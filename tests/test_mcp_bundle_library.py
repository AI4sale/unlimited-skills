"""E20: local MCP profile bundle library and activation manager.

Proves the contract of docs/mcp-bundle-library.md against
``unlimited_skills/mcp/bundle_library.py`` and the
``mcp profiles library`` CLI:

- the full operator lifecycle: publish via the REAL E19 ceremony -> add
  (verified through the REAL E14 path BEFORE storing) -> list/status ->
  activate (re-verified at activation time; atomic active.bundle.json
  pointer copy) -> the gateway resolves the active bundle through the real
  profile path under --require-signed-profiles -> deactivate (open-mode
  note) -> rollback (including the loud skip-revoked walk-back);
- add refuses invalid/tampered/expired/revoked/key-missing bundles with
  the EXACT reserved codes and stores nothing; duplicate add is an
  idempotent no-op; there is no quarantine mode;
- pin blocks remove (even --force); removing the ACTIVE bundle refuses
  without --force and deactivates first with it;
- doctor catches every documented problem class (missing/corrupt stored
  files, active-bundle-invalid exit 1 vs non-active warnings, stale active
  pointer, orphan files, corrupt state with rebuild guidance, history
  inconsistency);
- state-file corruption blocks mutations loudly while status/list still
  DESCRIBE the problem; a failed state write never leaves an orphan
  stored bundle (atomicity);
- leak-grep: no private key material in any library file or output, and
  audit-style outputs carry the source BASENAME only, never the operator's
  absolute source directory;
- CLI wiring and exit codes for the whole subgroup.
"""

from __future__ import annotations

import base64
import hashlib
import json
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

pytest.importorskip("cryptography")

from unlimited_skills.cli import main
from unlimited_skills.commands.mcp import _resolve_gateway_profile_state
from unlimited_skills.mcp import bundle_library
from unlimited_skills.mcp.bundle_library import (
    ACTIVE_BUNDLE_FILENAME,
    REBUILD_GUIDANCE,
    STATE_FILENAME,
    BundleLibrary,
    BundleLibraryError,
    add_bundle,
    activate_bundle,
    deactivate_bundle,
    doctor_report,
    inspect_report,
    list_report,
    read_state,
    remove_bundle,
    rollback_bundle,
    set_pinned,
    status_report,
)
from unlimited_skills.mcp.bundle_publisher import generate_keypair, publish_bundle
from unlimited_skills.mcp.bundles import (
    BUNDLE_EXPIRED,
    BUNDLE_KEY_MISSING,
    BUNDLE_REVOKED,
    BUNDLE_SIGNATURE_INVALID,
)
from unlimited_skills.mcp.profiles import PROFILE_INVALID, ActiveProfile
from unlimited_skills.mcp.trust_store import TrustStore, import_key, load_key_file, revoke

PROFILE_DOC = {
    "schema_version": 1,
    "default_profile": "dev",
    "profiles": {
        "dev": {"visible": ["fake.*"], "callable": ["fake.*"]},
        "reviewer": {"extends": "dev", "visible": ["fake.echo"], "callable": ["fake.echo"]},
    },
}

KEY_ID = "e20-dev-key-2026"
AUDIENCE = "team:e20"
EMPTY_CRL = {"schema_version": 1, "revoked_bundles": [], "revoked_key_ids": []}


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("UNLIMITED_SKILLS_MCP_PROFILE", raising=False)
    monkeypatch.delenv("UNLIMITED_SKILLS_MCP_AUDIENCE", raising=False)


