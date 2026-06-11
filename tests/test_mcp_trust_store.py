"""E15: managed MCP profile trust store.

Proves the contract of docs/mcp-trust-store.md against
``unlimited_skills.mcp.trust_store`` and the ``unlimited-skills mcp trust``
CLI:

- the store backend IS the E14 trusted-keys + CRL formats (one source of
  truth): everything ``import``/``revoke`` write is accepted by the strict
  E14 loaders the gateway uses, byte-semantics unchanged;
- status/list/import/revoke/doctor happy paths and JSON shapes;
- import refuses PRIVATE key material (PEM markers, private JSON fields,
  48/64-byte seed-length heuristics) loudly and writes NOTHING;
- import refuses a duplicate key_id with different material (no silent key
  replacement) and is idempotent for identical material;
- revoke is idempotent and append-only (history never deleted);
- doctor catches each problem class (duplicate key_id,
  expired-but-not-rotated, unreadable CRL, malformed store, unexplained
  revocation) with exit code 1, and stays exit 0 for warnings;
- atomic writes: a simulated replace failure leaves no partial store file;
- gateway integration: --profile-bundle without --trusted-keys verifies via
  the managed store when it exists and is byte-for-byte unchanged
  (-32019) when it does not; an explicit --trusted-keys always wins;
- output never contains full key bytes (only abbreviated fingerprints);
- CLI wiring through the cli facade (main(...) dispatch, --json shapes,
  exit codes).
"""

from __future__ import annotations

import base64
import json
import os
from argparse import Namespace
from pathlib import Path

import pytest

from unlimited_skills.cli import main
from unlimited_skills.commands.mcp import _resolve_gateway_profile_state
from unlimited_skills.mcp.bundles import (
    BUNDLE_KEY_MISSING,
    BUNDLE_REVOKED,
    BundleFailClosed,
    canonical_bundle_bytes,
    load_trusted_keys,
    _load_crl,
    _parse_timestamp,
)
from unlimited_skills.mcp.profiles import ActiveProfile
from unlimited_skills.mcp import trust_store as ts
from unlimited_skills.mcp.trust_store import (
    TrustStore,
    TrustStoreError,
    default_store_dir,
    doctor_report,
    import_key,
    key_fingerprint,
    list_keys_report,
    load_key_file,
    managed_trusted_keys_path,
    revoke,
    status_report,
)

try:  # optional real-Ed25519 dependency, same stance as the E14 tests
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

    HAVE_CRYPTOGRAPHY = True
except ImportError:  # pragma: no cover
    HAVE_CRYPTOGRAPHY = False

requires_ed25519 = pytest.mark.skipif(
    not HAVE_CRYPTOGRAPHY, reason="optional 'cryptography' package not installed"
)

NOW = _parse_timestamp("2026-07-01T00:00:00Z")
PUBLIC_A = bytes(range(32))
PUBLIC_B = bytes(range(32, 64))
B64_A = base64.b64encode(PUBLIC_A).decode("ascii")
B64_B = base64.b64encode(PUBLIC_B).decode("ascii")


def store_at(tmp_path: Path) -> TrustStore:
    return TrustStore(tmp_path / "trust")


def import_a(store: TrustStore, **overrides) -> dict:
    options = {
        "key_id": "team-profiles-2026",
        "public_key_b64": B64_A,
        "display": "Platform team",
        "scopes": ["profile-bundles"],
        "not_after": "2027-01-01T00:00:00Z",
        "now": NOW,
    }
    options.update(overrides)
    return import_key(store, **options)


# ---------------------------------------------------------------------------
# Store backend = the E14 formats (one source of truth).


