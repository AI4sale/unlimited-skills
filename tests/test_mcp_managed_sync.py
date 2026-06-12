"""E27: managed profile sync client prototype (fixture-only).

Proves the contract of docs/mcp-managed-sync.md against
``unlimited_skills/mcp/managed_sync.py`` and the
``unlimited-skills mcp profiles managed sync|status|last-good|doctor`` CLI:

- the DEFAULT is dry-run: a sync pass verifies and reports without touching
  the library, the trust store, the source, or the sync state file (zero
  mutation, proven byte-for-byte);
- ``--apply`` stages the verified candidate through the REAL E20 library
  add but NEVER activates (no active pointer, no active_sha256);
- conflict resolution is the E23 decision-6 order (host beats team, pin
  beats follow) and a residual tie refuses loudly with ``assignment_tie``;
- the anti-rollback watermark refuses a source presenting a LOWER channel
  revision (``routing_revision_regression``) and the state stays untouched;
- URL-shaped sources refuse outright (hosted sync not implemented; design
  gated);
- tampered/unsigned routing files, carrier-summary downgrades, and
  revoked/expired/wrong-audience bundles refuse with the exact E26 reason
  names and the reserved E14 codes (-32016/-32017/-32018) -- never a new
  numeric code;
- ``last-good --restore`` re-stages through the real library machinery
  (verify-before-store) and never bypasses verification;
- ``doctor`` finds the documented problem classes (corrupt state, replay
  against the watermark, staged bundle no longer verifying) and reports
  drift/expiry as warnings;
- the state file is written atomically, contains identifiers/shas/revisions
  only, and the CLI text outputs leak no secrets or local paths;
- containment: nothing outside the member's library/state is written and
  the repo's managed stores are never touched;
- the module imports no network-capable library (the stabilization-audit
  invariant, asserted locally too).
"""

from __future__ import annotations

import ast
import hashlib
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

pytest.importorskip("cryptography")

from unlimited_skills.cli import build_parser
from unlimited_skills.mcp import managed_sync
from unlimited_skills.mcp.audit import _PATH_PATTERN as PATH_PATTERN
from unlimited_skills.mcp.audit import looks_secret
from unlimited_skills.mcp.bundle_library import (
    ACTIVE_BUNDLE_FILENAME,
    BundleLibrary,
    activate_bundle,
    read_state,
    remove_bundle,
)
from unlimited_skills.mcp.bundle_publisher import (
    generate_keypair,
    load_signing_key,
    publish_bundle,
)
from unlimited_skills.mcp.managed_sync import (
    DistributionRefusal,
    forbidden_field_names,
    last_good_report,
    managed_doctor_report,
    managed_status_report,
    read_sync_state,
    sync_managed_profile,
    sync_state_path,
)
from unlimited_skills.mcp.trust_store import TrustStore, import_key, load_key_file, revoke

ROOT = Path(__file__).resolve().parents[1]
HARNESS_PATH = ROOT / "scripts" / "run-mcp-profile-distribution-fixture-e2e.py"

ISSUER = "managed-sync-issuer-2026"
CARRIER = "managed-sync-carrier-2026"
TEAM = "team:managed"
HOST = "host:managed-ci"
FOREIGN = "team:somewhere-else"
MEMBER = [TEAM, HOST]
DAY = 86400.0

EMPTY_CRL = {"schema_version": 1, "revoked_bundles": [], "revoked_key_ids": []}


