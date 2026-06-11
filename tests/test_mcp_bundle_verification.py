"""E14: signed MCP profile bundle verification (prototype).

Proves the contract of docs/mcp-signed-profile-bundles.md against
``unlimited_skills.mcp.bundles``:

- a verified bundle's embedded profiles enforce exactly like raw E10
  profiles (same decisions, same refusal codes, same audit redaction);
- every refusal path of the 10-step verification algorithm: tampering and
  stripped/placeholder signatures (-32015), missing keys / trusted-keys file
  / verifier backend and expired key trust (-32019), expired and
  not-yet-valid windows with the 300 s skew (-32016), bundle and key
  revocation plus declared-but-unreadable CRL fail-closed (-32017), audience
  mismatch and namespace-ceiling violations (-32018), malformed bundles and
  self-contained ``extends`` (-32014), unresolved selection (-32013);
- verification ORDER: the first failing step wins;
- key rotation: multiple active keys selected by ``key_id``;
- the signed-required policy refuses unsigned profile sources (-32015);
- the narrow-only local override: intersection with a local unsigned file
  can narrow the bundle and never widen it;
- ``profile_loaded`` audit provenance (source type, bundle SHA-256, issuer,
  key id, audience, verification status) without leaking key material or
  signature values.

Keys are EPHEMERAL test fixtures generated per test (never committed).
Real-Ed25519 tests require the optional ``cryptography`` package and are
skipped without it; the verification order and refusal paths are also
exercised with a clearly-marked TEST-ONLY deterministic fake backend, so
the algorithm stays covered on hosts without any crypto library.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import sys
from argparse import Namespace
from pathlib import Path

import pytest

from unlimited_skills.commands.mcp import _resolve_gateway_profile_state
from unlimited_skills.mcp.audit import AuditLog
from unlimited_skills.mcp.bundles import (
    AUDIENCE_ENV_VAR,
    BUNDLE_AUDIENCE_MISMATCH,
    BUNDLE_EXPIRED,
    BUNDLE_KEY_MISSING,
    BUNDLE_REVOKED,
    BUNDLE_SIGNATURE_INVALID,
    BundleFailClosed,
    SignatureBackend,
    canonical_bundle_bytes,
    default_signature_backend,
    local_audience_ids,
    require_signed_refusal,
    resolve_bundle_state,
    _parse_timestamp,
)
from unlimited_skills.mcp.gateway import Gateway, GatewayConfigError, UpstreamError, build_gateway_registry
from unlimited_skills.mcp.profiles import (
    PROFILE_INVALID,
    PROFILE_NOT_FOUND,
    TOOL_NOT_CALLABLE,
    TOOL_NOT_VISIBLE,
    ActiveProfile,
    resolve_profile_state,
)

try:  # the optional real-Ed25519 backend dependency
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

    HAVE_CRYPTOGRAPHY = True
except ImportError:  # pragma: no cover - exercised only without cryptography
    HAVE_CRYPTOGRAPHY = False

requires_ed25519 = pytest.mark.skipif(
    not HAVE_CRYPTOGRAPHY, reason="optional 'cryptography' package not installed"
)

KEY_ID = "test-team-profiles-2026"
NOW = _parse_timestamp("2026-07-01T00:00:00Z")  # inside the base validity window


# ---------------------------------------------------------------------------
# Fixture signers: real Ed25519 (ephemeral) and a TEST-ONLY fake backend.


def ed25519_keypair() -> tuple["Ed25519PrivateKey", bytes]:
    private = Ed25519PrivateKey.generate()
    public = private.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    return private, public


class FakeHmacBackend(SignatureBackend):
    """TEST-ONLY deterministic backend: HMAC-SHA256 keyed by the 'public key'.

    Clearly NOT a signature scheme (anyone with the verification key can
    forge); it exists purely so the verification ORDER and every refusal
    path can be exercised without curve math or optional dependencies.
    """

    name = "test-only-hmac"

    def verify(self, public_key: bytes, message: bytes, signature: bytes) -> bool:
        return hmac.compare_digest(hmac.new(public_key, message, "sha256").digest(), signature)


FAKE_PUBLIC = b"\x07" * 32


def fake_sign(message: bytes, public_key: bytes = FAKE_PUBLIC) -> bytes:
    return hmac.new(public_key, message, "sha256").digest()


# ---------------------------------------------------------------------------
# Bundle / trusted-keys / CRL builders.


def base_bundle(key_id: str = KEY_ID) -> dict:
    return {
        "bundle_version": 1,
        "issuer": {"key_id": key_id, "display": "Test platform team"},
        "audience": ["team:test", "host:ci"],
        "issued_at": "2026-06-01T00:00:00Z",
        "expires_at": "2026-09-01T00:00:00Z",
        "allowed_upstream_namespaces": ["fake.*", "other.*"],
        "default_profile": "dev",
        "profiles": {
            "dev": {"visible": ["fake.*", "other.*"], "callable": ["fake.*", "other.*"]},
            "reviewer": {
                "extends": "dev",
                "visible": ["fake.echo", "fake.add"],
                "callable": ["fake.echo"],
            },
        },
    }


def attach_signature(document: dict, signature: bytes, key_id: str) -> dict:
    document["signature"] = {
        "algorithm": "ed25519",
        "key_id": key_id,
        "value": base64.b64encode(signature).decode("ascii"),
    }
    return document


def sign_real(document: dict, private: "Ed25519PrivateKey", key_id: str = KEY_ID) -> dict:
    return attach_signature(document, private.sign(canonical_bundle_bytes(document)), key_id)


def sign_fake(document: dict, key_id: str = KEY_ID, public_key: bytes = FAKE_PUBLIC) -> dict:
    return attach_signature(document, fake_sign(canonical_bundle_bytes(document), public_key), key_id)


def write_json(path: Path, document: dict) -> Path:
    path.write_text(json.dumps(document), encoding="utf-8")
    return path


def trusted_keys_doc(entries: list[tuple[str, bytes, str | None]]) -> dict:
    keys = []
    for key_id, public, not_after in entries:
        entry: dict = {
            "key_id": key_id,
            "algorithm": "ed25519",
            "public_key": base64.b64encode(public).decode("ascii"),
        }
        if not_after:
            entry["not_after"] = not_after
        keys.append(entry)
    return {"schema_version": 1, "keys": keys}


def real_env(
    tmp_path: Path,
    mutate=None,
    tamper=None,
    key_id: str = KEY_ID,
    not_after: str | None = None,
) -> tuple[Path, Path, dict]:
    """One ephemeral keypair, a signed bundle file, and a trusted-keys file.

    ``mutate`` edits the document BEFORE signing (legitimately issued);
    ``tamper`` edits it AFTER signing (an attacker's modification).
    """
    private, public = ed25519_keypair()
    document = base_bundle(key_id)
    if mutate is not None:
        mutate(document)
    sign_real(document, private, key_id)
    if tamper is not None:
        tamper(document)
    bundle_path = write_json(tmp_path / "bundle.json", document)
    keys_path = write_json(
        tmp_path / "trusted-keys.json", trusted_keys_doc([(key_id, public, not_after)])
    )
    return bundle_path, keys_path, document


def fake_env(tmp_path: Path, mutate=None, tamper=None, key_id: str = KEY_ID) -> tuple[Path, Path, dict]:
    document = base_bundle(key_id)
    if mutate is not None:
        mutate(document)
    sign_fake(document, key_id)
    if tamper is not None:
        tamper(document)
    bundle_path = write_json(tmp_path / "bundle.json", document)
    keys_path = write_json(
        tmp_path / "trusted-keys.json", trusted_keys_doc([(key_id, FAKE_PUBLIC, None)])
    )
    return bundle_path, keys_path, document


def resolve(bundle_path: Path, keys_path: Path | None, **kwargs):
    kwargs.setdefault("cli_name", "")
    kwargs.setdefault("env_name", "")
    kwargs.setdefault("audience_ids", ["team:test"])
    kwargs.setdefault("now", NOW)
    return resolve_bundle_state(bundle_path, trusted_keys_path=keys_path, **kwargs)


def resolve_fake(bundle_path: Path, keys_path: Path | None, **kwargs):
    kwargs.setdefault("backend", FakeHmacBackend())
    return resolve(bundle_path, keys_path, **kwargs)


def assert_refused(state, code: int, name: str) -> BundleFailClosed:
    assert isinstance(state, BundleFailClosed), state
    assert state.code == code
    assert name in state.message
    return state


GATEWAY_CONFIG = {
    "schema_version": 1,
    "upstreams": [
        {
            "name": "fake",
            "command": sys.executable,
            "tools": [
                {"name": "echo", "description": "Echo text back"},
                {"name": "add", "description": "Add two integers"},
                {"name": "secret_wipe", "description": "Wipe the secret data storage"},
            ],
        },
        {
            "name": "other",
            "command": sys.executable,
            "tools": [{"name": "shred", "description": "Shred documents permanently"}],
        },
    ],
}

TOOL_MATRIX = (("fake", "echo"), ("fake", "add"), ("fake", "secret_wipe"), ("other", "shred"))


def audit_rows(path: Path) -> list[dict]:
    text = path.read_text(encoding="utf-8")
    return [json.loads(line) for line in text.splitlines() if line.strip()]


# ---------------------------------------------------------------------------
# Happy path and E10 enforcement integration.


@requires_ed25519
def test_verified_bundle_yields_active_profile_with_provenance(tmp_path: Path) -> None:
    bundle_path, keys_path, _ = real_env(tmp_path)
    state = resolve(bundle_path, keys_path)
    assert isinstance(state, ActiveProfile)
    assert state.name == "dev"
    expected_sha = hashlib.sha256(bundle_path.read_bytes()).hexdigest()
    assert state.file_sha256 == expected_sha
    provenance = state.provenance
    assert provenance is not None
    assert provenance.audit_fields() == {
        "profile_source": "signed_bundle",
        "bundle_sha256": expected_sha,
        "issuer_key_id": KEY_ID,
        "issuer_display": "Test platform team",
        "audience": ["team:test", "host:ci"],
        "expires_at": "2026-09-01T00:00:00Z",
        "verification": "verified",
    }


@requires_ed25519
def test_verified_bundle_enforces_exactly_like_raw_profile(tmp_path: Path) -> None:
    """A verified bundle's embedded profiles make the SAME decisions as the
    identical raw E10 profile file -- bundle verification adds provenance,
    never different enforcement."""
    bundle_path, keys_path, document = real_env(tmp_path)
    bundle_state = resolve(bundle_path, keys_path, cli_name="reviewer")
    assert isinstance(bundle_state, ActiveProfile)
    raw_path = write_json(
        tmp_path / "raw-profiles.json",
        {"schema_version": 1, "default_profile": "dev", "profiles": document["profiles"]},
    )
    raw_state = resolve_profile_state(raw_path, cli_name="reviewer", env_name="")
    assert isinstance(raw_state, ActiveProfile)
    for upstream, tool in TOOL_MATRIX:
        assert bundle_state.is_visible(upstream, tool) == raw_state.is_visible(upstream, tool)
        assert bundle_state.is_callable(upstream, tool) == raw_state.is_callable(upstream, tool)
    # Through the gateway: search filtering, -32011 and -32012, like E10.
    gateway = Gateway(GATEWAY_CONFIG, AuditLog(tmp_path / "audit.jsonl"), profile=bundle_state)
    try:
        assert gateway.tools_search({"query": "secret wipe"})["hits"] == []
        hits = gateway.tools_search({"query": "echo text"})["hits"]
        assert [hit["tool"] for hit in hits] == ["fake.echo"]
        assert hits[0]["callable"] is True
        with pytest.raises(UpstreamError) as excinfo:
            gateway.tools_schema({"tool": "fake.secret_wipe"})
        assert excinfo.value.code == TOOL_NOT_VISIBLE
        with pytest.raises(UpstreamError) as excinfo:
            gateway.tools_call({"tool": "fake.add", "arguments": {"a": 1, "b": 2}})
        assert excinfo.value.code == TOOL_NOT_CALLABLE
    finally:
        gateway.shutdown()


@requires_ed25519
def test_selection_precedence_cli_env_bundle_default(tmp_path: Path) -> None:
    bundle_path, keys_path, _ = real_env(tmp_path)
    cli_wins = resolve(bundle_path, keys_path, cli_name="reviewer", env_name="dev")
    assert isinstance(cli_wins, ActiveProfile) and cli_wins.name == "reviewer"
    env_wins = resolve(bundle_path, keys_path, cli_name="", env_name="reviewer")
    assert isinstance(env_wins, ActiveProfile) and env_wins.name == "reviewer"
    file_default = resolve(bundle_path, keys_path)
    assert isinstance(file_default, ActiveProfile) and file_default.name == "dev"


@requires_ed25519
def test_unresolved_selection_is_profile_not_found(tmp_path: Path) -> None:
    def drop_default(document: dict) -> None:
        del document["default_profile"]

    bundle_path, keys_path, _ = real_env(tmp_path, mutate=drop_default)
    nothing = resolve(bundle_path, keys_path)
    assert isinstance(nothing, BundleFailClosed)
    assert nothing.code == PROFILE_NOT_FOUND and nothing.requested == ""
    missing = resolve(bundle_path, keys_path, cli_name="ghost")
    assert isinstance(missing, BundleFailClosed)
    assert missing.code == PROFILE_NOT_FOUND and missing.requested == "ghost"
    assert missing.bundle_sha256, "selection failures still pin the verified bundle hash"


# ---------------------------------------------------------------------------
# -32015 bundle_signature_invalid.


@requires_ed25519
def test_tampered_bundle_refused(tmp_path: Path) -> None:
    def widen_audience(document: dict) -> None:
        document["audience"].append("org:everyone")

    bundle_path, keys_path, _ = real_env(tmp_path, tamper=widen_audience)
    assert_refused(
        resolve(bundle_path, keys_path), BUNDLE_SIGNATURE_INVALID, "bundle_signature_invalid"
    )


@requires_ed25519
def test_signature_over_different_document_refused(tmp_path: Path) -> None:
    private, public = ed25519_keypair()
    other = base_bundle()
    other["expires_at"] = "2026-12-01T00:00:00Z"
    foreign_signature = private.sign(canonical_bundle_bytes(other))
    document = attach_signature(base_bundle(), foreign_signature, KEY_ID)
    bundle_path = write_json(tmp_path / "bundle.json", document)
    keys_path = write_json(tmp_path / "keys.json", trusted_keys_doc([(KEY_ID, public, None)]))
    assert_refused(
        resolve(bundle_path, keys_path), BUNDLE_SIGNATURE_INVALID, "bundle_signature_invalid"
    )


@requires_ed25519
def test_repo_example_placeholder_signature_refused(tmp_path: Path) -> None:
    """The committed example's signature is base64 zero bytes by design --
    a real verifier must refuse it."""
    example = Path(__file__).resolve().parents[1] / "examples" / "mcp" / "profile-bundle.example.json"
    document = json.loads(example.read_text(encoding="utf-8"))
    _, public = ed25519_keypair()
    keys_path = write_json(
        tmp_path / "keys.json",
        trusted_keys_doc([(document["issuer"]["key_id"], public, None)]),
    )
    state = resolve(
        example,
        keys_path,
        audience_ids=["team:core-ai4sale"],
        now=_parse_timestamp("2026-07-01T00:00:00Z"),
    )
    assert_refused(state, BUNDLE_SIGNATURE_INVALID, "bundle_signature_invalid")


# ---------------------------------------------------------------------------
# -32019 bundle_key_missing (fail-closed, never a fallback to unsigned).


def test_unknown_key_id_refused(tmp_path: Path) -> None:
    bundle_path, _, _ = fake_env(tmp_path)
    keys_path = write_json(
        tmp_path / "other-keys.json", trusted_keys_doc([("some-other-key", FAKE_PUBLIC, None)])
    )
    assert_refused(resolve_fake(bundle_path, keys_path), BUNDLE_KEY_MISSING, "bundle_key_missing")


def test_missing_or_unconfigured_trusted_keys_file_refused(tmp_path: Path) -> None:
    bundle_path, _, _ = fake_env(tmp_path)
    missing = resolve_fake(bundle_path, tmp_path / "no-such-keys.json")
    assert_refused(missing, BUNDLE_KEY_MISSING, "bundle_key_missing")
    unconfigured = resolve_fake(bundle_path, None)
    assert_refused(unconfigured, BUNDLE_KEY_MISSING, "bundle_key_missing")


def test_malformed_trusted_keys_file_refused(tmp_path: Path) -> None:
    bundle_path, _, _ = fake_env(tmp_path)
    for label, document in {
        "wrong-length-key": trusted_keys_doc([(KEY_ID, b"\x01" * 16, None)]),
        "wrong-algorithm": {
            "schema_version": 1,
            "keys": [{"key_id": KEY_ID, "algorithm": "rsa", "public_key": "QQ=="}],
        },
        "not-json": None,
    }.items():
        keys_path = tmp_path / f"keys-{label}.json"
        if document is None:
            keys_path.write_text("{not json", encoding="utf-8")
        else:
            write_json(keys_path, document)
        state = resolve_fake(bundle_path, keys_path)
        assert_refused(state, BUNDLE_KEY_MISSING, "bundle_key_missing")


def test_key_past_not_after_refused(tmp_path: Path) -> None:
    document = base_bundle()
    sign_fake(document)
    bundle_path = write_json(tmp_path / "bundle.json", document)
    keys_path = write_json(
        tmp_path / "keys.json",
        trusted_keys_doc([(KEY_ID, FAKE_PUBLIC, "2026-06-15T00:00:00Z")]),
    )
    state = resolve_fake(bundle_path, keys_path)  # NOW is 2026-07-01
    assert_refused(state, BUNDLE_KEY_MISSING, "bundle_key_missing")
    still_valid = resolve_fake(bundle_path, keys_path, now=_parse_timestamp("2026-06-10T00:00:00Z"))
    assert isinstance(still_valid, ActiveProfile)


def test_missing_verifier_backend_refused(tmp_path: Path) -> None:
    bundle_path, keys_path, _ = fake_env(tmp_path)
    state = resolve(bundle_path, keys_path, backend=None)
    failure = assert_refused(state, BUNDLE_KEY_MISSING, "bundle_key_missing")
    assert "no verifier backend" in failure.message


@requires_ed25519
def test_key_rotation_two_active_keys(tmp_path: Path) -> None:
    """The overlap window: bundles signed by either active key verify; the
    signature's key_id selects the verification key with no heuristics."""
    old_private, old_public = ed25519_keypair()
    new_private, new_public = ed25519_keypair()
    keys_path = write_json(
        tmp_path / "keys.json",
        trusted_keys_doc(
            [("team-key-2025", old_public, None), ("team-key-2026", new_public, None)]
        ),
    )
    for key_id, private in (("team-key-2025", old_private), ("team-key-2026", new_private)):
        document = sign_real(base_bundle(key_id), private, key_id)
        bundle_path = write_json(tmp_path / f"bundle-{key_id}.json", document)
        state = resolve(bundle_path, keys_path)
        assert isinstance(state, ActiveProfile), key_id
        assert state.provenance.issuer_key_id == key_id


# ---------------------------------------------------------------------------
# -32016 bundle_expired (expired AND not-yet-valid; +-300 s skew).


def test_expired_and_not_yet_valid_refused_within_skew_accepted(tmp_path: Path) -> None:
    bundle_path, keys_path, _ = fake_env(tmp_path)
    expires = _parse_timestamp("2026-09-01T00:00:00Z")
    issued = _parse_timestamp("2026-06-01T00:00:00Z")
    expired = resolve_fake(bundle_path, keys_path, now=expires + 301)
    assert_refused(expired, BUNDLE_EXPIRED, "bundle_expired")
    not_yet = resolve_fake(bundle_path, keys_path, now=issued - 301)
    assert_refused(not_yet, BUNDLE_EXPIRED, "bundle_expired")
    inside_skew_late = resolve_fake(bundle_path, keys_path, now=expires + 299)
    assert isinstance(inside_skew_late, ActiveProfile)
    inside_skew_early = resolve_fake(bundle_path, keys_path, now=issued - 299)
    assert isinstance(inside_skew_early, ActiveProfile)


# ---------------------------------------------------------------------------
# -32017 bundle_revoked (CRL by bundle SHA-256, by key_id, and fail-closed
# on a declared-but-unreadable CRL).


def crl_bundle_env(tmp_path: Path, crl_document: dict | str | None) -> tuple[Path, Path]:
    crl_path = tmp_path / "crl.json"

    def add_revocation(document: dict) -> None:
        document["revocation"] = {"crl_path": str(crl_path)}

    bundle_path, keys_path, _ = fake_env(tmp_path, mutate=add_revocation)
    if isinstance(crl_document, dict):
        write_json(crl_path, crl_document)
    elif isinstance(crl_document, str):
        crl_path.write_text(crl_document, encoding="utf-8")
    return bundle_path, keys_path


def test_revoked_bundle_sha256_refused(tmp_path: Path) -> None:
    bundle_path, keys_path = crl_bundle_env(
        tmp_path, {"schema_version": 1, "revoked_bundles": [], "revoked_key_ids": []}
    )
    sha256 = hashlib.sha256(bundle_path.read_bytes()).hexdigest()
    write_json(
        tmp_path / "crl.json",
        {"schema_version": 1, "revoked_bundles": [sha256], "revoked_key_ids": []},
    )
    assert_refused(resolve_fake(bundle_path, keys_path), BUNDLE_REVOKED, "bundle_revoked")


def test_revoked_key_id_kills_every_bundle_it_signed(tmp_path: Path) -> None:
    bundle_path, keys_path = crl_bundle_env(
        tmp_path,
        {"schema_version": 1, "revoked_bundles": [], "revoked_key_ids": [KEY_ID]},
    )
    assert_refused(resolve_fake(bundle_path, keys_path), BUNDLE_REVOKED, "bundle_revoked")


def test_declared_but_unreadable_crl_fails_closed(tmp_path: Path) -> None:
    missing_crl = crl_bundle_env(tmp_path, None)  # CRL file never written
    assert_refused(resolve_fake(*missing_crl), BUNDLE_REVOKED, "bundle_revoked")
    malformed = crl_bundle_env(tmp_path, "{not json")
    assert_refused(resolve_fake(*malformed), BUNDLE_REVOKED, "bundle_revoked")


def test_clean_crl_and_no_revocation_member_verify(tmp_path: Path) -> None:
    clean = crl_bundle_env(
        tmp_path, {"schema_version": 1, "revoked_bundles": [], "revoked_key_ids": []}
    )
    assert isinstance(resolve_fake(*clean), ActiveProfile)
    no_member = fake_env(tmp_path)  # base bundle has no revocation member
    assert isinstance(resolve_fake(no_member[0], no_member[1]), ActiveProfile)


def test_relative_crl_path_is_a_load_error(tmp_path: Path) -> None:
    def add_relative(document: dict) -> None:
        document["revocation"] = {"crl_path": "relative/crl.json"}

    bundle_path, keys_path, _ = fake_env(tmp_path, mutate=add_relative)
    assert_refused(resolve_fake(bundle_path, keys_path), PROFILE_INVALID, "profile_invalid")


# ---------------------------------------------------------------------------
# -32018 bundle_audience_mismatch (audience intersection, namespace ceiling).


def test_audience_mismatch_and_no_local_identifiers_refused(tmp_path: Path) -> None:
    bundle_path, keys_path, _ = fake_env(tmp_path)
    mismatch = resolve_fake(bundle_path, keys_path, audience_ids=["team:other"])
    failure = assert_refused(mismatch, BUNDLE_AUDIENCE_MISMATCH, "bundle_audience_mismatch")
    assert "team:test" in failure.message and "team:other" in failure.message, (
        "the refusal names both sides of the mismatch"
    )
    none_presented = resolve_fake(bundle_path, keys_path, audience_ids=[])
    assert_refused(none_presented, BUNDLE_AUDIENCE_MISMATCH, "bundle_audience_mismatch")


def test_audience_env_var_fallback_and_flag_precedence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert local_audience_ids(["team:a"], env_value="team:b") == ["team:a"], "flag wins over env"
    assert local_audience_ids([], env_value=" team:b , host:c ") == ["team:b", "host:c"]
    bundle_path, keys_path, _ = fake_env(tmp_path)
    monkeypatch.setenv(AUDIENCE_ENV_VAR, "host:ci")
    from_env = resolve_fake(bundle_path, keys_path, audience_ids=None)
    assert isinstance(from_env, ActiveProfile)
    flag_beats_env = resolve_fake(bundle_path, keys_path, audience_ids=["team:wrong"])
    assert_refused(flag_beats_env, BUNDLE_AUDIENCE_MISMATCH, "bundle_audience_mismatch")


def test_profile_rule_outside_namespace_ceiling_refused(tmp_path: Path) -> None:
    def reach_outside(document: dict) -> None:
        document["profiles"]["dev"]["visible"] = ["fake.*", "payments.charge"]

    bundle_path, keys_path, _ = fake_env(tmp_path, mutate=reach_outside)
    failure = assert_refused(
        resolve_fake(bundle_path, keys_path), BUNDLE_AUDIENCE_MISMATCH, "bundle_audience_mismatch"
    )
    assert "allowed_upstream_namespaces" in failure.message


# ---------------------------------------------------------------------------
# -32014 profile_invalid (malformed bundles; self-contained extends).


def test_malformed_bundles_are_profile_invalid(tmp_path: Path) -> None:
    def key_id_mismatch(document: dict) -> None:
        document["issuer"]["key_id"] = "someone-else"

    def inverted_window(document: dict) -> None:
        document["issued_at"], document["expires_at"] = (
            document["expires_at"],
            document["issued_at"],
        )

    def unknown_key(document: dict) -> None:
        document["surprise"] = True

    def loose_timestamp(document: dict) -> None:
        document["expires_at"] = "2026-09-01T00:00:00+00:00"

    for label, mutate in {
        "signature.key_id != issuer.key_id": key_id_mismatch,
        "issued_at >= expires_at": inverted_window,
        "unknown top-level key": unknown_key,
        "non-Z timestamp": loose_timestamp,
    }.items():
        bundle_path, keys_path, _ = fake_env(tmp_path, tamper=mutate)
        state = resolve_fake(bundle_path, keys_path)
        assert isinstance(state, BundleFailClosed), label
        assert state.code == PROFILE_INVALID, label
        assert "profile_invalid" in state.message, label


def test_unreadable_and_non_json_bundle_files(tmp_path: Path) -> None:
    keys_path = write_json(tmp_path / "keys.json", trusted_keys_doc([(KEY_ID, FAKE_PUBLIC, None)]))
    missing = resolve_fake(tmp_path / "no-such-bundle.json", keys_path)
    assert_refused(missing, PROFILE_INVALID, "profile_invalid")
    garbage = tmp_path / "garbage.json"
    garbage.write_text("{not json", encoding="utf-8")
    assert_refused(resolve_fake(garbage, keys_path), PROFILE_INVALID, "profile_invalid")


def test_signed_child_extending_unsigned_parent_is_unrepresentable(tmp_path: Path) -> None:
    """Bundles are self-contained (decision 9): 'extends' resolves only
    inside the bundle's own map, so a child naming an unsigned local profile
    is simply a dangling parent -> -32014, before any selection."""

    def extend_outside(document: dict) -> None:
        document["profiles"]["reviewer"]["extends"] = "unsigned-local-parent"

    bundle_path, keys_path, _ = fake_env(tmp_path, mutate=extend_outside)
    failure = assert_refused(resolve_fake(bundle_path, keys_path), PROFILE_INVALID, "profile_invalid")
    assert "unsigned-local-parent" in failure.message


# ---------------------------------------------------------------------------
# Verification ORDER: the first failing step wins.


def test_verification_order_first_failing_step_wins(tmp_path: Path) -> None:
    expired_now = _parse_timestamp("2026-12-01T00:00:00Z")

    # Tampered AND expired: signature (step 4) beats window (step 5).
    def widen(document: dict) -> None:
        document["audience"].append("org:everyone")

    bundle_path, keys_path, _ = fake_env(tmp_path, tamper=widen)
    state = resolve_fake(bundle_path, keys_path, now=expired_now)
    assert_refused(state, BUNDLE_SIGNATURE_INVALID, "bundle_signature_invalid")

    # Expired AND revoked: window (step 5) beats revocation (step 6).
    revoked_bundle, revoked_keys = crl_bundle_env(
        tmp_path, {"schema_version": 1, "revoked_bundles": [], "revoked_key_ids": [KEY_ID]}
    )
    state = resolve_fake(revoked_bundle, revoked_keys, now=expired_now)
    assert_refused(state, BUNDLE_EXPIRED, "bundle_expired")

    # Revoked AND audience-mismatched: revocation (step 6) beats audience (step 7).
    state = resolve_fake(revoked_bundle, revoked_keys, audience_ids=["team:other"])
    assert_refused(state, BUNDLE_REVOKED, "bundle_revoked")

    # Audience mismatch AND ceiling violation: step 7 beats step 8.
    def reach_outside(document: dict) -> None:
        document["profiles"]["dev"]["visible"] = ["fake.*", "payments.charge"]

    bundle_path, keys_path, _ = fake_env(tmp_path, mutate=reach_outside)
    state = resolve_fake(bundle_path, keys_path, audience_ids=["team:other"])
    failure = assert_refused(state, BUNDLE_AUDIENCE_MISMATCH, "bundle_audience_mismatch")
    assert "does not intersect" in failure.message, "step 7 (audience), not step 8 (ceiling)"

    # Unknown key (step 3) beats a bad signature (step 4).
    bundle_path, _, _ = fake_env(tmp_path, tamper=widen)
    other_keys = write_json(
        tmp_path / "unrelated-keys.json", trusted_keys_doc([("unrelated", FAKE_PUBLIC, None)])
    )
    state = resolve_fake(bundle_path, other_keys, now=expired_now)
    assert_refused(state, BUNDLE_KEY_MISSING, "bundle_key_missing")


# ---------------------------------------------------------------------------
# Signed-required policy and CLI profile-state resolution.


def gateway_args(**overrides) -> Namespace:
    base = {
        "profiles": "",
        "profile": "",
        "profile_bundle": "",
        "trusted_keys": "",
        "audience_id": None,
        "require_signed_profiles": False,
    }
    base.update(overrides)
    return Namespace(**base)


def test_require_signed_refuses_raw_profiles_path(tmp_path: Path) -> None:
    raw_path = write_json(
        tmp_path / "raw.json",
        {"schema_version": 1, "default_profile": "dev", "profiles": {"dev": {"visible": ["fake.*"]}}},
    )
    state, note = _resolve_gateway_profile_state(
        gateway_args(profiles=str(raw_path), require_signed_profiles=True)
    )
    failure = assert_refused(state, BUNDLE_SIGNATURE_INVALID, "bundle_signature_invalid")
    assert failure.source == "raw_file"
    assert "FAIL-CLOSED" in note


def test_require_signed_with_no_profile_source_refuses(tmp_path: Path) -> None:
    state, note = _resolve_gateway_profile_state(gateway_args(require_signed_profiles=True))
    assert_refused(state, BUNDLE_SIGNATURE_INVALID, "bundle_signature_invalid")
    assert "FAIL-CLOSED" in note


def test_raw_profiles_path_unchanged_without_require_signed(tmp_path: Path) -> None:
    raw_path = write_json(
        tmp_path / "raw.json",
        {"schema_version": 1, "default_profile": "dev", "profiles": {"dev": {"visible": ["fake.*"]}}},
    )
    state, note = _resolve_gateway_profile_state(gateway_args(profiles=str(raw_path)))
    assert isinstance(state, ActiveProfile) and state.name == "dev"
    assert state.provenance is None, "the raw path never grows bundle provenance"
    assert note == "tool profile 'dev' enforced"
    open_state, open_note = _resolve_gateway_profile_state(gateway_args())
    assert open_state is None and open_note == "no tool profiles (open mode)"


def test_bundle_flags_without_bundle_are_config_errors(tmp_path: Path) -> None:
    with pytest.raises(GatewayConfigError):
        _resolve_gateway_profile_state(gateway_args(trusted_keys=str(tmp_path / "keys.json")))
    with pytest.raises(GatewayConfigError):
        _resolve_gateway_profile_state(gateway_args(audience_id=["team:test"]))
    with pytest.raises(GatewayConfigError):
        _resolve_gateway_profile_state(gateway_args(profile="dev"))


@requires_ed25519
def test_cli_resolution_with_bundle_and_require_signed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """--require-signed-profiles alongside a verifiable bundle stays legal;
    the bundle's validity window covers the real clock here by fixture."""
    monkeypatch.delenv("UNLIMITED_SKILLS_MCP_PROFILE", raising=False)
    monkeypatch.delenv(AUDIENCE_ENV_VAR, raising=False)
    import time

    def long_window(document: dict) -> None:
        document["issued_at"] = "2020-01-01T00:00:00Z"
        document["expires_at"] = "2099-01-01T00:00:00Z"

    bundle_path, keys_path, _ = real_env(tmp_path, mutate=long_window)
    state, note = _resolve_gateway_profile_state(
        gateway_args(
            profile_bundle=str(bundle_path),
            trusted_keys=str(keys_path),
            audience_id=["team:test"],
            require_signed_profiles=True,
        )
    )
    assert isinstance(state, ActiveProfile) and state.name == "dev"
    assert "signed bundle profile 'dev' enforced" in note
    assert time.time() < _parse_timestamp("2099-01-01T00:00:00Z")


# ---------------------------------------------------------------------------
# Local override: narrow-only intersection with --profiles (decision 4).


def local_file(tmp_path: Path, profiles: dict, default: str | None = None) -> Path:
    document: dict = {"schema_version": 1, "profiles": profiles}
    if default is not None:
        document["default_profile"] = default
    return write_json(tmp_path / "local-profiles.json", document)


def test_local_file_narrows_bundle(tmp_path: Path) -> None:
    bundle_path, keys_path, _ = fake_env(tmp_path)
    local = local_file(tmp_path, {"dev": {"visible": ["fake.*"], "callable": ["fake.echo"]}})
    state = resolve_fake(bundle_path, keys_path, local_profiles_path=local)
    assert isinstance(state, ActiveProfile)
    assert state.is_visible("fake", "echo") and state.is_callable("fake", "echo")
    assert state.is_visible("fake", "add") and not state.is_callable("fake", "add")
    assert not state.is_visible("other", "shred"), "the local file hid the 'other' upstream"
    assert state.provenance.local_profile_sha256, "intersection pins the local file hash too"


def test_local_file_can_never_widen_bundle(tmp_path: Path) -> None:
    bundle_path, keys_path, _ = fake_env(tmp_path)
    wide_local = local_file(
        tmp_path,
        {
            "reviewer": {
                "visible": ["fake.*", "other.*", "extra.*"],
                "callable": ["fake.*", "other.*", "extra.*"],
            }
        },
    )
    merged = resolve_fake(
        bundle_path, keys_path, cli_name="reviewer", local_profiles_path=wide_local
    )
    alone = resolve_fake(bundle_path, keys_path, cli_name="reviewer")
    assert isinstance(merged, ActiveProfile) and isinstance(alone, ActiveProfile)
    for upstream, tool in (*TOOL_MATRIX, ("extra", "anything")):
        assert merged.is_visible(upstream, tool) == alone.is_visible(upstream, tool), (upstream, tool)
        assert merged.is_callable(upstream, tool) == alone.is_callable(upstream, tool), (upstream, tool)


def test_local_empty_profile_denies_everything(tmp_path: Path) -> None:
    """A local selected profile that declares NO rule fields is E09 default
    deny -- the intersection denies everything rather than passing the
    bundle through."""
    bundle_path, keys_path, _ = fake_env(tmp_path)
    local = local_file(tmp_path, {"dev": {}})
    state = resolve_fake(bundle_path, keys_path, local_profiles_path=local)
    assert isinstance(state, ActiveProfile)
    for upstream, tool in TOOL_MATRIX:
        assert not state.is_visible(upstream, tool)
        assert not state.is_callable(upstream, tool)


def test_local_default_profile_is_ignored_selection_owned_by_bundle(tmp_path: Path) -> None:
    bundle_path, keys_path, _ = fake_env(tmp_path)
    # The local file's default says 'wide'; the bundle's default 'dev' wins.
    local = local_file(
        tmp_path,
        {"dev": {"visible": ["fake.echo"], "callable": ["fake.echo"]}, "wide": {"visible": ["fake.*"]}},
        default="wide",
    )
    state = resolve_fake(bundle_path, keys_path, local_profiles_path=local)
    assert isinstance(state, ActiveProfile) and state.name == "dev"
    assert state.is_visible("fake", "echo") and not state.is_visible("fake", "add")
    # A selection name missing from the local file is profile_not_found.
    missing = local_file(tmp_path, {"unrelated": {"visible": ["fake.*"]}})
    state = resolve_fake(bundle_path, keys_path, local_profiles_path=missing)
    assert isinstance(state, BundleFailClosed) and state.code == PROFILE_NOT_FOUND


def test_invalid_local_file_alongside_bundle_fails_closed(tmp_path: Path) -> None:
    bundle_path, keys_path, _ = fake_env(tmp_path)
    bad_local = tmp_path / "bad-local.json"
    bad_local.write_text("{not json", encoding="utf-8")
    state = resolve_fake(bundle_path, keys_path, local_profiles_path=bad_local)
    assert_refused(state, PROFILE_INVALID, "profile_invalid")


# ---------------------------------------------------------------------------
# Audit provenance: profile_loaded rows, refuse-all coverage, no leaks.


@requires_ed25519
def test_profile_loaded_row_carries_bundle_provenance_without_leaks(tmp_path: Path) -> None:
    bundle_path, keys_path, document = real_env(tmp_path)
    state = resolve(bundle_path, keys_path)
    audit_path = tmp_path / "audit.jsonl"
    gateway = Gateway(GATEWAY_CONFIG, AuditLog(audit_path), profile=state)
    registry = build_gateway_registry(gateway)
    try:
        registry["tools_search"]["handler"]({"query": "echo text"})
    finally:
        gateway.shutdown()
    rows = audit_rows(audit_path)
    loaded = rows[0]
    assert loaded["tool"] == "profile_loaded" and loaded["ok"] is True
    assert loaded["profile"] == "dev"
    assert loaded["profile_source"] == "signed_bundle"
    assert loaded["bundle_sha256"] == hashlib.sha256(bundle_path.read_bytes()).hexdigest()
    assert loaded["profile_sha256"] == loaded["bundle_sha256"]
    assert loaded["issuer_key_id"] == KEY_ID
    assert loaded["issuer_display"] == "Test platform team"
    assert loaded["audience"] == ["team:test", "host:ci"]
    assert loaded["expires_at"] == "2026-09-01T00:00:00Z"
    assert loaded["verification"] == "verified"
    assert all(row.get("profile") == "dev" for row in rows)
    # Leak grep: neither the signature value nor the public key (nor any
    # other key material) may ever appear in the audit log.
    audit_text = audit_path.read_text(encoding="utf-8")
    assert document["signature"]["value"] not in audit_text
    trusted_doc = json.loads(keys_path.read_text(encoding="utf-8"))
    assert trusted_doc["keys"][0]["public_key"] not in audit_text


def test_failed_verification_audits_stage_and_refuses_all_meta_tools(tmp_path: Path) -> None:
    bundle_path, keys_path, _ = fake_env(tmp_path)
    state = resolve_fake(bundle_path, keys_path, now=_parse_timestamp("2026-12-01T00:00:00Z"))
    assert isinstance(state, BundleFailClosed) and state.code == BUNDLE_EXPIRED
    audit_path = tmp_path / "audit.jsonl"
    gateway = Gateway(GATEWAY_CONFIG, AuditLog(audit_path), profile=state)
    registry = build_gateway_registry(gateway)
    try:
        for meta_tool, arguments in (
            ("tools_search", {"query": "echo"}),
            ("tools_schema", {"tool": "fake.echo"}),
            ("tools_call", {"tool": "fake.echo", "arguments": {}}),
        ):
            with pytest.raises(UpstreamError) as excinfo:
                registry[meta_tool]["handler"](arguments)
            assert excinfo.value.code == BUNDLE_EXPIRED, meta_tool
            assert "bundle_expired" in str(excinfo.value)
    finally:
        gateway.shutdown()
    rows = audit_rows(audit_path)
    loaded = rows[0]
    assert loaded["tool"] == "profile_loaded" and loaded["ok"] is False
    assert loaded["profile_source"] == "signed_bundle"
    assert loaded["bundle_sha256"] == hashlib.sha256(bundle_path.read_bytes()).hexdigest()
    assert "bundle_expired" in loaded["error"], "the failing step's code is named"
    refusals = [row for row in rows[1:]]
    assert len(refusals) == 3
    assert all(row["ok"] is False and "bundle_expired" in row["error"] for row in refusals)


def test_raw_profile_loaded_row_marks_raw_file_source(tmp_path: Path) -> None:
    raw_path = write_json(
        tmp_path / "raw.json",
        {"schema_version": 1, "default_profile": "dev", "profiles": {"dev": {"visible": ["fake.*"]}}},
    )
    state = resolve_profile_state(raw_path, cli_name="", env_name="")
    audit_path = tmp_path / "audit.jsonl"
    gateway = Gateway(GATEWAY_CONFIG, AuditLog(audit_path), profile=state)
    gateway.shutdown()
    loaded = audit_rows(audit_path)[0]
    assert loaded["tool"] == "profile_loaded" and loaded["ok"] is True
    assert loaded["profile_source"] == "raw_file"
    assert "bundle_sha256" not in loaded and "issuer_key_id" not in loaded


def test_unsigned_refusal_helper_is_minus_32015(tmp_path: Path) -> None:
    refusal = require_signed_refusal("unsigned source", requested="dev")
    assert refusal.code == BUNDLE_SIGNATURE_INVALID
    assert refusal.requested == "dev" and refusal.source == "raw_file"
    assert "bundle_signature_invalid" in refusal.message


@requires_ed25519
def test_default_backend_is_real_ed25519_when_available() -> None:
    backend = default_signature_backend()
    assert backend is not None and backend.name == "cryptography-ed25519"
    private, public = ed25519_keypair()
    message = b"unlimited-skills bundle verification"
    assert backend.verify(public, message, private.sign(message))
    assert not backend.verify(public, message + b"!", private.sign(message))
    assert not backend.verify(public, message, b"\x00" * 64)