class Setup:
    """One trust store + DEV keypair + a publish helper (the REAL E19
    ceremony) producing distinct signed bundle files."""

    def __init__(self, tmp_path: Path) -> None:
        self.tmp_path = tmp_path
        self.now = time.time()
        self.store = TrustStore(tmp_path / "trust-store")
        self.generated = generate_keypair(tmp_path / "keys", key_id=KEY_ID, display="E20 issuer")
        public_doc = load_key_file(Path(self.generated["public_key_path"]))
        import_key(self.store, key_id=KEY_ID, public_key_b64=str(public_doc["public_key"]))
        self.store.crl_path.parent.mkdir(parents=True, exist_ok=True)
        self.store.crl_path.write_text(json.dumps(EMPTY_CRL), encoding="utf-8")
        self.profiles_path = tmp_path / "team-profiles.json"
        self.profiles_path.write_text(json.dumps(PROFILE_DOC), encoding="utf-8")
        self.incoming = tmp_path / "incoming"
        self.library = BundleLibrary(tmp_path / "bundle-library")
        self._offset = 0

    def publish(self, name: str, with_crl: bool = True, expires_days: int = 30) -> Path:
        """Publish one signed bundle into the incoming dir; distinct ``now``
        offsets guarantee distinct file SHA-256s."""
        self._offset += 10
        publish_bundle(
            self.profiles_path,
            Path(self.generated["private_key_path"]),
            audience=[AUDIENCE],
            expires_days=expires_days,
            out_dir=self.incoming,
            name=name,
            crl_path=str(self.store.crl_path) if with_crl else "",
            now=self.now + self._offset,
            force=True,
        )
        return self.incoming / f"{name}.bundle.json"

    def add(self, path: Path, **kwargs) -> dict:
        kwargs.setdefault("trusted_keys_path", self.store.trusted_keys_path)
        kwargs.setdefault("now", self.now + 100)
        return add_bundle(self.library, path, **kwargs)

    def kwargs(self, **overrides) -> dict:
        merged = {"trusted_keys_path": self.store.trusted_keys_path, "now": self.now + 100}
        merged.update(overrides)
        return merged


@pytest.fixture
def setup(tmp_path: Path) -> Setup:
    return Setup(tmp_path)