def _load_harness():
    spec = importlib.util.spec_from_file_location("mcp_distribution_fixture_harness", HARNESS_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def harness():
    return _load_harness()


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("UNLIMITED_SKILLS_MCP_PROFILE", raising=False)
    monkeypatch.delenv("UNLIMITED_SKILLS_MCP_AUDIENCE", raising=False)


PROFILE_DOC = {
    "schema_version": 1,
    "default_profile": "dev",
    "profiles": {"dev": {"visible": ["fake.*"], "callable": ["fake.*"]}},
}


def make_env(harness, base: Path, assignment_mode: str = "follow") -> SimpleNamespace:
    """One self-contained fixture environment under ``base``.

    Builds DEV keys, an E15 store under ``<root>/.unlimited-skills-trust``,
    two published bundles (team-v1/team-v2) plus a foreign-audience bundle,
    and a fixture-source directory in the E26 registry layout with channel
    revisions 1 -> 2 and one live assignment for the member's team.
    """
    import time

    now = time.time()
    root = base / "root"
    store = TrustStore(root / ".unlimited-skills-trust")
    keys: dict[str, object] = {}
    private_paths: dict[str, Path] = {}
    for key_id in (ISSUER, CARRIER):
        result = generate_keypair(base / "keys" / key_id, key_id=key_id, now=now)
        keys[key_id] = load_signing_key(Path(result["private_key_path"]))
        private_paths[key_id] = Path(result["private_key_path"])
        if key_id == ISSUER:
            public_doc = load_key_file(Path(result["public_key_path"]))
            import_key(
                store,
                key_id=key_id,
                public_key_b64=str(public_doc["public_key"]),
                display=f"{key_id} (DEV)",
                now=now,
            )
    store.crl_path.parent.mkdir(parents=True, exist_ok=True)
    store.crl_path.write_text(json.dumps(EMPTY_CRL), encoding="utf-8")

    profiles_path = base / "team-profiles.json"
    profiles_path.write_text(json.dumps(PROFILE_DOC), encoding="utf-8")
    issuer_private = private_paths[ISSUER]
    shas: dict[str, str] = {}
    paths: dict[str, Path] = {}
    for offset, name, audience in (
        (0.0, "team-v1", MEMBER),
        (10.0, "team-v2", MEMBER),
        (20.0, "other-team-v1", [FOREIGN]),
    ):
        result = publish_bundle(
            profiles_path,
            issuer_private,
            audience=list(audience),
            expires_days=30,
            out_dir=base / "staging",
            name=name,
            crl_path=str(store.crl_path),
            now=now + offset,
        )
        assert result["published"] is True
        shas[name] = result["bundle_sha256"]
        paths[name] = base / "staging" / f"{name}.bundle.json"

    registry = harness.FixtureRegistry(base / "fixture-source", keys[CARRIER], clock=now)
    for name in ("team-v1", "team-v2", "other-team-v1"):
        registry.put_bundle(paths[name])
        registry.put_summary(paths[name])
    issuer_key = keys[ISSUER]
    v1_record = {
        "bundle_sha256": shas["team-v1"],
        "published_at": harness._utc(now - 900),
        "status": "active",
    }
    revision1 = harness.build_channel("stable", issuer_key, [dict(v1_record)], revision=1)
    registry.put_channel(revision1)
    history = [
        {**v1_record, "status": "superseded"},
        {
            "bundle_sha256": shas["team-v2"],
            "published_at": harness._utc(now - 600),
            "status": "active",
        },
    ]
    revision2 = harness.build_channel("stable", issuer_key, history, revision=2)
    registry.put_channel(revision2)
    assignment = harness.build_assignment(
        [TEAM],
        "stable",
        ISSUER,
        assignment_mode,
        issuer_key,
        revision=1,
        issued_at=harness._utc(now - 600),
        expires_at=harness._utc(now + 60 * DAY),
        bundle_sha256=shas["team-v1"] if assignment_mode == "pin" else "",
    )
    registry.put_assignment("team-managed", assignment)

    library = BundleLibrary(root / ".unlimited-skills-bundles")
    library.directory.mkdir(parents=True, exist_ok=True)
    return SimpleNamespace(
        now=now,
        root=root,
        store=store,
        registry=registry,
        source=registry.root,
        library=library,
        shas=shas,
        bundle_paths=paths,
        issuer_key=issuer_key,
        carrier_key=keys[CARRIER],
        revisions={1: revision1, 2: revision2},
        assignment=assignment,
        kwargs=dict(
            trusted_keys_path=str(store.trusted_keys_path),
            crl_path=str(store.crl_path),
            audience_ids=list(MEMBER),
            now=now,
        ),
    )


def _tree_snapshot(*roots: Path) -> dict[str, str]:
    snapshot: dict[str, str] = {}
    for root in roots:
        if not root.exists():
            snapshot[str(root)] = "<absent>"
            continue
        for path in sorted(root.rglob("*")):
            if path.is_file():
                snapshot[str(path)] = hashlib.sha256(path.read_bytes()).hexdigest()
    return snapshot


# ---------------------------------------------------------------------------
# Dry-run default: zero mutation, full preview.


def test_dry_run_default_reports_without_any_mutation(harness, tmp_path: Path) -> None:
    env = make_env(harness, tmp_path)
    before = _tree_snapshot(env.library.directory, env.store.trusted_keys_path.parent, env.source)
    report = sync_managed_profile(env.library, env.source, **env.kwargs)
    assert report["dry_run"] is True
    assert report["synced"] is False
    assert report["resolution"] == "ok"
    assert report["assignment"]["label"] == "team-managed"
    assert report["bundle_sha256"] == env.shas["team-v2"]
    assert report["channel"]["watermark_before"] == 0
    assert report["channel"]["watermark_after"] == 2
    assert report["would_stage"] is True and report["already_staged"] is False
    assert report["verification"] == {"ok": True, "via": "resolve_bundle_state (E14)"}
    assert "NEVER activates" in report["activation_note"]
    # Zero mutation: no state file, no library entries, nothing changed.
    assert not sync_state_path(env.library).exists()
    state, _ = read_state(env.library)
    assert state["entries"] == [] and state["active_sha256"] == ""
    assert _tree_snapshot(
        env.library.directory, env.store.trusted_keys_path.parent, env.source
    ) == before


# ---------------------------------------------------------------------------
# --apply: stages through the real E20 add, records state, never activates.


def test_apply_stages_records_state_and_never_activates(harness, tmp_path: Path) -> None:
    env = make_env(harness, tmp_path)
    report = sync_managed_profile(env.library, env.source, apply=True, **env.kwargs)
    assert report["synced"] is True and report["dry_run"] is False
    assert report["staged_as"] == f"managed-{env.shas['team-v2'][:12]}"
    state, problems = read_state(env.library)
    assert problems == []
    assert [entry["sha256"] for entry in state["entries"]] == [env.shas["team-v2"]]
    assert state["entries"][0]["verification"] == "verified"
    # NEVER activated: no active sha, no active pointer file, no history.
    assert state["active_sha256"] == ""
    assert not (env.library.directory / ACTIVE_BUNDLE_FILENAME).exists()
    assert state["history"] == []
    sync_state, sync_problems = read_sync_state(sync_state_path(env.library))
    assert sync_problems == []
    assert sync_state["source_id"] == "fixture-source"
    assert sync_state["watermarks"] == {f"stable@{ISSUER}": 2}
    assert sync_state["last_sync"]["result"] == "ok"
    assert sync_state["last_sync"]["bundle_sha256"] == env.shas["team-v2"]
    assert sync_state["last_good_bundle_sha256"] == env.shas["team-v2"]
    # No temp-file leftovers from the atomic write.
    assert list((env.library.directory / managed_sync.SYNC_DIRNAME).glob("*.tmp")) == []
    # Identifiers/shas/revisions only: no local paths, no forbidden fields.
    raw = sync_state_path(env.library).read_text(encoding="utf-8")
    assert not PATH_PATTERN.search(raw)
    assert forbidden_field_names(json.loads(raw)) == set()
    # Idempotent second pass: already staged, watermark unchanged.
    again = sync_managed_profile(env.library, env.source, apply=True, **env.kwargs)
    assert again["already_staged"] is True and "staged_as" not in again
    assert read_sync_state(sync_state_path(env.library))[0]["watermarks"] == {
        f"stable@{ISSUER}": 2
    }


# ---------------------------------------------------------------------------
# E23 decision-6 conflict resolution.


def test_host_assignment_beats_team_assignment(harness, tmp_path: Path) -> None:
    env = make_env(harness, tmp_path)
    host_follow = harness.build_assignment(
        [HOST], "stable", ISSUER, "follow", env.issuer_key,
        revision=1,
        issued_at=harness._utc(env.now - 700),
        expires_at=harness._utc(env.now + 60 * DAY),
    )
    env.registry.put_assignment("host-managed", host_follow)
    report = sync_managed_profile(env.library, env.source, **env.kwargs)
    assert report["resolution"] == "ok"
    assert report["assignment"]["label"] == "host-managed"


def test_pin_beats_follow_and_resolves_the_pinned_sha(harness, tmp_path: Path) -> None:
    env = make_env(harness, tmp_path)
    pin = harness.build_assignment(
        [TEAM], "stable", ISSUER, "pin", env.issuer_key,
        revision=2,
        issued_at=harness._utc(env.now - 500),
        expires_at=harness._utc(env.now + 60 * DAY),
        bundle_sha256=env.shas["team-v1"],
    )
    env.registry.put_assignment("team-pin", pin)
    report = sync_managed_profile(env.library, env.source, **env.kwargs)
    assert report["assignment"]["label"] == "team-pin"
    assert report["assignment"]["mode"] == "pin"
    # Pin wins over channel movement: the candidate is v1, not current v2.
    assert report["bundle_sha256"] == env.shas["team-v1"]
    assert report["channel"]["revision"] == 2


def test_exact_tie_is_refused_loudly_with_nothing_written(harness, tmp_path: Path) -> None:
    env = make_env(harness, tmp_path)
    twin = harness.build_assignment(
        [TEAM], "stable", ISSUER, "follow", env.issuer_key,
        revision=1,
        issued_at=env.assignment["issued_at"],
        expires_at=env.assignment["expires_at"],
    )
    env.registry.put_assignment("team-managed-twin", twin)
    before = _tree_snapshot(env.library.directory)
    with pytest.raises(DistributionRefusal) as exc_info:
        sync_managed_profile(env.library, env.source, apply=True, **env.kwargs)
    assert exc_info.value.reason == "assignment_tie"
    assert "team-managed" in str(exc_info.value)
    assert "team-managed-twin" in str(exc_info.value)
    assert not sync_state_path(env.library).exists()
    assert _tree_snapshot(env.library.directory) == before


def test_expired_assignment_directs_no_new_staging(harness, tmp_path: Path) -> None:
    env = make_env(harness, tmp_path)
    expired = harness.build_assignment(
        [TEAM], "stable", ISSUER, "follow", env.issuer_key,
        revision=2,
        issued_at=harness._utc(env.now - 60 * DAY),
        expires_at=harness._utc(env.now - 30 * DAY),
    )
    env.registry.assignments_dir.joinpath("team-managed.assignment.json").unlink()
    env.registry.assignment_labels.remove("team-managed")
    env.registry.put_assignment("expired-routing", expired)
    report = sync_managed_profile(env.library, env.source, apply=True, **env.kwargs)
    assert report["resolution"] == "expired"
    assert report["expired_assignments"] == ["expired-routing"]
    assert "EXPIRED" in report["note"]
    assert not sync_state_path(env.library).exists()
    state, _ = read_state(env.library)
    assert state["entries"] == []


# ---------------------------------------------------------------------------
# Anti-rollback watermark.


def test_lower_channel_revision_refuses_and_leaves_state_untouched(
    harness, tmp_path: Path
) -> None:
    env = make_env(harness, tmp_path)
    sync_managed_profile(env.library, env.source, apply=True, **env.kwargs)
    state_bytes = sync_state_path(env.library).read_bytes()
    # The source replays the legitimately signed but SUPERSEDED revision 1.
    channel_path = env.registry.channels_dir / f"{ISSUER}.stable.channel.json"
    channel_path.write_text(json.dumps(env.revisions[1], sort_keys=True), encoding="utf-8")
    with pytest.raises(DistributionRefusal) as exc_info:
        sync_managed_profile(env.library, env.source, apply=True, **env.kwargs)
    assert exc_info.value.reason == "routing_revision_regression"
    assert "watermark" in str(exc_info.value)
    assert sync_state_path(env.library).read_bytes() == state_bytes
    # The dry-run preview refuses identically (same watermark, no mutation).
    with pytest.raises(DistributionRefusal):
        sync_managed_profile(env.library, env.source, **env.kwargs)


# ---------------------------------------------------------------------------
# URL sources refuse: hosted sync not implemented; design gated.


@pytest.mark.parametrize(
    "url",
    [
        "https://unlimited.example/registry",
        "http://localhost:8080/sync",
        "registry+ssh://host/path",
    ],
)
def test_url_shaped_sources_refuse_outright(harness, tmp_path: Path, url: str) -> None:
    env = make_env(harness, tmp_path)
    with pytest.raises(DistributionRefusal) as exc_info:
        sync_managed_profile(env.library, url, apply=True, **env.kwargs)
    assert exc_info.value.reason == "source_url_rejected"
    assert "hosted sync is not implemented" in str(exc_info.value)
    assert "design gated" in str(exc_info.value)
    assert not sync_state_path(env.library).exists()


def test_non_layout_directory_refuses_as_source_invalid(harness, tmp_path: Path) -> None:
    env = make_env(harness, tmp_path)
    with pytest.raises(DistributionRefusal) as exc_info:
        sync_managed_profile(env.library, tmp_path / "not-a-registry", **env.kwargs)
    assert exc_info.value.reason == "source_invalid"


# ---------------------------------------------------------------------------
# Tampered / unsigned / revoked / expired refusals with exact codes.


def test_tampered_assignment_refuses_routing_signature_invalid(
    harness, tmp_path: Path
) -> None:
    env = make_env(harness, tmp_path)
    path = env.registry.assignments_dir / "team-managed.assignment.json"
    document = json.loads(path.read_text(encoding="utf-8"))
    document["revision"] = 9  # edited after signing
    path.write_text(json.dumps(document, sort_keys=True), encoding="utf-8")
    with pytest.raises(DistributionRefusal) as exc_info:
        sync_managed_profile(env.library, env.source, **env.kwargs)
    assert exc_info.value.reason == "routing_signature_invalid"
    assert exc_info.value.code == 0  # routing layer: reason names, no numeric codes


def test_unsigned_assignment_refuses_routing_unsigned(harness, tmp_path: Path) -> None:
    env = make_env(harness, tmp_path)
    path = env.registry.assignments_dir / "team-managed.assignment.json"
    document = json.loads(path.read_text(encoding="utf-8"))
    document.pop("signature")
    path.write_text(json.dumps(document, sort_keys=True), encoding="utf-8")
    with pytest.raises(DistributionRefusal) as exc_info:
        sync_managed_profile(env.library, env.source, **env.kwargs)
    assert exc_info.value.reason == "routing_unsigned"


def test_tampered_channel_refuses_routing_signature_invalid(
    harness, tmp_path: Path
) -> None:
    env = make_env(harness, tmp_path)
    path = env.registry.channels_dir / f"{ISSUER}.stable.channel.json"
    document = json.loads(path.read_text(encoding="utf-8"))
    document["revision"] = 3  # an attacker bumps the revision to force movement
    path.write_text(json.dumps(document, sort_keys=True), encoding="utf-8")
    with pytest.raises(DistributionRefusal) as exc_info:
        sync_managed_profile(env.library, env.source, **env.kwargs)
    assert exc_info.value.reason == "routing_signature_invalid"


def test_summary_downgrades_refuse_with_the_e26_reasons(harness, tmp_path: Path) -> None:
    env = make_env(harness, tmp_path)
    path = env.registry.summaries_dir / f"{env.shas['team-v2']}.summary.json"
    summary = json.loads(path.read_text(encoding="utf-8"))
    unsigned = {key: value for key, value in summary.items() if key != "signature"}
    path.write_text(json.dumps(unsigned, sort_keys=True), encoding="utf-8")
    with pytest.raises(DistributionRefusal) as exc_info:
        sync_managed_profile(env.library, env.source, **env.kwargs)
    assert exc_info.value.reason == "unsigned_artifact_rejected"
    smuggled = dict(summary)
    smuggled["profile_rules"] = ["fake.*"]  # a decision-20 denylisted field
    path.write_text(json.dumps(smuggled, sort_keys=True), encoding="utf-8")
    with pytest.raises(DistributionRefusal) as exc_info:
        sync_managed_profile(env.library, env.source, **env.kwargs)
    assert exc_info.value.reason == "forbidden_field_rejected"


def test_carrier_revoked_summary_refuses_bundle_revoked(harness, tmp_path: Path) -> None:
    env = make_env(harness, tmp_path)
    env.registry.put_summary(env.bundle_paths["team-v2"], status="revoked")
    with pytest.raises(DistributionRefusal) as exc_info:
        sync_managed_profile(env.library, env.source, apply=True, **env.kwargs)
    assert exc_info.value.reason == "bundle_revoked"
    assert not sync_state_path(env.library).exists()


def test_crl_revoked_bundle_refuses_with_code_32017(harness, tmp_path: Path) -> None:
    env = make_env(harness, tmp_path)
    revoke(
        env.store,
        bundle_sha256=env.shas["team-v2"],
        reason="managed sync drill",
        now=env.now,
    )
    with pytest.raises(DistributionRefusal) as exc_info:
        sync_managed_profile(env.library, env.source, apply=True, **env.kwargs)
    assert exc_info.value.reason == "bundle_revoked"
    assert exc_info.value.code == -32017
    state, _ = read_state(env.library)
    assert state["entries"] == []


def test_expired_bundle_refuses_with_code_32016(harness, tmp_path: Path) -> None:
    env = make_env(harness, tmp_path)
    kwargs = dict(env.kwargs)
    kwargs["now"] = env.now + 40 * DAY  # past the 30-day publish window
    with pytest.raises(DistributionRefusal) as exc_info:
        sync_managed_profile(env.library, env.source, apply=True, **kwargs)
    assert exc_info.value.reason == "bundle_expired"
    assert exc_info.value.code == -32016


def test_wrong_audience_bundle_refuses_with_code_32018(harness, tmp_path: Path) -> None:
    env = make_env(harness, tmp_path)
    # A signed pin assignment routes the member at the OTHER team's bundle:
    # routing resolves, but the bundle's own audience binding refuses.
    misrouted = harness.build_assignment(
        [TEAM], "stable", ISSUER, "pin", env.issuer_key,
        revision=3,
        issued_at=harness._utc(env.now - 400),
        expires_at=harness._utc(env.now + 60 * DAY),
        bundle_sha256=env.shas["other-team-v1"],
    )
    env.registry.put_assignment("misrouted-pin", misrouted)
    with pytest.raises(DistributionRefusal) as exc_info:
        sync_managed_profile(env.library, env.source, apply=True, **env.kwargs)
    assert exc_info.value.reason == "bundle_audience_mismatch"
    assert exc_info.value.code == -32018


# ---------------------------------------------------------------------------
# status: watermarks, staged-not-activated, drift.


def test_status_reports_staged_not_activated_and_drift(harness, tmp_path: Path) -> None:
    env = make_env(harness, tmp_path)
    report = managed_status_report(env.library, **{
        key: value for key, value in env.kwargs.items() if key != "crl_path"
    })
    assert report["synced_ever"] is False
    sync_managed_profile(env.library, env.source, apply=True, **env.kwargs)
    report = managed_status_report(
        env.library,
        trusted_keys_path=env.kwargs["trusted_keys_path"],
        audience_ids=MEMBER,
        now=env.now,
    )
    assert report["synced_ever"] is True
    assert report["watermarks"] == {f"stable@{ISSUER}": 2}
    assert report["staged_not_activated"] == [env.shas["team-v2"]]
    assert report["drift"]["in_sync"] is False  # nothing active yet
    # Activate the EXPECTED bundle explicitly through the library: in sync.
    activate_bundle(
        env.library,
        env.shas["team-v2"],
        trusted_keys_path=env.kwargs["trusted_keys_path"],
        audience_ids=MEMBER,
        now=env.now,
    )
    report = managed_status_report(
        env.library,
        trusted_keys_path=env.kwargs["trusted_keys_path"],
        audience_ids=MEMBER,
        now=env.now,
    )
    assert report["drift"]["in_sync"] is True
    assert report["staged_not_activated"] == []


# ---------------------------------------------------------------------------
# last-good: shown and restored through the REAL library machinery.


def test_last_good_restore_re_stages_via_the_real_library(harness, tmp_path: Path) -> None:
    env = make_env(harness, tmp_path)
    no_history = last_good_report(env.library, now=env.now)
    assert no_history["available"] is False and no_history["exit_code"] == 1
    sync_managed_profile(env.library, env.source, apply=True, **env.kwargs)
    shown = last_good_report(
        env.library,
        trusted_keys_path=env.kwargs["trusted_keys_path"],
        audience_ids=MEMBER,
        now=env.now,
    )
    assert shown["last_good_bundle_sha256"] == env.shas["team-v2"]
    assert shown["in_library"] is True and shown["verifies_now"] is True
    assert shown["exit_code"] == 0
    # The bundle disappears from the library; restore re-stages it through
    # the real add (verify-before-store), still without activating.
    remove_bundle(env.library, env.shas["team-v2"])
    missing = last_good_report(
        env.library,
        trusted_keys_path=env.kwargs["trusted_keys_path"],
        audience_ids=MEMBER,
        now=env.now,
    )
    assert missing["in_library"] is False and missing["exit_code"] == 1
    restored = last_good_report(
        env.library,
        trusted_keys_path=env.kwargs["trusted_keys_path"],
        audience_ids=MEMBER,
        restore=True,
        source=env.source,
        now=env.now,
    )
    assert restored["restored"] is True
    assert restored["staged_as"] == f"managed-{env.shas['team-v2'][:12]}"
    state, _ = read_state(env.library)
    assert [entry["sha256"] for entry in state["entries"]] == [env.shas["team-v2"]]
    assert state["active_sha256"] == ""  # never activated by restore
    # Restoration never bypasses verification: a now-revoked last-good
    # bundle refuses with the exact reserved code.
    remove_bundle(env.library, env.shas["team-v2"])
    revoke(env.store, bundle_sha256=env.shas["team-v2"], reason="drill", now=env.now)
    with pytest.raises(DistributionRefusal) as exc_info:
        last_good_report(
            env.library,
            trusted_keys_path=env.kwargs["trusted_keys_path"],
            audience_ids=MEMBER,
            restore=True,
            source=env.source,
            now=env.now,
        )
    assert exc_info.value.reason == "library_add_refused"
    assert exc_info.value.code == -32017


def test_last_good_url_source_refuses(harness, tmp_path: Path) -> None:
    env = make_env(harness, tmp_path)
    sync_managed_profile(env.library, env.source, apply=True, **env.kwargs)
    remove_bundle(env.library, env.shas["team-v2"])
    with pytest.raises(DistributionRefusal) as exc_info:
        last_good_report(
            env.library,
            trusted_keys_path=env.kwargs["trusted_keys_path"],
            audience_ids=MEMBER,
            restore=True,
            source="https://unlimited.example/registry",
            now=env.now,
        )
    assert exc_info.value.reason == "source_url_rejected"


# ---------------------------------------------------------------------------
# doctor: the documented problem classes.


def test_doctor_is_clean_after_a_good_sync(harness, tmp_path: Path) -> None:
    env = make_env(harness, tmp_path)
    fresh = managed_doctor_report(env.library, now=env.now)
    assert fresh["status"] == "ok" and fresh["exit_code"] == 0
    sync_managed_profile(env.library, env.source, apply=True, **env.kwargs)
    report = managed_doctor_report(
        env.library,
        trusted_keys_path=env.kwargs["trusted_keys_path"],
        audience_ids=MEMBER,
        source=env.source,
        now=env.now,
    )
    assert report["status"] == "ok" and report["exit_code"] == 0
    checks = {item["check"]: item["ok"] for item in report["checks"]}
    assert checks["state_file"] is True
    assert checks["staged_bundles"] is True
    assert checks["watermark_monotonicity"] is True


def test_doctor_flags_corrupt_state_replay_and_unverifiable_staged(
    harness, tmp_path: Path
) -> None:
    env = make_env(harness, tmp_path)
    sync_managed_profile(env.library, env.source, apply=True, **env.kwargs)
    # (a) Replay: the source rolls the channel back below the watermark.
    channel_path = env.registry.channels_dir / f"{ISSUER}.stable.channel.json"
    channel_path.write_text(json.dumps(env.revisions[1], sort_keys=True), encoding="utf-8")
    report = managed_doctor_report(
        env.library,
        trusted_keys_path=env.kwargs["trusted_keys_path"],
        audience_ids=MEMBER,
        source=env.source,
        now=env.now,
    )
    assert report["exit_code"] == 1
    assert any("routing_revision_regression" in problem for problem in report["problems"])
    # (b) A staged bundle that no longer verifies (revoked since the sync).
    channel_path.write_text(json.dumps(env.revisions[2], sort_keys=True), encoding="utf-8")
    revoke(env.store, bundle_sha256=env.shas["team-v2"], reason="drill", now=env.now)
    report = managed_doctor_report(
        env.library,
        trusted_keys_path=env.kwargs["trusted_keys_path"],
        audience_ids=MEMBER,
        now=env.now,
    )
    assert report["exit_code"] == 1
    assert any("no longer verifies" in problem for problem in report["problems"])
    # (c) Corrupt state file shape.
    sync_state_path(env.library).write_text("{not json", encoding="utf-8")
    report = managed_doctor_report(env.library, now=env.now)
    assert report["exit_code"] == 1
    assert any("not valid JSON" in problem for problem in report["problems"])
    # ...and the mutating sync path refuses on the same corrupt state.
    with pytest.raises(DistributionRefusal) as exc_info:
        sync_managed_profile(env.library, env.source, apply=True, **env.kwargs)
    assert exc_info.value.reason == "state_invalid"


def test_doctor_warns_on_drift_and_assignment_expiry(harness, tmp_path: Path) -> None:
    env = make_env(harness, tmp_path)
    sync_managed_profile(env.library, env.source, apply=True, **env.kwargs)
    # Stage and activate the OLD bundle: assignment expects v2, member runs v1.
    from unlimited_skills.mcp.bundle_library import add_bundle

    add_bundle(
        env.library,
        env.bundle_paths["team-v1"],
        trusted_keys_path=env.kwargs["trusted_keys_path"],
        audience_ids=MEMBER,
        now=env.now,
    )
    activate_bundle(
        env.library,
        env.shas["team-v1"],
        trusted_keys_path=env.kwargs["trusted_keys_path"],
        audience_ids=MEMBER,
        now=env.now,
    )
    soon = harness.build_assignment(
        [TEAM], "stable", ISSUER, "follow", env.issuer_key,
        revision=2,
        issued_at=harness._utc(env.now - 400),
        expires_at=harness._utc(env.now + 5 * DAY),  # inside the 14-day window
    )
    env.registry.put_assignment("expiring-soon", soon)
    report = managed_doctor_report(
        env.library,
        trusted_keys_path=env.kwargs["trusted_keys_path"],
        audience_ids=MEMBER,
        source=env.source,
        now=env.now,
    )
    assert report["exit_code"] == 0, report["problems"]
    assert any("you run another" in warning or "is active" in warning for warning in report["warnings"])
    assert any("expires within" in warning for warning in report["warnings"])


# ---------------------------------------------------------------------------
# State atomicity: writes go through the temp-file + os.replace pattern.


def test_state_writes_are_atomic(harness, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    env = make_env(harness, tmp_path)
    calls: list[Path] = []
    real = managed_sync._atomic_write_json

    def spy(path: Path, document: dict) -> None:
        calls.append(Path(path))
        real(path, document)

    monkeypatch.setattr(managed_sync, "_atomic_write_json", spy)
    sync_managed_profile(env.library, env.source, apply=True, **env.kwargs)
    assert sync_state_path(env.library) in calls
    # A failing atomic write leaves no partial state file behind.
    fail_env = make_env(harness, tmp_path / "fail")

    def boom(path: Path, document: dict) -> None:
        raise OSError("disk full (injected)")

    monkeypatch.setattr(managed_sync, "_atomic_write_json", boom)
    with pytest.raises(OSError):
        sync_managed_profile(fail_env.library, fail_env.source, apply=True, **fail_env.kwargs)
    assert not sync_state_path(fail_env.library).exists()


# ---------------------------------------------------------------------------
# CLI wiring, leak-grep, and containment.


def _run_cli(argv: list[str]) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))