def test_import_writes_the_exact_e14_trusted_keys_format(tmp_path: Path) -> None:
    store = store_at(tmp_path)
    result = import_a(store, not_before="2026-01-01T00:00:00Z", comment="current key")
    assert result["imported"] is True
    assert result["fingerprint"] == key_fingerprint(PUBLIC_A)
    # The strict E14 loader (what the gateway runs) accepts the file as-is.
    trusted = load_trusted_keys(store.trusted_keys_path)
    assert trusted["team-profiles-2026"].public_key == PUBLIC_A
    assert trusted["team-profiles-2026"].not_after == _parse_timestamp("2027-01-01T00:00:00Z")
    document = json.loads(store.trusted_keys_path.read_text(encoding="utf-8"))
    assert document["schema_version"] == 1
    assert set(document["keys"][0]) <= {"key_id", "algorithm", "public_key", "not_after", "comment"}
    # Sidecar metadata never leaks into the verification file.
    metadata = json.loads(store.metadata_path.read_text(encoding="utf-8"))
    assert metadata["keys"]["team-profiles-2026"]["not_before"] == "2026-01-01T00:00:00Z"
    assert metadata["keys"]["team-profiles-2026"]["scopes"] == ["profile-bundles"]
    assert "not_before" not in document["keys"][0]


def test_revoke_writes_the_exact_e14_crl_format(tmp_path: Path) -> None:
    store = store_at(tmp_path)
    import_a(store)
    sha = "ab" * 32
    assert revoke(store, key_id="team-profiles-2026", reason="compromised", now=NOW)["revoked"]
    assert revoke(store, bundle_sha256=sha, now=NOW)["revoked"]
    hashes, key_ids = _load_crl(store.crl_path)  # the strict E14 CRL loader
    assert sha in hashes and "team-profiles-2026" in key_ids
    crl = json.loads(store.crl_path.read_text(encoding="utf-8"))
    assert set(crl) <= {"schema_version", "comment", "revoked_bundles", "revoked_key_ids"}
    metadata = json.loads(store.metadata_path.read_text(encoding="utf-8"))
    reasons = [record.get("reason") for record in metadata["revocations"]]
    assert "compromised" in reasons, "the reason lives in the sidecar, not the CRL"


# ---------------------------------------------------------------------------
# status / list.


def test_status_counts_key_states(tmp_path: Path) -> None:
    store = store_at(tmp_path)
    import_a(store)  # active (expires 2027)
    import_a(store, key_id="expiring-key", public_key_b64=B64_B, not_after="2026-07-10T00:00:00Z")
    import_a(
        store,
        key_id="expired-key",
        public_key_b64=base64.b64encode(bytes(range(64, 96))).decode("ascii"),
        not_after="2026-06-01T00:00:00Z",
    )
    import_a(
        store,
        key_id="revoked-key",
        public_key_b64=base64.b64encode(bytes(range(96, 128))).decode("ascii"),
    )
    revoke(store, key_id="revoked-key", reason="rotated away", now=NOW)
    report = status_report(store, now=NOW, expiring_days=30)
    assert report["counts"] == {
        "total": 4,
        "active": 1,
        "expiring_soon": 1,
        "expired": 1,
        "revoked": 1,
    }
    assert report["crl"]["exists"] and report["crl"]["revoked_key_ids"] == 1
    assert report["crl"]["size_bytes"] > 0
    assert report["problems"] == []


def test_status_of_missing_store_is_empty_not_an_error(tmp_path: Path) -> None:
    report = status_report(store_at(tmp_path), now=NOW)
    assert report["store_exists"] is False
    assert report["counts"]["total"] == 0
    assert report["problems"] == []


