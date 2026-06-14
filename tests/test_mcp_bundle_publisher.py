"""E19: local MCP profile bundle publisher and signing ceremony.

Proves the contract of docs/mcp-bundle-publishing.md against
``unlimited_skills/mcp/bundle_publisher.py`` and the ``mcp bundle`` CLI:

- the full happy-path ceremony: keygen -> trust import of the PUBLIC key ->
  publish (validate, sign over the canonical JSON, package, automatic E14
  self-check) -> verify ok -> the bundle loads through the REAL gateway
  profile path (``_resolve_gateway_profile_state``) under
  ``--require-signed-profiles``;
- ``--dry-run`` performs every step but writes NOTHING to the out dir;
- every documented refusal: invalid profile (E09/E10 errors surfaced),
  missing/unreadable signing key, PUBLIC-only key files, expired/inverted
  validity windows, empty/malformed audience, namespace rule grammar
  violations and uncovered profile rules, out-dir collisions without
  ``--force``, issuer key-id mismatch, missing ``cryptography``;
- PRIVATE-KEY HYGIENE (the crux): the private key bytes (base64 and hex)
  and PEM/OpenSSH private markers appear in NO ceremony output -- not the
  bundle, manifest, validation report, rollback metadata, public key file,
  trust store files, or captured stdout/stderr; the keygen out dir is the
  ONLY place the private key exists, and the trust store refuses to import
  the private file (``looks_secret``-family heuristics reused);
- atomicity: a simulated ceremony failure (self-check refusal or a sidecar
  write failure) leaves NO signed bundle and no temp leftovers behind;
- manifest / validation-report / rollback metadata correctness, and a
  drill-style round trip: the exact ``mcp trust revoke --bundle-sha256``
  command from the rollback metadata actually revokes the bundle through
  the real E15 store and the real E14 verification refuses it (-32017).
"""

from __future__ import annotations

import base64
import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

pytest.importorskip("cryptography")

from unlimited_skills.cli import main
from unlimited_skills.commands.mcp import _resolve_gateway_profile_state
from unlimited_skills.mcp import bundle_publisher
from unlimited_skills.mcp.audit import looks_secret
from unlimited_skills.mcp.bundle_publisher import (
    DEV_KEY_WARNING,
    PublisherError,
    generate_keypair,
    load_signing_key,
    publish_bundle,
    verify_report,
)
from unlimited_skills.mcp.bundles import (
    BUNDLE_KEY_MISSING,
    BUNDLE_REVOKED,
    BUNDLE_SIGNATURE_INVALID,
    BundleFailClosed,
)
from unlimited_skills.mcp.profiles import ActiveProfile
from unlimited_skills.mcp.trust_store import (
    TrustStore,
    TrustStoreError,
    import_key,
    load_key_file,
    revoke,
)

PROFILE_DOC = {
    "schema_version": 1,
    "default_profile": "dev",
    "profiles": {
        "dev": {"visible": ["fake.*"], "callable": ["fake.*"]},
        "reviewer": {"extends": "dev", "visible": ["fake.echo"], "callable": ["fake.echo"]},
    },
}

KEY_ID = "e19-dev-key-2026"
AUDIENCE = "team:e19"
EMPTY_CRL = {"schema_version": 1, "revoked_bundles": [], "revoked_key_ids": []}


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("UNLIMITED_SKILLS_MCP_PROFILE", raising=False)
    monkeypatch.delenv("UNLIMITED_SKILLS_MCP_AUDIENCE", raising=False)


def write_profiles(directory: Path, document: dict | None = None, name: str = "team-profiles.json") -> Path:
    path = directory / name
    path.write_text(json.dumps(document or PROFILE_DOC), encoding="utf-8")
    return path


def keygen(directory: Path, **kwargs) -> dict:
    return generate_keypair(directory / "keys", key_id=KEY_ID, display="E19 dev issuer", **kwargs)