def _cli_common(env) -> list[str]:
    return [
        "--root", str(env.root),
        "mcp", "profiles", "managed",
    ]


def test_cli_dry_run_apply_status_last_good_doctor(
    harness, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    env = make_env(harness, tmp_path)
    common = [
        "--library-dir", str(env.library.directory),
        "--trusted-keys", str(env.store.trusted_keys_path),
        "--audience-id", TEAM,
        "--audience-id", HOST,
    ]
    base = ["--root", str(env.root), "mcp", "profiles", "managed"]
    # Dry-run (default): reports, exits 0, mutates nothing.
    assert _run_cli(base + ["sync", "--source", str(env.source)] + common) == 0
    out = capsys.readouterr().out
    assert "DRY-RUN (no mutation)" in out
    assert "WOULD be staged" in out
    assert not sync_state_path(env.library).exists()
    # Apply: stages, never activates.
    assert _run_cli(base + ["sync", "--source", str(env.source), "--apply", "--json"] + common) == 0
    document = json.loads(capsys.readouterr().out)
    assert document["synced"] is True
    assert forbidden_field_names(document) == set()
    state, _ = read_state(env.library)
    assert state["active_sha256"] == ""
    # status / last-good / doctor.
    assert _run_cli(base + ["status"] + common) == 0
    status_out = capsys.readouterr().out
    assert "watermark" in status_out and "NOT activated" in status_out
    assert _run_cli(base + ["last-good"] + common) == 0
    last_good_out = capsys.readouterr().out
    assert "last-good bundle" in last_good_out
    assert _run_cli(base + ["doctor", "--source", str(env.source)] + common) == 0
    doctor_out = capsys.readouterr().out
    assert "managed sync doctor: ok" in doctor_out
    # Leak-grep over every text output: no secrets, no local paths.
    for line in (out + status_out + last_good_out + doctor_out).splitlines():
        assert not looks_secret(line), f"secret-looking CLI line: {line[:48]}..."
        assert not PATH_PATTERN.search(line), f"local path in CLI line: {line[:48]}..."


def test_cli_url_source_refuses_with_the_gated_message(
    harness, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    env = make_env(harness, tmp_path)
    rc = _run_cli(
        ["--root", str(env.root), "mcp", "profiles", "managed", "sync",
         "--source", "https://unlimited.example/registry",
         "--library-dir", str(env.library.directory),
         "--trusted-keys", str(env.store.trusted_keys_path),
         "--audience-id", TEAM]
    )
    assert rc == 1
    err = capsys.readouterr().err
    assert "source_url_rejected" in err
    assert "hosted sync is not implemented" in err
    assert "design gated" in err


def test_containment_nothing_outside_the_member_state_is_written(
    harness, tmp_path: Path
) -> None:
    env = make_env(harness, tmp_path)
    repo_store = ROOT / ".unlimited-skills-trust"
    repo_library = ROOT / ".unlimited-skills-bundles"
    repo_audit = ROOT / ".learning" / "mcp-audit.jsonl"
    repo_before = {path: path.exists() for path in (repo_store, repo_library, repo_audit)}
    source_before = _tree_snapshot(env.source)
    store_before = _tree_snapshot(env.store.trusted_keys_path.parent)
    sync_managed_profile(env.library, env.source, apply=True, **env.kwargs)
    # The source and the trust store are read-only to sync; only the
    # member's library directory (entries + sync state) gains files.
    assert _tree_snapshot(env.source) == source_before
    assert _tree_snapshot(env.store.trusted_keys_path.parent) == store_before
    assert sync_state_path(env.library).is_file()
    for path, existed in repo_before.items():
        assert path.exists() == existed, f"{path.name} was touched by managed sync"


# ---------------------------------------------------------------------------
# Boundary: no network-capable imports in the module (the stabilization
# audit's security_boundaries dimension, asserted here as well).


def test_managed_sync_module_imports_no_network_library() -> None:
    forbidden = {
        "socket", "ssl", "http", "urllib", "urllib3", "requests", "httpx",
        "aiohttp", "websockets", "ftplib", "smtplib", "telnetlib", "xmlrpc",
        "webbrowser",
    }
    source = (ROOT / "unlimited_skills" / "mcp" / "managed_sync.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            roots.add(node.module.split(".")[0])
    assert roots & forbidden == set()


def test_shared_pieces_are_the_harness_pieces(harness) -> None:
    """The E26 harness imports the SAME client functions this module ships:
    one implementation, the abuse battery as its regression suite."""
    assert harness.verify_routing_document is managed_sync.verify_routing_document
    assert harness.resolve_assignments is managed_sync.resolve_assignments
    assert harness.load_summary_document is managed_sync.load_summary_document
    assert harness.forbidden_field_names is managed_sync.forbidden_field_names
    assert harness.FORBIDDEN_FIELDS is managed_sync.FORBIDDEN_FIELDS
    assert harness.DistributionRefusal is managed_sync.DistributionRefusal