def test_list_reports_states_metadata_and_fingerprints_only(tmp_path: Path) -> None:
    store = store_at(tmp_path)
    import_a(store, not_before="2026-01-01T00:00:00Z")
    import_a(store, key_id="old-key", public_key_b64=B64_B, not_after="2026-06-01T00:00:00Z")
    report = list_keys_report(store, now=NOW)
    by_id = {key["key_id"]: key for key in report["keys"]}
    assert by_id["team-profiles-2026"]["state"] == "active"
    assert by_id["team-profiles-2026"]["display"] == "Platform team"
    assert by_id["team-profiles-2026"]["scopes"] == ["profile-bundles"]
    assert by_id["team-profiles-2026"]["not_before"] == "2026-01-01T00:00:00Z"
    assert by_id["team-profiles-2026"]["not_after"] == "2027-01-01T00:00:00Z"
    assert by_id["old-key"]["state"] == "expired"
    assert [key["key_id"] for key in report["keys"]] == sorted(by_id), "sorted by key_id"
    # Never full key bytes: only the abbreviated fingerprint appears.
    dumped = json.dumps(report)
    assert B64_A not in dumped and B64_B not in dumped
    assert by_id["team-profiles-2026"]["fingerprint"] == key_fingerprint(PUBLIC_A)
    assert len(by_id["team-profiles-2026"]["fingerprint"]) == 16


# ---------------------------------------------------------------------------
# import: public keys only; private material is refused and never written.


def assert_nothing_written(store: TrustStore) -> None:
    assert not store.trusted_keys_path.exists(), "refusal must write nothing"
    assert not store.metadata_path.exists()
    if store.directory.exists():
        assert not list(store.directory.glob("*.tmp")), "no temp leftovers"


@pytest.mark.parametrize(
    "public_key",
    [
        "-----BEGIN PRIVATE KEY-----\nMC4CAQAwBQYDK2VwBCIEIA==\n-----END PRIVATE KEY-----",
        "-----BEGIN ED25519 PRIVATE KEY-----\nabc\n-----END ED25519 PRIVATE KEY-----",
        "-----BEGIN OPENSSH PRIVATE KEY-----\nabc\n-----END OPENSSH PRIVATE KEY-----",
    ],
)
def test_import_refuses_pem_private_markers(tmp_path: Path, public_key: str) -> None:
    store = store_at(tmp_path)
    with pytest.raises(TrustStoreError, match="PUBLIC keys only"):
        import_a(store, public_key_b64=public_key)
    assert_nothing_written(store)


@pytest.mark.parametrize(
    ("length", "hint"),
    [(64, "seed"), (48, "PKCS#8")],
)
def test_import_refuses_private_length_material(tmp_path: Path, length: int, hint: str) -> None:
    store = store_at(tmp_path)
    material = base64.b64encode(b"\x01" * length).decode("ascii")
    with pytest.raises(TrustStoreError, match="PRIVATE key material"):
        import_a(store, public_key_b64=material)
    assert_nothing_written(store)


def test_import_refuses_non_32_byte_keys(tmp_path: Path) -> None:
    store = store_at(tmp_path)
    with pytest.raises(TrustStoreError, match="32-byte"):
        import_a(store, public_key_b64=base64.b64encode(b"\x01" * 31).decode("ascii"))
    with pytest.raises(TrustStoreError, match="not valid base64"):
        import_a(store, public_key_b64="@@not-base64@@")
    assert_nothing_written(store)