def publish(tmp_path: Path, **overrides) -> dict:
    """keygen + publish with sensible defaults; returns the publish result
    plus the keygen result under ``_keygen``."""
    generated = overrides.pop("_generated", None) or keygen(tmp_path, force=True)
    kwargs = {
        "profiles_path": overrides.pop("profiles_path", None) or write_profiles(tmp_path),
        "signing_key_path": overrides.pop(
            "signing_key_path", Path(generated["private_key_path"])
        ),
        "issuer_key_id": KEY_ID,
        "audience": [AUDIENCE],
        "expires_days": 30,
        "out_dir": tmp_path / "dist",
        "name": "team",
    }
    kwargs.update(overrides)
    result = publish_bundle(**kwargs)
    result["_keygen"] = generated
    return result


def read_private_seed(generated: dict) -> tuple[str, str]:
    """(seed base64, seed hex) parsed from the private key file."""
    raw = Path(generated["private_key_path"]).read_text(encoding="utf-8")
    body = "\n".join(line for line in raw.splitlines() if not line.lstrip().startswith("#"))
    document = json.loads(body)
    seed_b64 = document["private_key"]
    return seed_b64, base64.b64decode(seed_b64).hex()


# ---------------------------------------------------------------------------
# keygen


def test_keygen_writes_dev_keypair_with_loud_warning(tmp_path: Path) -> None:
    result = keygen(tmp_path)
    private_path = Path(result["private_key_path"])
    public_path = Path(result["public_key_path"])
    assert private_path.is_file() and public_path.is_file()
    assert private_path.parent == tmp_path / "keys" and public_path.parent == tmp_path / "keys"
    # Loud DEV header on the very first line of the private file.
    first_line = private_path.read_text(encoding="utf-8").splitlines()[0]
    assert DEV_KEY_WARNING in first_line
    assert "PRIVATE" in private_path.read_text(encoding="utf-8")
    # The public file is the trust-store import format (32-byte Ed25519).
    public_doc = json.loads(public_path.read_text(encoding="utf-8"))
    assert public_doc["key_id"] == KEY_ID and public_doc["algorithm"] == "ed25519"
    assert len(base64.b64decode(public_doc["public_key"])) == 32
    # The result carries paths and the fingerprint only -- never key bytes.
    dumped = json.dumps(result)
    seed_b64, seed_hex = read_private_seed(result)
    assert seed_b64 not in dumped and seed_hex not in dumped
    assert public_doc["public_key"] not in dumped
    assert result["warning"] == DEV_KEY_WARNING and result["dev_only"] is True
    assert len(result["fingerprint"]) == 16
    if os.name == "posix":  # restrictive perms are best-effort on Windows
        assert private_path.stat().st_mode & 0o077 == 0


def test_keygen_refuses_collision_without_force(tmp_path: Path) -> None:
    first = keygen(tmp_path)
    first_seed = read_private_seed(first)
    with pytest.raises(PublisherError, match="--force"):
        keygen(tmp_path)
    # Nothing was overwritten by the refusal.
    assert read_private_seed(first) == first_seed
    second = keygen(tmp_path, force=True)
    assert read_private_seed(second) != first_seed


def test_keygen_public_file_round_trips_into_trust_store(tmp_path: Path) -> None:
    result = keygen(tmp_path)
    store = TrustStore(tmp_path / "trust-store")
    document = load_key_file(Path(result["public_key_path"]))
    imported = import_key(
        store,
        key_id=str(document["key_id"]),
        public_key_b64=str(document["public_key"]),
        display=str(document.get("display", "")),
    )
    assert imported["imported"] is True
    assert imported["fingerprint"] == result["fingerprint"]


def test_trust_store_refuses_the_private_key_file(tmp_path: Path) -> None:
    """Defense in depth: importing the PRIVATE file refuses before any write
    (the E15 private-material heuristics fire on the keygen format)."""
    result = keygen(tmp_path)
    with pytest.raises(TrustStoreError, match="PRIVATE"):
        load_key_file(Path(result["private_key_path"]))