def sha_of(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


# ---------------------------------------------------------------------------
# add / list / status basics.


def test_add_verifies_then_stores_content_addressed(setup: Setup) -> None:
    bundle = setup.publish("team-v1")
    sha = sha_of(bundle)
    result = setup.add(bundle)
    assert result["added"] is True and result["sha256"] == sha
    assert result["name"] == "team-v1" and result["verification"] == "verified"
    stored = setup.library.directory / f"{sha[:12]}-team-v1.bundle.json"
    assert stored.is_file() and stored.read_bytes() == bundle.read_bytes()
    state, problems = read_state(setup.library)
    assert problems == []
    entry = state["entries"][0]
    assert entry["sha256"] == sha and entry["issuer_key_id"] == KEY_ID
    assert entry["audience"] == [AUDIENCE] and entry["pinned"] is False
    assert entry["source"] == "team-v1.bundle.json"  # basename only
    assert state["active_sha256"] == "" and state["history"] == []


def test_duplicate_add_is_idempotent_no_op(setup: Setup) -> None:
    bundle = setup.publish("team-v1")
    first = setup.add(bundle)
    second = setup.add(bundle)
    assert second["added"] is False and second["already_present"] is True
    assert second["sha256"] == first["sha256"]
    state, _ = read_state(setup.library)
    assert len(state["entries"]) == 1


def test_add_refuses_duplicate_name_with_different_content(setup: Setup) -> None:
    setup.add(setup.publish("team-v1"))
    other = setup.publish("team-v2")
    renamed = setup.incoming / "team-v1-copy.bundle.json"
    renamed.write_bytes(other.read_bytes())
    with pytest.raises(BundleLibraryError, match="already used"):
        setup.add(renamed, name="team-v1")
    # A distinct --name installs fine.
    result = setup.add(renamed, name="team-v2")
    assert result["added"] is True


def test_list_and_status_reports(setup: Setup) -> None:
    setup.add(setup.publish("team-v1"))
    setup.add(setup.publish("team-v2"))
    report = list_report(setup.library, **setup.kwargs())
    assert [entry["name"] for entry in report["entries"]] == ["team-v1", "team-v2"]
    assert all(entry["state"] == "ok" for entry in report["entries"])
    assert all(not entry["active"] and not entry["pinned"] for entry in report["entries"])
    status = status_report(setup.library, **setup.kwargs())
    assert status["active"] == {} and status["counts"] == {"total": 2, "pinned": 0}
    assert status["problems"] == []


# ---------------------------------------------------------------------------
# Full lifecycle: add -> activate -> gateway -> deactivate -> rollback.


def test_full_lifecycle_with_real_gateway_resolution(setup: Setup) -> None:
    v1 = setup.publish("team-v1")
    v2 = setup.publish("team-v2")
    sha_v1, sha_v2 = sha_of(v1), sha_of(v2)
    setup.add(v1)
    setup.add(v2)

    activated = activate_bundle(setup.library, "team-v1", **setup.kwargs())
    assert activated["activated"] is True and activated["sha256"] == sha_v1
    assert "no hot reload" in activated["note"]
    pointer = setup.library.active_bundle_path
    assert pointer.is_file() and sha_of(pointer) == sha_v1

    status = status_report(setup.library, **setup.kwargs())
    assert status["active"]["sha256"] == sha_v1
    assert status["active"]["issuer_key_id"] == KEY_ID
    assert status["active"]["verifies_now"] is True and status["active"]["recheck"] == "ok"
    assert status["active"]["days_left"] is not None and 28 < status["active"]["days_left"] < 31
    assert status["active_bundle_file"] == ACTIVE_BUNDLE_FILENAME

    # The gateway resolves the ACTIVE pointer through the REAL profile path,
    # even under the signed-required policy.
    state, note = _resolve_gateway_profile_state(
        SimpleNamespace(
            profiles="",
            profile="",
            profile_bundle=str(pointer),
            trusted_keys=str(setup.store.trusted_keys_path),
            audience_id=[AUDIENCE],
            require_signed_profiles=True,
            root="",
        )
    )
    assert isinstance(state, ActiveProfile) and state.name == "dev"
    assert state.is_callable("fake", "echo") and not state.is_visible("other", "tool")
    assert "signed bundle profile 'dev' enforced" in note

    # Activate v2; one active at a time.
    activate_bundle(setup.library, sha_v2[:12], **setup.kwargs())
    assert sha_of(pointer) == sha_v2
    listed = list_report(setup.library, **setup.kwargs())
    assert [entry["active"] for entry in listed["entries"]] == [False, True]

    # Rollback re-activates the previous known-good entry.
    rolled = rollback_bundle(setup.library, **setup.kwargs())
    assert rolled["rolled_back"] is True and rolled["sha256"] == sha_v1
    assert rolled["action"] == "rollback" and rolled["skipped"] == []
    assert sha_of(pointer) == sha_v1

    # Deactivate: pointer removed, open-mode note, idempotent.
    result = deactivate_bundle(setup.library)
    assert result["deactivated"] is True and "OPEN no-profiles mode" in result["note"]
    assert not pointer.exists()
    again = deactivate_bundle(setup.library)
    assert again["already_inactive"] is True

    # The append-only history powered all of it.
    state_doc, _ = read_state(setup.library)
    actions = [(record["sha256"], record["action"]) for record in state_doc["history"]]
    assert actions == [
        (sha_v1, "activate"),
        (sha_v2, "activate"),
        (sha_v1, "rollback"),
        (sha_v1, "deactivate"),
    ]


def test_rollback_skips_revoked_and_walks_back_loudly(setup: Setup) -> None:
    shas = {}
    for name in ("team-v1", "team-v2", "team-v3"):
        path = setup.publish(name)
        shas[name] = sha_of(path)
        setup.add(path)
        activate_bundle(setup.library, name, **setup.kwargs())
    # v2 is revoked AFTER activation history was built.
    revoke(setup.store, bundle_sha256=shas["team-v2"], reason="e20 walk-back test")
    rolled = rollback_bundle(setup.library, **setup.kwargs())
    assert rolled["sha256"] == shas["team-v1"], "walked back past the revoked v2"
    assert len(rolled["skipped"]) == 1
    skipped = rolled["skipped"][0]
    assert skipped["sha256"] == shas["team-v2"]
    assert skipped["code"] == BUNDLE_REVOKED and skipped["refusal"] == "bundle_revoked"


def test_rollback_refuses_without_history_or_verifying_candidate(setup: Setup) -> None:
    with pytest.raises(BundleLibraryError, match="no previous bundle"):
        rollback_bundle(setup.library, **setup.kwargs())
    v1 = setup.publish("team-v1")
    v2 = setup.publish("team-v2")
    setup.add(v1)
    setup.add(v2)
    activate_bundle(setup.library, "team-v1", **setup.kwargs())
    activate_bundle(setup.library, "team-v2", **setup.kwargs())
    revoke(setup.store, bundle_sha256=sha_of(v1), reason="kill the only candidate")
    with pytest.raises(BundleLibraryError, match="bundle_revoked"):
        rollback_bundle(setup.library, **setup.kwargs())
    # Nothing changed: v2 stays active.
    state, _ = read_state(setup.library)
    assert state["active_sha256"] == sha_of(v2)


def test_activate_reverifies_at_activation_time(setup: Setup) -> None:
    bundle = setup.publish("team-v1")
    setup.add(bundle)
    # The CRL changed AFTER add: activation must re-verify and refuse.
    revoke(setup.store, bundle_sha256=sha_of(bundle), reason="revoked after add")
    with pytest.raises(BundleLibraryError, match="bundle_revoked") as excinfo:
        activate_bundle(setup.library, "team-v1", **setup.kwargs())
    assert excinfo.value.code == BUNDLE_REVOKED
    assert not setup.library.active_bundle_path.exists()


# ---------------------------------------------------------------------------
# add refusals: exact codes, nothing stored, no quarantine mode.


def assert_nothing_stored(library: BundleLibrary) -> None:
    state, _ = read_state(library)
    assert state["entries"] == []
    if library.directory.is_dir():
        assert list(library.directory.glob("*.bundle.json")) == []


def test_add_refuses_missing_and_invalid_files(setup: Setup) -> None:
    with pytest.raises(BundleLibraryError, match="missing or unreadable"):
        setup.add(setup.tmp_path / "absent.bundle.json")
    bad = setup.tmp_path / "bad.bundle.json"
    bad.write_text("{not json", encoding="utf-8")
    with pytest.raises(BundleLibraryError, match="profile_invalid") as excinfo:
        setup.add(bad)
    assert excinfo.value.code == PROFILE_INVALID
    assert_nothing_stored(setup.library)


def test_add_refuses_tampered_bundle(setup: Setup) -> None:
    bundle = setup.publish("team-v1")
    document = json.loads(bundle.read_text(encoding="utf-8"))
    document["audience"].append("org:everyone")
    bundle.write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises(BundleLibraryError, match="bundle_signature_invalid") as excinfo:
        setup.add(bundle)
    assert excinfo.value.code == BUNDLE_SIGNATURE_INVALID
    assert_nothing_stored(setup.library)


def test_add_refuses_expired_bundle(setup: Setup) -> None:
    bundle = setup.publish("team-v1", expires_days=1)
    with pytest.raises(BundleLibraryError, match="bundle_expired") as excinfo:
        setup.add(bundle, now=setup.now + 10 * 86400.0)
    assert excinfo.value.code == BUNDLE_EXPIRED
    assert_nothing_stored(setup.library)


def test_add_refuses_revoked_bundle(setup: Setup) -> None:
    bundle = setup.publish("team-v1")
    revoke(setup.store, bundle_sha256=sha_of(bundle), reason="e20 add test")
    with pytest.raises(BundleLibraryError, match="bundle_revoked") as excinfo:
        setup.add(bundle)
    assert excinfo.value.code == BUNDLE_REVOKED
    assert_nothing_stored(setup.library)


def test_add_refuses_without_trusted_keys(setup: Setup) -> None:
    bundle = setup.publish("team-v1")
    with pytest.raises(BundleLibraryError, match="bundle_key_missing") as excinfo:
        setup.add(bundle, trusted_keys_path="")
    assert excinfo.value.code == BUNDLE_KEY_MISSING
    assert_nothing_stored(setup.library)


def test_add_with_explicit_wrong_audience_refuses(setup: Setup) -> None:
    """Explicit --audience-id is checked strictly; only when omitted does
    the library use the bundle's own first audience (self-audience)."""
    bundle = setup.publish("team-v1")
    with pytest.raises(BundleLibraryError, match="bundle_audience_mismatch"):
        setup.add(bundle, audience_ids=["team:somebody-else"])
    result = setup.add(bundle, audience_ids=[AUDIENCE])
    assert result["added"] is True


# ---------------------------------------------------------------------------
# pin / unpin / remove semantics.


def test_pin_blocks_remove_even_with_force(setup: Setup) -> None:
    bundle = setup.publish("team-v1")
    setup.add(bundle)
    pinned = set_pinned(setup.library, "team-v1", True)
    assert pinned["pinned"] is True and pinned["changed"] is True
    again = set_pinned(setup.library, "team-v1", True)
    assert again["changed"] is False  # idempotent
    with pytest.raises(BundleLibraryError, match="PINNED"):
        remove_bundle(setup.library, "team-v1")
    with pytest.raises(BundleLibraryError, match="PINNED"):
        remove_bundle(setup.library, "team-v1", force=True)
    set_pinned(setup.library, "team-v1", False)
    result = remove_bundle(setup.library, "team-v1")
    assert result["removed"] is True
    assert_nothing_stored(setup.library)


def test_remove_active_refuses_without_force_and_deactivates_with_it(setup: Setup) -> None:
    bundle = setup.publish("team-v1")
    sha = sha_of(bundle)
    setup.add(bundle)
    activate_bundle(setup.library, "team-v1", **setup.kwargs())
    with pytest.raises(BundleLibraryError, match="ACTIVE"):
        remove_bundle(setup.library, "team-v1")
    assert setup.library.active_bundle_path.is_file(), "refusal changed nothing"
    result = remove_bundle(setup.library, "team-v1", force=True)
    assert result["removed"] is True and result["deactivated"] is True
    assert not setup.library.active_bundle_path.exists()
    state, _ = read_state(setup.library)
    assert state["active_sha256"] == "" and state["entries"] == []
    assert [record["action"] for record in state["history"]] == ["activate", "deactivate"]
    assert state["history"][-1]["sha256"] == sha


# ---------------------------------------------------------------------------
# inspect and reference resolution.


def test_inspect_reports_manifest_detail_and_recheck(setup: Setup) -> None:
    bundle = setup.publish("team-v1")
    sha = sha_of(bundle)
    setup.add(bundle)
    report = inspect_report(setup.library, sha[:12], **setup.kwargs())
    assert report["sha256"] == sha and report["name"] == "team-v1"
    assert report["issuer_key_id"] == KEY_ID and report["audience"] == [AUDIENCE]
    assert report["default_profile"] == "dev"
    assert report["allowed_upstream_namespaces"] == ["fake.*"]
    assert report["profiles"]["dev"] == {"visible_rules": 1, "callable_rules": 1}
    assert report["source"] == "team-v1.bundle.json"
    assert report["verification"]["ok"] is True and report["verification"]["state"] == "ok"
    # After revocation, inspect shows the CURRENT re-verification result.
    revoke(setup.store, bundle_sha256=sha, reason="e20 inspect test")
    report = inspect_report(setup.library, "team-v1", **setup.kwargs())
    assert report["verification"]["ok"] is False
    assert report["verification"]["code"] == BUNDLE_REVOKED
    assert report["verification"]["state"] == "revoked"


def test_unknown_reference_refuses(setup: Setup) -> None:
    setup.add(setup.publish("team-v1"))
    with pytest.raises(BundleLibraryError, match="no library entry matches"):
        activate_bundle(setup.library, "nope", **setup.kwargs())
    with pytest.raises(BundleLibraryError, match="reference .* is required"):
        activate_bundle(setup.library, "  ", **setup.kwargs())


# ---------------------------------------------------------------------------
# doctor: every documented problem class.


def test_doctor_clean_library_is_ok(setup: Setup) -> None:
    setup.add(setup.publish("team-v1"))
    report = doctor_report(setup.library, **setup.kwargs())
    assert report["status"] == "ok" and report["exit_code"] == 0
    assert report["problems"] == [] and report["warnings"] == []


def test_doctor_no_library_dir_is_ok(tmp_path: Path) -> None:
    report = doctor_report(BundleLibrary(tmp_path / "never-created"))
    assert report["exit_code"] == 0 and report["status"] == "ok"


def test_doctor_missing_and_corrupt_stored_files(setup: Setup) -> None:
    v1 = setup.publish("team-v1")
    v2 = setup.publish("team-v2")
    setup.add(v1)
    setup.add(v2)
    state, _ = read_state(setup.library)
    setup.library.stored_path(state["entries"][0]).unlink()
    corrupt = setup.library.stored_path(state["entries"][1])
    corrupt.write_text(corrupt.read_text(encoding="utf-8") + " ", encoding="utf-8")
    report = doctor_report(setup.library, **setup.kwargs())
    assert report["exit_code"] == 1
    assert any("is missing" in problem for problem in report["problems"])
    assert any("no longer match the recorded sha256" in problem for problem in report["problems"])


def test_doctor_active_invalid_is_problem_nonactive_is_warning(setup: Setup) -> None:
    v1 = setup.publish("team-v1")
    v2 = setup.publish("team-v2")
    setup.add(v1)
    setup.add(v2)
    activate_bundle(setup.library, "team-v2", **setup.kwargs())
    # Non-active v1 revoked: warning only, exit 0.
    revoke(setup.store, bundle_sha256=sha_of(v1), reason="non-active")
    report = doctor_report(setup.library, **setup.kwargs())
    assert report["exit_code"] == 0
    assert any("bundle_revoked" in warning for warning in report["warnings"])
    # ACTIVE v2 revoked: problem, exit 1, gateway warning.
    revoke(setup.store, bundle_sha256=sha_of(v2), reason="active")
    report = doctor_report(setup.library, **setup.kwargs())
    assert report["exit_code"] == 1
    assert any(
        "ACTIVE" in problem and "fail closed" in problem for problem in report["problems"]
    )


def test_doctor_expired_entries_warn_or_fail_by_active_state(setup: Setup) -> None:
    bundle = setup.publish("team-v1", expires_days=1)
    setup.add(bundle)
    future = setup.now + 10 * 86400.0
    report = doctor_report(setup.library, **setup.kwargs(now=future))
    assert report["exit_code"] == 0
    assert any("bundle_expired" in warning for warning in report["warnings"])
    activate_bundle(setup.library, "team-v1", **setup.kwargs())  # still valid now
    report = doctor_report(setup.library, **setup.kwargs(now=future))
    assert report["exit_code"] == 1
    assert any("bundle_expired" in problem for problem in report["problems"])


def test_doctor_orphans_stale_pointer_and_history(setup: Setup) -> None:
    bundle = setup.publish("team-v1")
    other = setup.publish("team-v2")
    setup.add(bundle)
    activate_bundle(setup.library, "team-v1", **setup.kwargs())
    # Orphan file in the library dir.
    (setup.library.directory / "stray.bundle.json").write_text("{}", encoding="utf-8")
    # Stale pointer: active.bundle.json bytes differ from the active entry.
    setup.library.active_bundle_path.write_bytes(other.read_bytes())
    report = doctor_report(setup.library, **setup.kwargs())
    assert report["exit_code"] == 1
    assert any("do not match the active entry" in problem for problem in report["problems"])
    assert any("orphan file stray.bundle.json" in warning for warning in report["warnings"])


def test_doctor_corrupt_state_file_gives_rebuild_guidance(setup: Setup) -> None:
    setup.add(setup.publish("team-v1"))
    setup.library.state_path.write_text("{broken", encoding="utf-8")
    report = doctor_report(setup.library, **setup.kwargs())
    assert report["exit_code"] == 1
    assert REBUILD_GUIDANCE in report["problems"]


def test_doctor_history_inconsistency(setup: Setup) -> None:
    bundle = setup.publish("team-v1")
    setup.add(bundle)
    state, _ = read_state(setup.library)
    state["active_sha256"] = sha_of(bundle)  # active without any history record
    setup.library.state_path.write_text(json.dumps(state), encoding="utf-8")
    setup.library.active_bundle_path.write_bytes(bundle.read_bytes())
    report = doctor_report(setup.library, **setup.kwargs())
    assert report["exit_code"] == 1
    assert any("no activation record" in problem for problem in report["problems"])


# ---------------------------------------------------------------------------
# State-file corruption and atomicity.


def test_corrupt_state_blocks_mutations_but_status_describes(setup: Setup) -> None:
    bundle = setup.publish("team-v1")
    setup.library.directory.mkdir(parents=True, exist_ok=True)
    setup.library.state_path.write_text("[]", encoding="utf-8")
    for operation in (
        lambda: setup.add(bundle),
        lambda: activate_bundle(setup.library, "x", **setup.kwargs()),
        lambda: rollback_bundle(setup.library, **setup.kwargs()),
        lambda: set_pinned(setup.library, "x", True),
        lambda: remove_bundle(setup.library, "x"),
        lambda: deactivate_bundle(setup.library),
    ):
        with pytest.raises(BundleLibraryError, match="rebuild"):
            operation()
    status = status_report(setup.library, **setup.kwargs())
    assert status["problems"], "status DESCRIBES the corrupt state instead of raising"
    listed = list_report(setup.library, **setup.kwargs())
    assert listed["problems"] and listed["entries"] == []


def test_failed_state_write_leaves_no_orphan_bundle(
    setup: Setup, monkeypatch: pytest.MonkeyPatch
) -> None:
    bundle = setup.publish("team-v1")

    def explode(path, document):
        raise OSError("simulated disk failure")

    monkeypatch.setattr(bundle_library, "_atomic_write_json", explode)
    with pytest.raises(OSError, match="simulated disk failure"):
        setup.add(bundle)
    monkeypatch.undo()
    assert_nothing_stored(setup.library)
    # The library still works after the failure.
    assert setup.add(bundle)["added"] is True


# ---------------------------------------------------------------------------
# Leak-grep: no key material anywhere; source paths as basenames only.


def test_no_key_material_and_no_source_paths_in_outputs(
    setup: Setup, capsys: pytest.CaptureFixture
) -> None:
    root = setup.tmp_path / "root"
    root.mkdir()
    bundle = setup.publish("team-v1")
    raw = Path(setup.generated["private_key_path"]).read_text(encoding="utf-8")
    body = "\n".join(line for line in raw.splitlines() if not line.lstrip().startswith("#"))
    seed_b64 = json.loads(body)["private_key"]
    secrets = (seed_b64, seed_b64.rstrip("="), base64.b64decode(seed_b64).hex())

    def cli(*argv: str) -> int:
        return main(
            [
                "--root",
                str(root),
                "mcp",
                "profiles",
                "library",
                argv[0],
                "--library-dir",
                str(setup.library.directory),
                "--trusted-keys",
                str(setup.store.trusted_keys_path),
                *argv[1:],
            ]
        )

    transcripts: list[str] = []
    assert cli("add", str(bundle), "--json") == 0
    transcripts.append(capsys.readouterr().out)
    assert cli("activate", "team-v1", "--json") == 0
    transcripts.append(capsys.readouterr().out)
    for command in ("status", "list", "doctor"):
        assert cli(command, "--json") == 0
        transcripts.append(capsys.readouterr().out)
    assert cli("inspect", "team-v1", "--json") == 0
    transcripts.append(capsys.readouterr().out)

    incoming_dir = str(setup.incoming)
    for index, transcript in enumerate(transcripts):
        for secret in secrets:
            assert secret not in transcript, f"output #{index} leaked private key material"
        assert "PRIVATE KEY" not in transcript.upper()
        assert incoming_dir not in transcript, (
            f"output #{index} leaked the operator's source directory (basenames only)"
        )
    # Library files carry no key material either (bundles hold public info only).
    for path in setup.library.directory.iterdir():
        text = path.read_text(encoding="utf-8", errors="replace")
        for secret in secrets:
            assert secret not in text, f"{path.name} leaked private key material"
        assert incoming_dir not in text, f"{path.name} stored an absolute source path"


# ---------------------------------------------------------------------------
# CLI wiring and exit codes.


def test_cli_lifecycle_and_exit_codes(setup: Setup, capsys: pytest.CaptureFixture) -> None:
    root = setup.tmp_path / "root"
    root.mkdir()
    v1 = setup.publish("team-v1")
    v2 = setup.publish("team-v2")

    def cli(*argv: str) -> int:
        return main(
            [
                "--root",
                str(root),
                "mcp",
                "profiles",
                "library",
                argv[0],
                "--library-dir",
                str(setup.library.directory),
                "--trusted-keys",
                str(setup.store.trusted_keys_path),
                *argv[1:],
            ]
        )

    assert cli("add", str(v1)) == 0
    assert "added bundle" in capsys.readouterr().out
    assert cli("add", str(v1)) == 0
    assert "already installed" in capsys.readouterr().out
    assert cli("add", str(v2), "--json") == 0
    capsys.readouterr()

    # Refusal: tampered bundle, loud stderr, exit 1.
    tampered = setup.incoming / "tampered.bundle.json"
    document = json.loads(v1.read_text(encoding="utf-8"))
    document["expires_at"] = "2099-01-01T00:00:00Z"
    tampered.write_text(json.dumps(document), encoding="utf-8")
    assert cli("add", str(tampered)) == 1
    captured = capsys.readouterr()
    assert "bundle library refused" in captured.err
    assert "bundle_signature_invalid" in captured.err

    assert cli("activate", "team-v1") == 0
    capsys.readouterr()
    assert cli("pin", "team-v1") == 0
    capsys.readouterr()
    assert cli("remove", "team-v1") == 1  # pinned (and active)
    assert "PINNED" in capsys.readouterr().err
    assert cli("unpin", "team-v1") == 0
    capsys.readouterr()
    assert cli("remove", "team-v1") == 1  # still active
    assert "ACTIVE" in capsys.readouterr().err
    assert cli("activate", "team-v2") == 0
    capsys.readouterr()
    assert cli("rollback") == 0
    assert "rolled back to bundle" in capsys.readouterr().out
    assert cli("status", "--json") == 0
    status = json.loads(capsys.readouterr().out)
    assert status["active"]["name"] == "team-v1"
    assert cli("doctor") == 0
    capsys.readouterr()
    assert cli("deactivate") == 0
    assert "OPEN no-profiles mode" in capsys.readouterr().out
    assert cli("remove", "team-v1") == 0
    capsys.readouterr()
    # Doctor exit 1 on a corrupted library.
    setup.library.state_path.write_text("{broken", encoding="utf-8")
    assert cli("doctor") == 1


def test_cli_defaults_to_managed_trust_store_under_root(
    setup: Setup, capsys: pytest.CaptureFixture
) -> None:
    """Without --trusted-keys the library uses the E15 managed store under
    <root>/.unlimited-skills-trust when it exists (exactly like the gateway)."""
    root = setup.tmp_path / "root"
    managed = TrustStore(root / ".unlimited-skills-trust")
    public_doc = load_key_file(Path(setup.generated["public_key_path"]))
    import_key(managed, key_id=KEY_ID, public_key_b64=str(public_doc["public_key"]))
    bundle = setup.publish("team-v1", with_crl=False)
    assert (
        main(
            [
                "--root",
                str(root),
                "mcp",
                "profiles",
                "library",
                "add",
                str(bundle),
                "--library-dir",
                str(setup.library.directory),
                "--json",
            ]
        )
        == 0
    )
    result = json.loads(capsys.readouterr().out)
    assert result["added"] is True and result["verification"] == "verified"