def test_key_file_with_private_fields_is_refused_and_never_written(tmp_path: Path) -> None:
    store = store_at(tmp_path)
    key_file = tmp_path / "key.json"
    key_file.write_text(
        json.dumps(
            {
                "key_id": "leaky",
                "public_key": B64_A,
                "private_key": "hunter2-seed-material",
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(TrustStoreError, match="PRIVATE key material field"):
        load_key_file(key_file)
    assert_nothing_written(store)
    pem_file = tmp_path / "key.pem.json"
    pem_file.write_text(
        '{"key_id": "x", "public_key": "-----BEGIN PRIVATE KEY-----..."}', encoding="utf-8"
    )
    with pytest.raises(TrustStoreError, match="PUBLIC keys only"):
        load_key_file(pem_file)
    assert_nothing_written(store)


def test_import_duplicate_key_id_with_different_material_is_loud(tmp_path: Path) -> None:
    store = store_at(tmp_path)
    import_a(store)
    before = store.trusted_keys_path.read_bytes()
    with pytest.raises(TrustStoreError, match="DIFFERENT key material"):
        import_a(store, public_key_b64=B64_B)
    assert store.trusted_keys_path.read_bytes() == before, "refusal changed nothing"
    # The refusal names fingerprints, never key bytes.
    try:
        import_a(store, public_key_b64=B64_B)
    except TrustStoreError as exc:
        assert B64_A not in str(exc) and B64_B not in str(exc)
        assert key_fingerprint(PUBLIC_A) in str(exc)


def test_import_same_material_is_idempotent(tmp_path: Path) -> None:
    store = store_at(tmp_path)
    import_a(store)
    before = store.trusted_keys_path.read_bytes()
    result = import_a(store)
    assert result == {
        "imported": False,
        "already_present": True,
        "key_id": "team-profiles-2026",
        "fingerprint": key_fingerprint(PUBLIC_A),
    }
    assert store.trusted_keys_path.read_bytes() == before


def test_import_validates_inputs(tmp_path: Path) -> None:
    store = store_at(tmp_path)
    with pytest.raises(TrustStoreError, match="key_id"):
        import_a(store, key_id="-bad-leading-dash")
    with pytest.raises(TrustStoreError, match="not_after"):
        import_a(store, not_after="2027-01-01 00:00:00")
    with pytest.raises(TrustStoreError, match="strictly before"):
        import_a(store, not_before="2028-01-01T00:00:00Z", not_after="2027-01-01T00:00:00Z")
    with pytest.raises(TrustStoreError, match="scope"):
        import_a(store, scopes=["NOT VALID"])
    assert_nothing_written(store)


# ---------------------------------------------------------------------------
# revoke: idempotent, append-only.


def test_revoke_is_idempotent_and_append_only(tmp_path: Path) -> None:
    store = store_at(tmp_path)
    import_a(store)
    first = revoke(store, key_id="team-profiles-2026", reason="stolen laptop", now=NOW)
    assert first["revoked"] is True and first["already_revoked"] is False
    again = revoke(store, key_id="team-profiles-2026", now=NOW)
    assert again["revoked"] is False and again["already_revoked"] is True
    crl = json.loads(store.crl_path.read_text(encoding="utf-8"))
    assert crl["revoked_key_ids"] == ["team-profiles-2026"], "no duplicate entries"
    # Appending a bundle hash keeps prior history intact (never deletes).
    sha = "cd" * 32
    revoke(store, bundle_sha256=sha, now=NOW)
    crl = json.loads(store.crl_path.read_text(encoding="utf-8"))
    assert crl["revoked_key_ids"] == ["team-profiles-2026"]
    assert crl["revoked_bundles"] == [sha]
    metadata = json.loads(store.metadata_path.read_text(encoding="utf-8"))
    assert len(metadata["revocations"]) == 2, "idempotent repeats add no history rows"


def test_revoke_validates_targets(tmp_path: Path) -> None:
    store = store_at(tmp_path)
    with pytest.raises(TrustStoreError, match="exactly one"):
        revoke(store)
    with pytest.raises(TrustStoreError, match="exactly one"):
        revoke(store, key_id="a", bundle_sha256="ab" * 32)
    with pytest.raises(TrustStoreError, match="64 lowercase hex"):
        revoke(store, bundle_sha256="not-a-hash")
    assert not store.crl_path.exists()


# ---------------------------------------------------------------------------
# doctor: each problem class.


def test_doctor_healthy_store_exits_zero(tmp_path: Path) -> None:
    store = store_at(tmp_path)
    import_a(store)
    report = doctor_report(store, now=NOW)
    assert report["status"] == "ok" and report["exit_code"] == 0
    assert report["problems"] == []


def test_doctor_missing_store_is_ok(tmp_path: Path) -> None:
    report = doctor_report(store_at(tmp_path), now=NOW)
    assert report["exit_code"] == 0 and report["status"] == "ok"


def test_doctor_catches_duplicate_key_ids(tmp_path: Path) -> None:
    store = store_at(tmp_path)
    import_a(store)
    document = json.loads(store.trusted_keys_path.read_text(encoding="utf-8"))
    document["keys"].append(dict(document["keys"][0]))
    store.trusted_keys_path.write_text(json.dumps(document), encoding="utf-8")
    report = doctor_report(store, now=NOW)
    assert report["exit_code"] == 1
    assert any("duplicate key_id" in problem for problem in report["problems"])


def test_doctor_catches_expired_but_not_rotated(tmp_path: Path) -> None:
    store = store_at(tmp_path)
    import_a(store, not_after="2026-06-01T00:00:00Z")  # already expired at NOW
    report = doctor_report(store, now=NOW)
    assert report["exit_code"] == 1
    assert any("expired-but-not-rotated" in problem for problem in report["problems"])
    # With an active replacement the expired key is only a rotation-tail warning.
    import_a(store, key_id="team-profiles-2027", public_key_b64=B64_B)
    report = doctor_report(store, now=NOW)
    assert report["exit_code"] == 0
    assert any("rotation overlap" in warning for warning in report["warnings"])


def test_doctor_catches_unreadable_crl(tmp_path: Path) -> None:
    store = store_at(tmp_path)
    import_a(store)
    store.crl_path.parent.mkdir(parents=True, exist_ok=True)
    store.crl_path.write_text("{not json", encoding="utf-8")
    report = doctor_report(store, now=NOW)
    assert report["exit_code"] == 1
    assert any("not valid JSON" in problem for problem in report["problems"])


def test_doctor_catches_malformed_store_files(tmp_path: Path) -> None:
    store = store_at(tmp_path)
    store.directory.mkdir(parents=True)
    store.trusted_keys_path.write_text('{"schema_version": 2, "keys": "nope"}', encoding="utf-8")
    report = doctor_report(store, now=NOW)
    assert report["exit_code"] == 1
    assert any("schema_version 1" in problem for problem in report["problems"])
    store.trusted_keys_path.write_text("garbage", encoding="utf-8")
    assert doctor_report(store, now=NOW)["exit_code"] == 1


def test_doctor_flags_unexplained_revocations_and_accepts_explained_ones(tmp_path: Path) -> None:
    store = store_at(tmp_path)
    import_a(store)
    # Revoked through the store: explained -> warning only.
    revoke(store, key_id="team-profiles-2026", reason="rotated", now=NOW)
    import_a(store, key_id="team-profiles-2027", public_key_b64=B64_B)
    report = doctor_report(store, now=NOW)
    assert report["exit_code"] == 0
    assert any("CRL wins" in warning for warning in report["warnings"])
    # Revoked OUTSIDE the store (hand-edited CRL, no metadata record): problem.
    crl = json.loads(store.crl_path.read_text(encoding="utf-8"))
    crl["revoked_key_ids"].append("team-profiles-2027")
    store.crl_path.write_text(json.dumps(crl), encoding="utf-8")
    report = doctor_report(store, now=NOW)
    assert report["exit_code"] == 1
    assert any("no metadata revocation record" in problem for problem in report["problems"])


def test_doctor_warns_on_expiring_soon_and_empty_store(tmp_path: Path) -> None:
    store = store_at(tmp_path)
    import_a(store, not_after="2026-07-10T00:00:00Z")
    report = doctor_report(store, now=NOW, expiring_days=30)
    assert report["exit_code"] == 0
    assert any("expires within 30 day" in warning for warning in report["warnings"])
    # An empty keys list is a warning (the gateway would refuse -32019).
    store.trusted_keys_path.write_text('{"schema_version": 1, "keys": []}', encoding="utf-8")
    report = doctor_report(store, now=NOW)
    assert report["exit_code"] == 0
    assert any("bundle_key_missing" in warning for warning in report["warnings"])


# ---------------------------------------------------------------------------
# Atomic writes.


def test_failed_write_leaves_no_partial_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    store = store_at(tmp_path)

    def explode(src, dst):
        raise OSError("simulated replace failure")

    monkeypatch.setattr(ts.os, "replace", explode)
    with pytest.raises(OSError, match="simulated"):
        import_a(store)
    monkeypatch.undo()
    assert not store.trusted_keys_path.exists(), "no partial trusted-keys file"
    assert not list(store.directory.glob("*.tmp")), "temp file cleaned up"
    # The store still works after the failure.
    assert import_a(store)["imported"] is True
    load_trusted_keys(store.trusted_keys_path)


# ---------------------------------------------------------------------------
# Gateway integration: the managed store as the default --trusted-keys.


def gateway_args(**overrides) -> Namespace:
    base = {
        "root": "",
        "profiles": "",
        "profile": "",
        "profile_bundle": "",
        "trusted_keys": "",
        "audience_id": None,
        "require_signed_profiles": False,
    }
    base.update(overrides)
    return Namespace(**base)


def signed_bundle(tmp_path: Path, private, key_id: str) -> Path:
    document = {
        "bundle_version": 1,
        "issuer": {"key_id": key_id, "display": "Test platform team"},
        "audience": ["team:test"],
        "issued_at": "2020-01-01T00:00:00Z",
        "expires_at": "2099-01-01T00:00:00Z",
        "allowed_upstream_namespaces": ["fake.*"],
        "default_profile": "dev",
        "profiles": {"dev": {"visible": ["fake.*"], "callable": ["fake.*"]}},
    }
    signature = private.sign(canonical_bundle_bytes(document))
    document["signature"] = {
        "algorithm": "ed25519",
        "key_id": key_id,
        "value": base64.b64encode(signature).decode("ascii"),
    }
    path = tmp_path / "bundle.json"
    path.write_text(json.dumps(document), encoding="utf-8")
    return path


@requires_ed25519
def test_gateway_defaults_to_managed_store_when_present(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("UNLIMITED_SKILLS_MCP_PROFILE", raising=False)
    monkeypatch.delenv("UNLIMITED_SKILLS_MCP_AUDIENCE", raising=False)
    root = tmp_path / "library"
    root.mkdir()
    private = Ed25519PrivateKey.generate()
    public = private.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    store = TrustStore(default_store_dir(root))
    import_key(
        store,
        key_id="managed-key-2026",
        public_key_b64=base64.b64encode(public).decode("ascii"),
        now=NOW,
    )
    assert managed_trusted_keys_path(root) == store.trusted_keys_path
    bundle_path = signed_bundle(tmp_path, private, "managed-key-2026")
    state, note = _resolve_gateway_profile_state(
        gateway_args(
            root=str(root), profile_bundle=str(bundle_path), audience_id=["team:test"]
        )
    )
    assert isinstance(state, ActiveProfile) and state.name == "dev"
    assert "signed bundle profile 'dev' enforced" in note
    # A key revoked through the store refuses via the bundle's CRL pointer
    # semantics only; here prove the managed file is what verified: an
    # explicit --trusted-keys pointing elsewhere WINS over the managed store.
    other_keys = tmp_path / "other-keys.json"
    other_keys.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "keys": [
                    {
                        "key_id": "unrelated",
                        "algorithm": "ed25519",
                        "public_key": base64.b64encode(b"\x07" * 32).decode("ascii"),
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    state, _ = _resolve_gateway_profile_state(
        gateway_args(
            root=str(root),
            profile_bundle=str(bundle_path),
            trusted_keys=str(other_keys),
            audience_id=["team:test"],
        )
    )
    assert isinstance(state, BundleFailClosed) and state.code == BUNDLE_KEY_MISSING


@requires_ed25519
def test_gateway_unchanged_when_no_managed_store_exists(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("UNLIMITED_SKILLS_MCP_PROFILE", raising=False)
    monkeypatch.delenv("UNLIMITED_SKILLS_MCP_AUDIENCE", raising=False)
    root = tmp_path / "library"
    root.mkdir()
    private = Ed25519PrivateKey.generate()
    bundle_path = signed_bundle(tmp_path, private, "managed-key-2026")
    state, note = _resolve_gateway_profile_state(
        gateway_args(root=str(root), profile_bundle=str(bundle_path), audience_id=["team:test"])
    )
    assert isinstance(state, BundleFailClosed) and state.code == BUNDLE_KEY_MISSING
    assert "no trusted-keys file configured" in state.message
    assert "FAIL-CLOSED" in note


@requires_ed25519
def test_managed_revocation_flows_into_verification(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A bundle whose crl_path points at the managed crl.json is refused
    after `trust revoke` -- the store manages the very files E14 reads."""
    monkeypatch.delenv("UNLIMITED_SKILLS_MCP_PROFILE", raising=False)
    monkeypatch.delenv("UNLIMITED_SKILLS_MCP_AUDIENCE", raising=False)
    root = tmp_path / "library"
    root.mkdir()
    private = Ed25519PrivateKey.generate()
    public = private.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    store = TrustStore(default_store_dir(root))
    import_key(
        store,
        key_id="managed-key-2026",
        public_key_b64=base64.b64encode(public).decode("ascii"),
        now=NOW,
    )
    document = {
        "bundle_version": 1,
        "issuer": {"key_id": "managed-key-2026", "display": "Test platform team"},
        "audience": ["team:test"],
        "issued_at": "2020-01-01T00:00:00Z",
        "expires_at": "2099-01-01T00:00:00Z",
        "allowed_upstream_namespaces": ["fake.*"],
        "default_profile": "dev",
        "profiles": {"dev": {"visible": ["fake.*"], "callable": ["fake.*"]}},
        "revocation": {"crl_path": str(store.crl_path)},
    }
    signature = private.sign(canonical_bundle_bytes(document))
    document["signature"] = {
        "algorithm": "ed25519",
        "key_id": "managed-key-2026",
        "value": base64.b64encode(signature).decode("ascii"),
    }
    bundle_path = tmp_path / "bundle.json"
    bundle_path.write_text(json.dumps(document), encoding="utf-8")
    args = gateway_args(
        root=str(root), profile_bundle=str(bundle_path), audience_id=["team:test"]
    )
    # The bundle declares a CRL that does not exist yet: fail-closed E14
    # semantics unchanged (declared-but-unreadable CRL is bundle_revoked).
    state, _ = _resolve_gateway_profile_state(args)
    assert isinstance(state, BundleFailClosed) and state.code == BUNDLE_REVOKED
    # Revoking an unrelated bundle creates the CRL; verification now passes.
    revoke(store, bundle_sha256="ef" * 32, now=NOW)
    state, _ = _resolve_gateway_profile_state(args)
    assert isinstance(state, ActiveProfile)
    # Revoking THE signing key refuses the bundle.
    revoke(store, key_id="managed-key-2026", reason="test revocation", now=NOW)
    state, _ = _resolve_gateway_profile_state(args)
    assert isinstance(state, BundleFailClosed) and state.code == BUNDLE_REVOKED


# ---------------------------------------------------------------------------
# CLI wiring through the facade (unlimited_skills.cli.main).


def trust_cli(root: Path, *argv: str) -> int:
    return main(["--root", str(root), "mcp", "trust", *argv])


def test_cli_import_status_list_doctor_roundtrip(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    root = tmp_path / "library"
    root.mkdir()
    assert (
        trust_cli(
            root,
            "import",
            "--key-id",
            "cli-key-2026",
            "--public-key",
            B64_A,
            "--display",
            "CLI team",
            "--not-after",
            "2099-01-01T00:00:00Z",
            "--json",
        )
        == 0
    )
    imported = json.loads(capsys.readouterr().out)
    assert imported["imported"] is True and imported["key_id"] == "cli-key-2026"
    assert (default_store_dir(root) / "trusted-keys.json").is_file()

    assert trust_cli(root, "status", "--json") == 0
    status = json.loads(capsys.readouterr().out)
    assert status["counts"]["total"] == 1 and status["counts"]["active"] == 1

    assert trust_cli(root, "list", "--json") == 0
    listing = json.loads(capsys.readouterr().out)
    assert listing["keys"][0]["key_id"] == "cli-key-2026"
    assert B64_A not in json.dumps(listing), "full key bytes never printed"

    assert trust_cli(root, "doctor", "--json") == 0
    doctor = json.loads(capsys.readouterr().out)
    assert doctor["status"] == "ok" and doctor["exit_code"] == 0

    # Human (non-JSON) renderers never print full key bytes either.
    assert trust_cli(root, "status") == 0
    assert trust_cli(root, "list") == 0
    assert trust_cli(root, "doctor") == 0
    text = capsys.readouterr().out
    assert B64_A not in text and "cli-key-2026" in text


def test_cli_revoke_and_doctor_exit_codes(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    root = tmp_path / "library"
    root.mkdir()
    trust_cli(root, "import", "--key-id", "cli-key-2026", "--public-key", B64_A)
    capsys.readouterr()
    assert trust_cli(root, "revoke", "--key-id", "cli-key-2026", "--reason", "test", "--json") == 0
    revoked = json.loads(capsys.readouterr().out)
    assert revoked["revoked"] is True
    assert trust_cli(root, "revoke", "--key-id", "cli-key-2026") == 0
    assert "already in the local CRL" in capsys.readouterr().out
    # All keys revoked (none active, none expired) -> doctor warns but is ok;
    # break the CRL on disk -> doctor exits 1.
    crl_path = default_store_dir(root) / "crl.json"
    crl_path.write_text("{broken", encoding="utf-8")
    assert trust_cli(root, "doctor", "--json") == 1
    report = json.loads(capsys.readouterr().out)
    assert report["exit_code"] == 1


def test_cli_import_refusals_exit_one(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    root = tmp_path / "library"
    root.mkdir()
    assert (
        trust_cli(
            root,
            "import",
            "--key-id",
            "k",
            "--public-key",
            "-----BEGIN PRIVATE KEY-----abc-----END PRIVATE KEY-----",
        )
        == 1
    )
    err = capsys.readouterr().err
    assert "trust import refused" in err and "PUBLIC keys only" in err
    assert not default_store_dir(root).exists(), "refusal wrote nothing at all"
    # Missing key material is a refusal too.
    assert trust_cli(root, "import", "--key-id", "k") == 1
    assert trust_cli(root, "revoke") == 1


def test_cli_key_file_import(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    root = tmp_path / "library"
    root.mkdir()
    key_file = tmp_path / "key.json"
    key_file.write_text(
        json.dumps(
            {
                "key_id": "file-key-2026",
                "public_key": B64_A,
                "display": "From file",
                "scopes": ["profile-bundles"],
                "not_after": "2099-01-01T00:00:00Z",
            }
        ),
        encoding="utf-8",
    )
    assert trust_cli(root, "import", "--key-file", str(key_file), "--json") == 0
    imported = json.loads(capsys.readouterr().out)
    assert imported["key_id"] == "file-key-2026"
    trusted = load_trusted_keys(default_store_dir(root) / "trusted-keys.json")
    assert trusted["file-key-2026"].public_key == PUBLIC_A


def test_cli_store_dir_override(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    root = tmp_path / "library"
    root.mkdir()
    custom = tmp_path / "custom-store"
    assert (
        trust_cli(
            root,
            "import",
            "--store-dir",
            str(custom),
            "--key-id",
            "custom-key",
            "--public-key",
            B64_A,
        )
        == 0
    )
    capsys.readouterr()
    assert (custom / "trusted-keys.json").is_file()
    assert not default_store_dir(root).exists()