def test_keygen_refuses_without_cryptography(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(bundle_publisher, "cryptography_available", lambda: False)
    with pytest.raises(PublisherError, match="cryptography"):
        keygen(tmp_path)
    assert not (tmp_path / "keys").exists(), "refusal happens before any write"


# ---------------------------------------------------------------------------
# publish: happy path, manifest/rollback correctness, dry run


def test_full_ceremony_happy_path(tmp_path: Path) -> None:
    result = publish(tmp_path)
    out = tmp_path / "dist"
    assert result["published"] is True and result["dry_run"] is False
    for name in ("team.bundle.json", "team.MANIFEST.json", "team.VALIDATION-REPORT.json", "team.ROLLBACK.json"):
        assert (out / name).is_file(), name
    bundle_path = out / "team.bundle.json"
    import hashlib

    assert hashlib.sha256(bundle_path.read_bytes()).hexdigest() == result["bundle_sha256"]
    document = json.loads(bundle_path.read_text(encoding="utf-8"))
    assert document["bundle_version"] == 1
    assert document["issuer"]["key_id"] == KEY_ID
    assert document["audience"] == [AUDIENCE]
    assert document["allowed_upstream_namespaces"] == ["fake.*"]  # derived
    assert document["default_profile"] == "dev"
    assert document["signature"]["algorithm"] == "ed25519"
    # The automatic post-package self-check already ran (in the checks list).
    assert any(item["check"] == "post_package_verification" for item in result["checks"])

    # verify step: the REAL E14 verification through the trust store's file.
    store = TrustStore(tmp_path / "trust-store")
    public_doc = load_key_file(Path(result["_keygen"]["public_key_path"]))
    import_key(store, key_id=KEY_ID, public_key_b64=str(public_doc["public_key"]))
    report = verify_report(bundle_path, store.trusted_keys_path, audience_ids=[AUDIENCE])
    assert report["ok"] is True and report["code"] == 0
    assert report["profile"] == "dev" and report["issuer_key_id"] == KEY_ID
    assert report["bundle_sha256"] == result["bundle_sha256"]

    # Handoff: the bundle loads through the REAL gateway profile path, even
    # under the signed-required policy.
    state, note = _resolve_gateway_profile_state(
        SimpleNamespace(
            profiles="",
            profile="",
            profile_bundle=str(bundle_path),
            trusted_keys=str(store.trusted_keys_path),
            audience_id=[AUDIENCE],
            require_signed_profiles=True,
            root="",
        )
    )
    assert isinstance(state, ActiveProfile) and state.name == "dev"
    assert state.is_callable("fake", "echo") and not state.is_visible("other", "tool")
    assert "signed bundle profile 'dev' enforced" in note


def test_manifest_validation_report_and_rollback_contents(tmp_path: Path) -> None:
    import hashlib

    profiles_path = write_profiles(tmp_path)
    result = publish(tmp_path, profiles_path=profiles_path)
    out = tmp_path / "dist"
    manifest = json.loads((out / "team.MANIFEST.json").read_text(encoding="utf-8"))
    assert manifest["bundle_sha256"] == result["bundle_sha256"]
    assert manifest["bundle_file"] == "team.bundle.json"
    assert manifest["issuer_key_id"] == KEY_ID
    assert manifest["source_profile_sha256"] == hashlib.sha256(profiles_path.read_bytes()).hexdigest()
    assert manifest["profile_count"] == 2
    assert manifest["profiles"]["dev"] == {"visible_rules": 1, "callable_rules": 1}
    assert manifest["visible_rule_count"] == 2 and manifest["callable_rule_count"] == 2
    assert manifest["publisher_version"] == 1
    assert manifest["dev_key_warning"] == DEV_KEY_WARNING
    assert manifest["created_at"].endswith("Z") and manifest["expires_at"].endswith("Z")

    report = json.loads((out / "team.VALIDATION-REPORT.json").read_text(encoding="utf-8"))
    check_names = {item["check"] for item in report["checks"]}
    assert {
        "profile_static_checks",
        "signing_key",
        "audience",
        "validity_window",
        "namespace_ceiling",
        "signature",
        "post_package_verification",
    } <= check_names
    assert all(item["ok"] is True for item in report["checks"])
    assert report["verification"]["via"] == "resolve_bundle_state (E14)"
    assert report["bundle_sha256"] == result["bundle_sha256"]

    rollback = json.loads((out / "team.ROLLBACK.json").read_text(encoding="utf-8"))
    assert rollback["bundle_sha256"] == result["bundle_sha256"]
    assert rollback["previous_bundle_sha256"] == ""
    assert (
        rollback["revoke_command"]
        == f"unlimited-skills mcp trust revoke --bundle-sha256 {result['bundle_sha256']}"
    )
    assert rollback["rollback_steps"]


def test_previous_bundle_sha_recorded_in_rollback(tmp_path: Path) -> None:
    import hashlib

    first = publish(tmp_path)
    bundle_v1 = tmp_path / "dist" / "team.bundle.json"
    v1_sha = hashlib.sha256(bundle_v1.read_bytes()).hexdigest()
    second = publish(
        tmp_path,
        _generated=first["_keygen"],
        name="team-v2",
        previous=str(bundle_v1),
    )
    rollback = json.loads(
        (tmp_path / "dist" / "team-v2.ROLLBACK.json").read_text(encoding="utf-8")
    )
    assert rollback["previous_bundle_sha256"] == v1_sha
    assert second["previous_bundle_sha256"] == v1_sha
    # A literal 64-hex SHA-256 is accepted too.
    third = publish(tmp_path, _generated=first["_keygen"], name="team-v3", previous="ab" * 32)
    assert third["previous_bundle_sha256"] == "ab" * 32


def test_dry_run_writes_nothing(tmp_path: Path) -> None:
    out = tmp_path / "dist"
    result = publish(tmp_path, dry_run=True)
    assert result["dry_run"] is True and result["published"] is False
    assert result["verification"]["ok"] is True  # the self-check still ran
    assert result["bundle_sha256"]
    assert not out.exists(), "dry run must not create or write the out dir"
    assert "would" in json.dumps(result["note"]).lower() or "NO signed" in result["note"]


# ---------------------------------------------------------------------------
# Refusals: loud PublisherError, exit 1 at the CLI, nothing signed written.


def assert_no_bundle(out: Path) -> None:
    if out.exists():
        leftovers = [path.name for path in out.iterdir()]
        assert not leftovers, f"ceremony refusal left artifacts behind: {leftovers}"


def test_refuses_invalid_profile_json(tmp_path: Path) -> None:
    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    with pytest.raises(PublisherError, match="raw profile is invalid"):
        publish(tmp_path, profiles_path=bad)
    assert_no_bundle(tmp_path / "dist")


def test_refuses_profile_failing_e09_semantic_checks(tmp_path: Path) -> None:
    document = {
        "schema_version": 1,
        "profiles": {"dev": {"visible": ["fake.echo"], "callable": ["fake.*"]}},
    }
    with pytest.raises(PublisherError, match="not covered by visible"):
        publish(tmp_path, profiles_path=write_profiles(tmp_path, document, "bad.json"))
    assert_no_bundle(tmp_path / "dist")


def test_refuses_missing_signing_key(tmp_path: Path) -> None:
    with pytest.raises(PublisherError, match="missing or unreadable"):
        publish(tmp_path, signing_key_path=tmp_path / "nope.signing-key.json")
    assert_no_bundle(tmp_path / "dist")


def test_refuses_public_only_key_files(tmp_path: Path) -> None:
    generated = keygen(tmp_path)
    # The keygen PUBLIC file is refused with a pointed message.
    with pytest.raises(PublisherError, match="PUBLIC"):
        publish(
            tmp_path,
            _generated=generated,
            signing_key_path=Path(generated["public_key_path"]),
        )
    # A trusted-keys file (E14 format) is equally PUBLIC-only.
    trusted = tmp_path / "trusted-keys.json"
    trusted.write_text(
        json.dumps({"schema_version": 1, "keys": [{"key_id": "k", "algorithm": "ed25519", "public_key": "QUFB"}]}),
        encoding="utf-8",
    )
    with pytest.raises(PublisherError, match="PUBLIC"):
        publish(tmp_path, _generated=generated, signing_key_path=trusted)
    assert_no_bundle(tmp_path / "dist")


def test_refuses_issuer_key_id_mismatch(tmp_path: Path) -> None:
    with pytest.raises(PublisherError, match="does not match"):
        publish(tmp_path, issuer_key_id="somebody-else")
    assert_no_bundle(tmp_path / "dist")


@pytest.mark.parametrize("days", [0, -7])
def test_refuses_past_or_inverted_validity_window(tmp_path: Path, days: int) -> None:
    with pytest.raises(PublisherError, match=">= 1"):
        publish(tmp_path, expires_days=days)
    assert_no_bundle(tmp_path / "dist")


def test_refuses_empty_audience(tmp_path: Path) -> None:
    with pytest.raises(PublisherError, match="non-empty"):
        publish(tmp_path, audience=[])
    with pytest.raises(PublisherError, match="non-empty"):
        publish(tmp_path, audience=["   "])
    assert_no_bundle(tmp_path / "dist")


def test_refuses_malformed_audience(tmp_path: Path) -> None:
    with pytest.raises(PublisherError, match="'team:'/'org:'/'host:'"):
        publish(tmp_path, audience=["everyone"])
    assert_no_bundle(tmp_path / "dist")


def test_refuses_namespace_rule_grammar_violations(tmp_path: Path) -> None:
    with pytest.raises(PublisherError, match="rule grammar"):
        publish(tmp_path, namespaces=["fake..*"])
    with pytest.raises(PublisherError, match="rule grammar"):
        publish(tmp_path, namespaces=["*.echo"])
    assert_no_bundle(tmp_path / "dist")


def test_refuses_profile_rules_outside_the_ceiling(tmp_path: Path) -> None:
    with pytest.raises(PublisherError, match="outside the allowed_upstream_namespaces"):
        publish(tmp_path, namespaces=["other.*"])
    assert_no_bundle(tmp_path / "dist")


def test_refuses_out_dir_collision_without_force(tmp_path: Path) -> None:
    first = publish(tmp_path)
    with pytest.raises(PublisherError, match="--force"):
        publish(tmp_path, _generated=first["_keygen"])
    # The original package survives a refused re-publish untouched.
    assert (tmp_path / "dist" / "team.bundle.json").is_file()
    forced = publish(tmp_path, _generated=first["_keygen"], force=True)
    assert forced["published"] is True


def test_publish_refuses_without_cryptography(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    generated = keygen(tmp_path)
    profiles_path = write_profiles(tmp_path)
    monkeypatch.setattr(bundle_publisher, "cryptography_available", lambda: False)
    with pytest.raises(PublisherError, match="cryptography"):
        publish(tmp_path, _generated=generated, profiles_path=profiles_path)
    assert_no_bundle(tmp_path / "dist")


# ---------------------------------------------------------------------------
# Atomicity: ceremony failures never leave a signed bundle behind.


def test_self_check_failure_leaves_nothing_signed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def refuse(*args, **kwargs):
        return BundleFailClosed(
            code=BUNDLE_SIGNATURE_INVALID,
            message="simulated self-check refusal",
            requested="dev",
        )

    monkeypatch.setattr(bundle_publisher, "resolve_bundle_state", refuse)
    with pytest.raises(PublisherError, match="self-check FAILED"):
        publish(tmp_path)
    out = tmp_path / "dist"
    leftovers = [path.name for path in out.iterdir()] if out.exists() else []
    assert leftovers == [], f"self-check failure left files: {leftovers}"


def test_sidecar_write_failure_removes_the_temp_bundle(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def explode(path, document):
        raise OSError("simulated disk failure")

    monkeypatch.setattr(bundle_publisher, "_atomic_write_json", explode)
    with pytest.raises(OSError, match="simulated disk failure"):
        publish(tmp_path)
    out = tmp_path / "dist"
    leftovers = [path.name for path in out.iterdir()] if out.exists() else []
    assert leftovers == [], f"sidecar write failure left files: {leftovers}"


# ---------------------------------------------------------------------------
# Private-key hygiene: the crux. The private key exists ONLY in the keygen
# out dir; its bytes appear in NO other ceremony output, and PEM/OpenSSH
# private markers appear nowhere (the trust-store heuristics reused).


def _assert_clean(text: str, secrets: tuple[str, ...], where: str) -> None:
    upper = text.upper()
    for marker in ("PRIVATE KEY", "BEGIN OPENSSH PRIVATE", "-----BEGIN"):
        assert marker not in upper, f"{where}: private marker {marker!r} leaked"
    for secret in secrets:
        assert secret not in text, f"{where}: private key material leaked"


def test_private_key_never_leaks_from_any_ceremony_output(
    tmp_path: Path, capsys: pytest.CaptureFixture
) -> None:
    root = tmp_path / "library"
    root.mkdir()
    keys_dir = tmp_path / "keys"
    out_dir = tmp_path / "dist"
    profiles_path = write_profiles(tmp_path)
    store = TrustStore(tmp_path / "trust-store")

    def cli(*argv: str) -> int:
        return main(["--root", str(root), "mcp", "bundle", *argv])

    transcripts: list[str] = []

    assert cli("keygen", "--out", str(keys_dir), "--key-id", KEY_ID, "--json") == 0
    captured = capsys.readouterr()
    keygen_json = json.loads(captured.out)
    transcripts.append(captured.out + captured.err)
    seed_b64, seed_hex = read_private_seed(keygen_json)
    secrets = (seed_b64, seed_b64.rstrip("="), seed_hex)

    public_doc = load_key_file(Path(keygen_json["public_key_path"]))
    import_key(store, key_id=KEY_ID, public_key_b64=str(public_doc["public_key"]))

    assert (
        cli(
            "publish",
            "--profiles",
            str(profiles_path),
            "--signing-key",
            keygen_json["private_key_path"],
            "--issuer-key-id",
            KEY_ID,
            "--audience",
            AUDIENCE,
            "--out",
            str(out_dir),
            "--name",
            "team",
            "--json",
        )
        == 0
    )
    captured = capsys.readouterr()
    transcripts.append(captured.out + captured.err)

    assert (
        cli(
            "verify",
            "--bundle",
            str(out_dir / "team.bundle.json"),
            "--trusted-keys",
            str(store.trusted_keys_path),
            "--audience-id",
            AUDIENCE,
            "--json",
        )
        == 0
    )
    captured = capsys.readouterr()
    transcripts.append(captured.out + captured.err)

    # Every ceremony output EXCEPT the private key file itself.
    private_path = Path(keygen_json["private_key_path"]).resolve()
    artifacts = [
        path
        for directory in (out_dir, keys_dir, store.directory)
        for path in sorted(directory.rglob("*"))
        if path.is_file() and path.resolve() != private_path
    ]
    assert len(artifacts) >= 7, "expected bundle package + public key + store files"
    for path in artifacts:
        _assert_clean(path.read_text(encoding="utf-8"), secrets, path.name)
    for index, transcript in enumerate(transcripts):
        _assert_clean(transcript, secrets, f"stdout/stderr #{index}")
    # The private key exists in exactly one place: the keygen out dir.
    hits = [path for path in tmp_path.rglob("*") if path.is_file() and seed_b64 in path.read_text(encoding="utf-8", errors="replace")]
    assert hits == [private_path], f"private key found outside the keygen out dir: {hits}"
    # Keygen output values are paths/fingerprints only -- nothing secret-shaped.
    for key, value in keygen_json.items():
        if isinstance(value, str) and "path" not in key and "command" not in key:
            assert not looks_secret(value), f"keygen output field {key!r} looks secret"


# ---------------------------------------------------------------------------
# Round trip with the managed trust store: the rollback metadata's exact
# revoke command actually revokes the bundle (drill-style).


def test_rollback_revoke_command_actually_revokes(tmp_path: Path) -> None:
    store = TrustStore(tmp_path / "trust-store")
    generated = keygen(tmp_path)
    public_doc = load_key_file(Path(generated["public_key_path"]))
    import_key(store, key_id=KEY_ID, public_key_b64=str(public_doc["public_key"]))
    store.crl_path.parent.mkdir(parents=True, exist_ok=True)
    store.crl_path.write_text(json.dumps(EMPTY_CRL), encoding="utf-8")

    result = publish(tmp_path, _generated=generated, crl_path=str(store.crl_path))
    bundle_path = tmp_path / "dist" / "team.bundle.json"
    report = verify_report(bundle_path, store.trusted_keys_path, audience_ids=[AUDIENCE])
    assert report["ok"] is True

    rollback = json.loads((tmp_path / "dist" / "team.ROLLBACK.json").read_text(encoding="utf-8"))
    command = rollback["revoke_command"].split()
    assert command[:5] == ["unlimited-skills", "mcp", "trust", "revoke", "--bundle-sha256"]
    revoked_sha = command[5]
    assert revoked_sha == result["bundle_sha256"]
    outcome = revoke(store, bundle_sha256=revoked_sha, reason="e19 rollback test")
    assert outcome["revoked"] is True

    refusal = verify_report(bundle_path, store.trusted_keys_path, audience_ids=[AUDIENCE])
    assert refusal["ok"] is False and refusal["code"] == BUNDLE_REVOKED
    assert refusal["refusal"] == "bundle_revoked"


# ---------------------------------------------------------------------------
# CLI exit codes and the verify wrapper.


def test_cli_verify_exit_codes_ok_and_tampered(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    root = tmp_path / "library"
    root.mkdir()
    store = TrustStore(tmp_path / "trust-store")
    result = publish(tmp_path)
    public_doc = load_key_file(Path(result["_keygen"]["public_key_path"]))
    import_key(store, key_id=KEY_ID, public_key_b64=str(public_doc["public_key"]))
    bundle_path = tmp_path / "dist" / "team.bundle.json"

    argv = [
        "--root",
        str(root),
        "mcp",
        "bundle",
        "verify",
        "--bundle",
        str(bundle_path),
        "--trusted-keys",
        str(store.trusted_keys_path),
        "--audience-id",
        AUDIENCE,
        "--json",
    ]
    assert main(argv) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["ok"] is True and report["profile"] == "dev"

    # Post-signing tampering refuses through the same real path, exit 1.
    document = json.loads(bundle_path.read_text(encoding="utf-8"))
    document["audience"].append("org:everyone")
    bundle_path.write_text(json.dumps(document), encoding="utf-8")
    assert main(argv) == 1
    report = json.loads(capsys.readouterr().out)
    assert report["code"] == BUNDLE_SIGNATURE_INVALID
    assert report["refusal"] == "bundle_signature_invalid"


def test_cli_publish_dry_run_and_refusal_exit_codes(
    tmp_path: Path, capsys: pytest.CaptureFixture
) -> None:
    root = tmp_path / "library"
    root.mkdir()
    generated = keygen(tmp_path)
    profiles_path = write_profiles(tmp_path)
    out_dir = tmp_path / "dist"
    base = [
        "--root",
        str(root),
        "mcp",
        "bundle",
        "publish",
        "--profiles",
        str(profiles_path),
        "--signing-key",
        generated["private_key_path"],
        "--audience",
        AUDIENCE,
        "--out",
        str(out_dir),
    ]
    assert main([*base, "--dry-run", "--json"]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["dry_run"] is True
    assert not out_dir.exists(), "CLI dry run wrote into the out dir"

    # Refusal: empty audience -> loud stderr, exit 1, nothing written.
    refused = [item for item in base if item != AUDIENCE and item != "--audience"]
    assert main(refused) == 1
    captured = capsys.readouterr()
    assert "bundle publish refused" in captured.err and "non-empty" in captured.err
    assert not out_dir.exists()


def test_verify_report_missing_trusted_keys_is_key_missing(tmp_path: Path) -> None:
    result = publish(tmp_path)
    bundle_path = tmp_path / "dist" / "team.bundle.json"
    report = verify_report(bundle_path, tmp_path / "absent-keys.json", audience_ids=[AUDIENCE])
    assert report["ok"] is False and report["code"] == BUNDLE_KEY_MISSING
    assert report["bundle_sha256"] == result["bundle_sha256"]


def test_load_signing_key_recomputes_and_checks_public_half(tmp_path: Path) -> None:
    generated = keygen(tmp_path)
    key = load_signing_key(Path(generated["private_key_path"]))
    assert key.key_id == KEY_ID and key.fingerprint == generated["fingerprint"]
    # A hand-edited public half (seed/public mismatch) is refused.
    private_path = Path(generated["private_key_path"])
    raw = private_path.read_text(encoding="utf-8")
    body = "\n".join(line for line in raw.splitlines() if not line.lstrip().startswith("#"))
    document = json.loads(body)
    document["public_key"] = base64.b64encode(b"\x01" * 32).decode("ascii")
    private_path.write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises(PublisherError, match="does not match the private seed"):
        load_signing_key(private_path)
