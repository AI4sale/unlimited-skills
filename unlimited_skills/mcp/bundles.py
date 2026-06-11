"""Signed MCP profile bundle verification (E13 design, E14 prototype).

Implements the 10-step verification algorithm of
docs/mcp-signed-profile-bundles.md: a bundle (one local JSON file,
schemas/mcp-profile-bundle.schema.json) wraps the E09 profile map with an
issuer, a mandatory non-empty audience, a mandatory validity window, an
upstream-namespace ceiling, an optional local-CRL revocation pointer, and a
mandatory detached Ed25519 signature over the canonical JSON of the document
minus its ``signature`` member.

Every verification failure is **fail-closed refuse-all** with a reserved
code (``-32015``..``-32019``), never a fallback to unsigned or open
behavior; malformed bundle documents reuse ``-32014`` ``profile_invalid``
and selection failures inside a verified bundle reuse ``-32013``
``profile_not_found`` (the design's "Refusal codes" section).

Signature verification is a pluggable :class:`SignatureBackend`. The default
backend uses the optional ``cryptography`` package (real Ed25519); when no
backend is available, a configured bundle refuses with ``-32019``
``bundle_key_missing`` -- "cannot verify" never silently becomes "trusted"
(design decision 8). Trust is one local trusted-keys file (no PKI, no
network fetch); rotation is multiple active keys selected by ``key_id``.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import re
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence

from .profiles import (
    KEY_ID_RE,
    MAX_KEY_ID_LENGTH,
    PROFILE_ENV_VAR,
    PROFILE_INVALID,
    PROFILE_NAME_RE,
    PROFILE_NOT_FOUND,
    RULE_RE,
    ActiveProfile,
    FailClosedProfile,
    ProfileLoadError,
    RuleSet,
    _profiles_map_shape_errors,
    _resolve_active,
    _rule_covered,
    _semantic_errors,
    _signature_errors,
    load_profile_document,
    select_profile_name,
)

# Bundle refusal codes, contiguous with the implemented -32001..-32014 family
# (re-exported by unlimited_skills.mcp.gateway). Reserved by the E13 design;
# never reused for anything else.
BUNDLE_SIGNATURE_INVALID = -32015  # signature does not verify / absent under policy / no backend
BUNDLE_EXPIRED = -32016  # outside the signed validity window (expired OR not yet valid)
BUNDLE_REVOKED = -32017  # bundle SHA-256 or key_id listed in the CRL, or declared CRL unreadable
BUNDLE_AUDIENCE_MISMATCH = -32018  # audience intersection empty, or rule outside the namespace ceiling
BUNDLE_KEY_MISSING = -32019  # signing key not present and valid locally; verification not attempted

AUDIENCE_ENV_VAR = "UNLIMITED_SKILLS_MCP_AUDIENCE"
CLOCK_SKEW_SECONDS = 300  # fixed tolerance for the validity window (design step 5)

MAX_AUDIENCE = 32
MAX_NAMESPACES = 64
MAX_DISPLAY_LENGTH = 128
MAX_CRL_PATH_LENGTH = 512

AUDIENCE_RE = re.compile(r"^(team|org|host):[A-Za-z0-9][A-Za-z0-9_.-]*$")
TIMESTAMP_RE = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$")

_BUNDLE_KEYS = frozenset(
    {
        "bundle_version",
        "comment",
        "issuer",
        "audience",
        "issued_at",
        "expires_at",
        "allowed_upstream_namespaces",
        "default_profile",
        "profiles",
        "revocation",
        "signature",
    }
)
_BUNDLE_REQUIRED = (
    "bundle_version",
    "issuer",
    "audience",
    "issued_at",
    "expires_at",
    "allowed_upstream_namespaces",
    "profiles",
    "signature",
)
_ISSUER_KEYS = frozenset({"comment", "key_id", "display"})
_REVOCATION_KEYS = frozenset({"comment", "crl_path", "registry_endpoint"})
_TRUSTED_KEYS_TOP = frozenset({"schema_version", "comment", "keys"})
_TRUSTED_KEY_KEYS = frozenset({"key_id", "algorithm", "public_key", "not_after", "comment"})
_CRL_KEYS = frozenset({"schema_version", "comment", "revoked_bundles", "revoked_key_ids"})

ED25519_PUBLIC_KEY_BYTES = 32


# ---------------------------------------------------------------------------
# Pluggable signature backend (design "Verifier backend decision").


class SignatureBackend:
    """Interface for detached-signature verification.

    ``verify`` returns True only when ``signature`` is a valid signature of
    ``message`` under ``public_key``. It must never raise on a merely
    invalid signature -- only return False. A missing backend (``None``
    where one is required) is the fail-closed ``bundle_key_missing`` state,
    never a silent pass.
    """

    name = "abstract"

    def verify(self, public_key: bytes, message: bytes, signature: bytes) -> bool:
        raise NotImplementedError


class CryptographyEd25519Backend(SignatureBackend):
    """Real Ed25519 verification via the optional ``cryptography`` package."""

    name = "cryptography-ed25519"

    def verify(self, public_key: bytes, message: bytes, signature: bytes) -> bool:
        from cryptography.exceptions import InvalidSignature
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

        try:
            Ed25519PublicKey.from_public_bytes(public_key).verify(signature, message)
        except (InvalidSignature, ValueError):
            return False
        return True


def default_signature_backend() -> SignatureBackend | None:
    """The default backend, or ``None`` when no crypto library is available.

    ``None`` with a bundle configured is ``bundle_key_missing`` (-32019)
    fail-closed -- there is no fallback to unsigned (design decision 8).
    """
    try:
        from cryptography.hazmat.primitives.asymmetric import ed25519  # noqa: F401
    except Exception:  # pragma: no cover - exercised only without cryptography
        return None
    return CryptographyEd25519Backend()


_DEFAULT_BACKEND = object()  # sentinel: "use default_signature_backend()"


# ---------------------------------------------------------------------------
# Canonicalization (design "Canonicalization and what is signed").


def canonical_bundle_bytes(document: dict) -> bytes:
    """Canonical JSON of the bundle minus ``signature``: UTF-8, sorted keys,
    no insignificant whitespace -- the normative signing input."""
    unsigned = {key: value for key, value in document.items() if key != "signature"}
    return json.dumps(unsigned, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode(
        "utf-8"
    )


# ---------------------------------------------------------------------------
# Provenance and fail-closed state.


@dataclass(frozen=True)
class BundleProvenance:
    """Non-sensitive bundle provenance for the ``profile_loaded`` audit row.

    Key ids, hashes, audience identifiers, and timestamps only (bounded
    charsets) -- never key material, signature values, or bundle content.
    """

    bundle_sha256: str
    issuer_key_id: str
    issuer_display: str
    audience: tuple[str, ...]
    expires_at: str
    local_profile_sha256: str = ""

    def audit_fields(self) -> dict[str, object]:
        fields: dict[str, object] = {
            "profile_source": "signed_bundle",
            "bundle_sha256": self.bundle_sha256,
            "issuer_key_id": self.issuer_key_id,
            "issuer_display": self.issuer_display[:MAX_DISPLAY_LENGTH],
            "audience": list(self.audience),
            "expires_at": self.expires_at,
            "verification": "verified",
        }
        if self.local_profile_sha256:
            fields["local_profile_sha256"] = self.local_profile_sha256
        return fields


@dataclass(frozen=True)
class BundleFailClosed(FailClosedProfile):
    """Fail-closed refuse-all caused by bundle verification or policy.

    Identical gateway semantics to :class:`FailClosedProfile` (the meta-tools
    are served, every call refused with ``code``); additionally carries the
    bundle file SHA-256 when computable, so the startup audit row can name
    the failing artifact without embedding any of its content. ``source`` is
    the refused profile source type for that row: ``signed_bundle`` for a
    failed bundle verification, ``raw_file`` when the signed-required policy
    refuses an unsigned profile source.
    """

    bundle_sha256: str = ""
    source: str = "signed_bundle"


def _fail(
    code: int, name: str, detail: str, requested: str, sha256: str = ""
) -> BundleFailClosed:
    return BundleFailClosed(
        code=code,
        message=(
            f"Signed profile bundle refused ({name}): {detail}; every call is "
            "refused. Restart the gateway after fixing the bundle, keys, or flags."
        ),
        requested=requested,
        bundle_sha256=sha256,
    )


def require_signed_refusal(detail: str, requested: str = "") -> BundleFailClosed:
    """The signed-required policy refusal for unsigned profile sources.

    Decision 6: an absent signature under ``--require-signed-profiles`` is
    the same ``-32015`` as a corrupted one -- stripping gains nothing over
    tampering.
    """
    refusal = _fail(BUNDLE_SIGNATURE_INVALID, "bundle_signature_invalid", detail, requested)
    return replace(refusal, source="raw_file")


# ---------------------------------------------------------------------------
# Trusted-keys file (design "Trust and keys"; v1: one local file, no PKI).


class TrustedKeysError(ValueError):
    """The trusted-keys file is missing, unreadable, or malformed.

    Always maps to ``bundle_key_missing`` (-32019): a key that cannot be
    found and validated is a key that is missing.
    """


@dataclass(frozen=True)
class TrustedKey:
    key_id: str
    public_key: bytes
    not_after: float | None  # epoch seconds; per-key local trust deadline


def _parse_timestamp(value: str) -> float:
    """RFC 3339 UTC ('Z' only) to epoch seconds; format pre-validated."""
    parsed = datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    return parsed.timestamp()


def load_trusted_keys(path: Path) -> dict[str, TrustedKey]:
    """Load the local trusted-keys file: ``key_id`` -> :class:`TrustedKey`.

    Multiple active keys ARE the rotation mechanism (overlap window selected
    by the signature's ``key_id``). Public keys only -- never private
    material. Any structural problem is :class:`TrustedKeysError`.
    """
    path = Path(path)
    try:
        raw = path.read_bytes()
    except OSError:
        raise TrustedKeysError("trusted-keys file is missing or unreadable") from None
    try:
        document = json.loads(raw.decode("utf-8-sig", errors="replace"))
    except json.JSONDecodeError:
        raise TrustedKeysError("trusted-keys file is not valid JSON") from None
    if not isinstance(document, dict) or document.get("schema_version") != 1:
        raise TrustedKeysError("trusted-keys file must be an object with schema_version 1")
    for key in document:
        if key not in _TRUSTED_KEYS_TOP:
            raise TrustedKeysError(f"trusted-keys file: unknown key {key!r}")
    entries = document.get("keys")
    if not isinstance(entries, list) or not entries:
        raise TrustedKeysError("trusted-keys file must list at least one key")
    keys: dict[str, TrustedKey] = {}
    for index, entry in enumerate(entries):
        label = f"keys[{index}]"
        if not isinstance(entry, dict):
            raise TrustedKeysError(f"{label} must be an object")
        for key in entry:
            if key not in _TRUSTED_KEY_KEYS:
                raise TrustedKeysError(f"{label}: unknown key {key!r}")
        key_id = entry.get("key_id")
        if (
            not isinstance(key_id, str)
            or not 1 <= len(key_id) <= MAX_KEY_ID_LENGTH
            or not KEY_ID_RE.match(key_id)
        ):
            raise TrustedKeysError(f"{label}.key_id must be a bounded opaque identifier")
        if key_id in keys:
            raise TrustedKeysError(f"duplicate key_id {key_id!r}")
        if entry.get("algorithm") != "ed25519":
            raise TrustedKeysError(f"{label}.algorithm must be 'ed25519'")
        public_b64 = entry.get("public_key")
        if not isinstance(public_b64, str):
            raise TrustedKeysError(f"{label}.public_key must be a base64 string")
        try:
            public_key = base64.b64decode(public_b64, validate=True)
        except (ValueError, TypeError):
            raise TrustedKeysError(f"{label}.public_key is not valid base64") from None
        if len(public_key) != ED25519_PUBLIC_KEY_BYTES:
            raise TrustedKeysError(
                f"{label}.public_key must be a raw {ED25519_PUBLIC_KEY_BYTES}-byte Ed25519 key"
            )
        not_after: float | None = None
        if "not_after" in entry:
            value = entry["not_after"]
            if not isinstance(value, str) or not TIMESTAMP_RE.match(value):
                raise TrustedKeysError(f"{label}.not_after must be an RFC 3339 UTC timestamp")
            not_after = _parse_timestamp(value)
        keys[key_id] = TrustedKey(key_id=key_id, public_key=public_key, not_after=not_after)
    return keys


# ---------------------------------------------------------------------------
# Local CRL file (design "Revocation (v1: local CRL file)").


class CrlError(ValueError):
    """The declared CRL cannot be read or parsed: fail-closed ``bundle_revoked``
    -- "cannot prove not-revoked" never degrades to "trusted" (threat 18)."""


def _load_crl(path: Path) -> tuple[frozenset[str], frozenset[str]]:
    """(revoked bundle SHA-256s lowercased, revoked key ids)."""
    try:
        raw = Path(path).read_bytes()
    except OSError:
        raise CrlError("declared CRL file is missing or unreadable") from None
    try:
        document = json.loads(raw.decode("utf-8-sig", errors="replace"))
    except json.JSONDecodeError:
        raise CrlError("declared CRL file is not valid JSON") from None
    if not isinstance(document, dict) or document.get("schema_version") != 1:
        raise CrlError("CRL must be an object with schema_version 1")
    for key in document:
        if key not in _CRL_KEYS:
            raise CrlError(f"CRL: unknown key {key!r}")
    hashes: set[str] = set()
    key_ids: set[str] = set()
    for field, target in (("revoked_bundles", hashes), ("revoked_key_ids", key_ids)):
        values = document.get(field, [])
        if not isinstance(values, list) or not all(isinstance(item, str) for item in values):
            raise CrlError(f"CRL.{field} must be a list of strings")
        target.update(item.lower() if field == "revoked_bundles" else item for item in values)
    return frozenset(hashes), frozenset(key_ids)


# ---------------------------------------------------------------------------
# Bundle shape and static checks (verification step 2; strict, bounded,
# allocation-light -- the same hardened-parser stance as profiles.py).


def _bundle_shape_errors(document: object) -> list[str]:
    if not isinstance(document, dict):
        return ["bundle must be a JSON object"]
    errors: list[str] = []
    for key in document:
        if key not in _BUNDLE_KEYS:
            errors.append(f"unknown key {key!r}")
    for key in _BUNDLE_REQUIRED:
        if key not in document:
            errors.append(f"missing required {key!r}")
    if "bundle_version" in document and document["bundle_version"] != 1:
        errors.append("bundle_version must be the constant 1")
    if "comment" in document and not isinstance(document["comment"], str):
        errors.append("comment must be a string")
    errors.extend(_issuer_errors(document.get("issuer")))
    errors.extend(_audience_errors(document.get("audience")))
    for field in ("issued_at", "expires_at"):
        value = document.get(field)
        if value is not None and (not isinstance(value, str) or not TIMESTAMP_RE.match(value)):
            errors.append(f"{field} must be an RFC 3339 UTC timestamp ending in 'Z'")
    errors.extend(_namespace_errors(document.get("allowed_upstream_namespaces")))
    default = document.get("default_profile")
    if default is not None and (not isinstance(default, str) or not PROFILE_NAME_RE.match(default)):
        errors.append("default_profile must be a profile name")
    if "revocation" in document:
        errors.extend(_revocation_errors(document["revocation"]))
    if "profiles" in document:
        errors.extend(_profiles_map_shape_errors(document["profiles"]))
    if "signature" in document:
        errors.extend(_signature_errors(document["signature"]))
    if errors:
        return errors
    # Bundle-level static checks (only on a structurally sound document).
    if document["signature"].get("key_id") != document["issuer"].get("key_id"):
        errors.append("signature.key_id must equal issuer.key_id")
    if _parse_timestamp(document["issued_at"]) >= _parse_timestamp(document["expires_at"]):
        errors.append("issued_at must be strictly before expires_at")
    return errors


def _issuer_errors(issuer: object) -> list[str]:
    if issuer is None:
        return []
    if not isinstance(issuer, dict):
        return ["issuer must be an object"]
    errors: list[str] = []
    for key in issuer:
        if key not in _ISSUER_KEYS:
            errors.append(f"issuer: unknown key {key!r}")
    key_id = issuer.get("key_id")
    if (
        not isinstance(key_id, str)
        or not 1 <= len(key_id) <= MAX_KEY_ID_LENGTH
        or not KEY_ID_RE.match(key_id)
    ):
        errors.append("issuer.key_id must be a bounded opaque identifier")
    display = issuer.get("display")
    if not isinstance(display, str) or not 1 <= len(display) <= MAX_DISPLAY_LENGTH:
        errors.append("issuer.display must be a 1-128 char string")
    return errors


def _audience_errors(audience: object) -> list[str]:
    if audience is None:
        return []
    if not isinstance(audience, list):
        return ["audience must be an array of identifiers"]
    errors: list[str] = []
    if not 1 <= len(audience) <= MAX_AUDIENCE:
        errors.append(f"audience must contain between 1 and {MAX_AUDIENCE} identifiers")
    if len(set(map(str, audience))) != len(audience):
        errors.append("audience identifiers must be unique")
    for item in audience:
        if (
            not isinstance(item, str)
            or len(item) > MAX_DISPLAY_LENGTH
            or not AUDIENCE_RE.match(item)
        ):
            errors.append(f"audience identifier {item!r} must be 'team:'/'org:'/'host:' + name")
    return errors


def _namespace_errors(namespaces: object) -> list[str]:
    if namespaces is None:
        return []
    if not isinstance(namespaces, list):
        return ["allowed_upstream_namespaces must be an array of rules"]
    errors: list[str] = []
    if not 1 <= len(namespaces) <= MAX_NAMESPACES:
        errors.append(
            f"allowed_upstream_namespaces must contain between 1 and {MAX_NAMESPACES} rules"
        )
    if len(set(map(str, namespaces))) != len(namespaces):
        errors.append("allowed_upstream_namespaces rules must be unique")
    for rule in namespaces:
        if not isinstance(rule, str) or not RULE_RE.match(rule):
            errors.append(
                f"allowed_upstream_namespaces rule {rule!r} is not "
                "'<upstream>.<tool>' or '<upstream>.*'"
            )
    return errors


def _revocation_errors(revocation: object) -> list[str]:
    if not isinstance(revocation, dict):
        return ["revocation must be an object"]
    errors: list[str] = []
    for key in revocation:
        if key not in _REVOCATION_KEYS:
            errors.append(f"revocation: unknown key {key!r}")
    crl_path = revocation.get("crl_path")
    if crl_path is not None:
        if not isinstance(crl_path, str) or not 1 <= len(crl_path) <= MAX_CRL_PATH_LENGTH:
            errors.append("revocation.crl_path must be a 1-512 char path string")
        elif not os.path.isabs(os.path.expanduser(crl_path)):
            errors.append("revocation.crl_path must be absolute after '~' expansion")
    endpoint = revocation.get("registry_endpoint")
    if endpoint is not None and (
        not isinstance(endpoint, str)
        or not endpoint.startswith("https://")
        or len(endpoint) > MAX_CRL_PATH_LENGTH
    ):
        errors.append("revocation.registry_endpoint must be an https:// URL (never fetched in v1)")
    return errors


def _format_errors(errors: list[str]) -> str:
    shown = "; ".join(errors[:3])
    if len(errors) > 3:
        shown += f"; and {len(errors) - 3} more"
    return shown


# ---------------------------------------------------------------------------
# Local audience identifiers (verification step 7).


def local_audience_ids(flag_ids: Sequence[str] | None, env_value: str | None = None) -> list[str]:
    """The consumer's own identifiers: repeatable ``--audience-id`` flags win
    over the comma-separated ``UNLIMITED_SKILLS_MCP_AUDIENCE`` env var
    (E09's explicitness order). ``env_value=None`` reads the real environment."""
    cleaned = [item.strip() for item in (flag_ids or []) if item and item.strip()]
    if cleaned:
        return cleaned
    if env_value is None:
        env_value = os.environ.get(AUDIENCE_ENV_VAR, "")
    return [item.strip() for item in env_value.split(",") if item.strip()]


# ---------------------------------------------------------------------------
# The verification algorithm (design "Verification algorithm", steps 1-10).


def resolve_bundle_state(
    bundle_path: Path,
    trusted_keys_path: Path | None = None,
    cli_name: str | None = None,
    env_name: str | None = None,
    audience_ids: Sequence[str] | None = None,
    local_profiles_path: Path | None = None,
    now: float | None = None,
    backend: object = _DEFAULT_BACKEND,
) -> ActiveProfile | BundleFailClosed:
    """Verify a signed profile bundle and resolve the active profile.

    Runs the design's 10 steps in order; the first failing step wins and
    yields a fail-closed refuse-all :class:`BundleFailClosed` -- never an
    exception, never open behavior, never unsigned fallback. On success the
    returned :class:`ActiveProfile` enforces exactly like a raw E10 profile
    and carries :class:`BundleProvenance` for the audit row.

    ``local_profiles_path`` is the ``narrow-only`` local override (design
    decision 4): the local unsigned file is intersected with the bundle's
    selected profile and can only ever narrow it. The single resolved
    selection name (``cli_name`` > env > the bundle's ``default_profile``;
    the local file's own ``default_profile`` is ignored -- exactly one
    artifact owns selection) must exist in BOTH artifacts.

    ``now`` (epoch seconds) and ``backend`` exist for tests: an injected
    clock and an injected :class:`SignatureBackend` (``None`` simulates the
    no-backend host).
    """
    import time as _time

    if env_name is None:
        env_name = os.environ.get(PROFILE_ENV_VAR, "")
    requested = select_profile_name(cli_name, env_name, None)
    if backend is _DEFAULT_BACKEND:
        backend = default_signature_backend()
    if now is None:
        now = _time.time()

    # Step 1: read the bundle file; compute the file SHA-256.
    try:
        raw = Path(bundle_path).read_bytes()
    except OSError:
        return _fail(
            PROFILE_INVALID,
            "profile_invalid",
            "bundle file is missing or unreadable",
            requested,
        )
    sha256 = hashlib.sha256(raw).hexdigest()

    # Step 2: parse and shape-check, plus the bundle-level static checks.
    try:
        document = json.loads(raw.decode("utf-8-sig", errors="replace"))
    except json.JSONDecodeError:
        return _fail(
            PROFILE_INVALID, "profile_invalid", "bundle file is not valid JSON", requested, sha256
        )
    errors = _bundle_shape_errors(document)
    if errors:
        return _fail(PROFILE_INVALID, "profile_invalid", _format_errors(errors), requested, sha256)
    key_id = document["signature"]["key_id"]

    # Step 3: look up the key in the trusted-keys file.
    if backend is None:
        return _fail(
            BUNDLE_KEY_MISSING,
            "bundle_key_missing",
            "no verifier backend available (install the optional 'cryptography' package)",
            requested,
            sha256,
        )
    if not isinstance(backend, SignatureBackend):
        return _fail(
            BUNDLE_KEY_MISSING,
            "bundle_key_missing",
            "no verifier backend available",
            requested,
            sha256,
        )
    if not trusted_keys_path:
        return _fail(
            BUNDLE_KEY_MISSING,
            "bundle_key_missing",
            "no trusted-keys file configured (--trusted-keys)",
            requested,
            sha256,
        )
    try:
        trusted = load_trusted_keys(Path(trusted_keys_path))
    except TrustedKeysError as exc:
        return _fail(BUNDLE_KEY_MISSING, "bundle_key_missing", str(exc), requested, sha256)
    key = trusted.get(key_id)
    if key is None:
        return _fail(
            BUNDLE_KEY_MISSING,
            "bundle_key_missing",
            f"signing key '{key_id}' is not in the trusted-keys file",
            requested,
            sha256,
        )
    if key.not_after is not None and now >= key.not_after:
        return _fail(
            BUNDLE_KEY_MISSING,
            "bundle_key_missing",
            f"signing key '{key_id}' is past its local not_after trust deadline",
            requested,
            sha256,
        )

    # Step 4: verify the Ed25519 signature over the canonical document.
    try:
        signature = base64.b64decode(document["signature"]["value"], validate=True)
    except (ValueError, TypeError):
        signature = b""
    if not signature or not backend.verify(key.public_key, canonical_bundle_bytes(document), signature):
        return _fail(
            BUNDLE_SIGNATURE_INVALID,
            "bundle_signature_invalid",
            "the bundle signature does not verify over the canonical document",
            requested,
            sha256,
        )
    # Only after this step is any field of the bundle trusted.

    # Step 5: check the signed validity window (+-300 s skew; one code for
    # expired AND not-yet-valid, design decision 7).
    issued_at = _parse_timestamp(document["issued_at"])
    expires_at = _parse_timestamp(document["expires_at"])
    if not (issued_at - CLOCK_SKEW_SECONDS <= now < expires_at + CLOCK_SKEW_SECONDS):
        return _fail(
            BUNDLE_EXPIRED,
            "bundle_expired",
            "the current time is outside the bundle's signed validity window "
            f"({document['issued_at']} .. {document['expires_at']})",
            requested,
            sha256,
        )

    # Step 6: check revocation (declared-but-unreadable CRL is fail-closed).
    revocation = document.get("revocation") or {}
    crl_path = revocation.get("crl_path")
    if crl_path:
        try:
            revoked_hashes, revoked_key_ids = _load_crl(Path(os.path.expanduser(crl_path)))
        except CrlError as exc:
            return _fail(BUNDLE_REVOKED, "bundle_revoked", str(exc), requested, sha256)
        if sha256.lower() in revoked_hashes:
            return _fail(
                BUNDLE_REVOKED,
                "bundle_revoked",
                "the bundle file SHA-256 is listed in the CRL",
                requested,
                sha256,
            )
        if key_id in revoked_key_ids:
            return _fail(
                BUNDLE_REVOKED,
                "bundle_revoked",
                f"signing key '{key_id}' is listed in the CRL",
                requested,
                sha256,
            )

    # Step 7: check the audience intersection.
    local_ids = local_audience_ids(audience_ids)
    bundle_audience = list(document["audience"])
    if not local_ids or not set(local_ids) & set(bundle_audience):
        return _fail(
            BUNDLE_AUDIENCE_MISMATCH,
            "bundle_audience_mismatch",
            f"bundle audience [{', '.join(bundle_audience)}] does not intersect "
            f"local identifiers [{', '.join(local_ids) or '<none>'}]",
            requested,
            sha256,
        )

    # Step 8: check the namespace ceiling (decision 10): every rule in every
    # embedded profile must be covered by allowed_upstream_namespaces.
    ceiling = list(document["allowed_upstream_namespaces"])
    for profile_name, spec in document["profiles"].items():
        for field in ("visible", "callable"):
            for rule in spec.get(field) or []:
                if not _rule_covered(rule, ceiling):
                    return _fail(
                        BUNDLE_AUDIENCE_MISMATCH,
                        "bundle_audience_mismatch",
                        f"profile '{profile_name}' {field} rule '{rule}' is outside "
                        "allowed_upstream_namespaces",
                        requested,
                        sha256,
                    )

    # Step 9: the E09 static load checks on the embedded profile map,
    # unchanged (extends exists / no self-reference / no cycle / depth <= 8,
    # callable covered by visible, default_profile exists). Bundles are
    # self-contained (decision 9): 'extends' can only name profiles in THIS
    # map -- a dangling parent (e.g. an unsigned local name) is -32014 here.
    embedded = {"profiles": document["profiles"]}
    if "default_profile" in document:
        embedded["default_profile"] = document["default_profile"]
    semantic = _semantic_errors(embedded)
    if semantic:
        return _fail(
            PROFILE_INVALID, "profile_invalid", _format_errors(semantic), requested, sha256
        )

    # Step 10: resolve the selection (cli > env > bundle default_profile)
    # and compile the active profile exactly as E10 does.
    selected = select_profile_name(cli_name, env_name, document.get("default_profile"))
    if not selected:
        return BundleFailClosed(
            code=PROFILE_NOT_FOUND,
            message=(
                "No profile selected and the bundle has no default_profile; every "
                "call is refused (profile_not_found). Fix --profile, "
                "UNLIMITED_SKILLS_MCP_PROFILE, or the bundle's default_profile."
            ),
            requested="",
            bundle_sha256=sha256,
        )
    if selected not in document["profiles"]:
        return BundleFailClosed(
            code=PROFILE_NOT_FOUND,
            message=(
                f"Profile '{selected}' does not exist in the verified bundle; every "
                "call is refused (profile_not_found)."
            ),
            requested=selected,
            bundle_sha256=sha256,
        )
    active = _resolve_active(embedded, selected, sha256)
    provenance = BundleProvenance(
        bundle_sha256=sha256,
        issuer_key_id=document["issuer"]["key_id"],
        issuer_display=document["issuer"]["display"],
        audience=tuple(bundle_audience),
        expires_at=document["expires_at"],
    )

    if local_profiles_path is None:
        return replace(active, provenance=provenance)

    # Local override, narrow-only (design decision 4 and "Local override
    # policy"): the local unsigned file is loaded under the full E09 rules,
    # resolved for the SAME selection name (its own default_profile is
    # ignored -- exactly one artifact owns selection), and intersected with
    # the bundle's selected profile. It can narrow, never widen.
    try:
        local_document, local_sha = load_profile_document(Path(local_profiles_path))
    except ProfileLoadError as exc:
        return _fail(
            PROFILE_INVALID,
            "profile_invalid",
            f"the local profile file alongside the bundle is invalid: {exc}",
            selected,
            sha256,
        )
    if selected not in local_document["profiles"]:
        return BundleFailClosed(
            code=PROFILE_NOT_FOUND,
            message=(
                f"Profile '{selected}' does not exist in the local profile file "
                "configured alongside the bundle; every call is refused "
                "(profile_not_found). The local file must define the selected "
                "profile to narrow it (its default_profile is ignored)."
            ),
            requested=selected,
            bundle_sha256=sha256,
        )
    local_active = _resolve_active(local_document, selected, local_sha)
    merged = _intersect_profiles(active, local_active)
    return replace(merged, provenance=replace(provenance, local_profile_sha256=local_sha))


_DENY_ALL_CHAIN = (RuleSet(globs=frozenset(), exact=frozenset()),)


def _intersect_profiles(bundle: ActiveProfile, local: ActiveProfile) -> ActiveProfile:
    """Restriction-only conjunction across the artifact boundary.

    Concatenates the two resolved rule chains, preserving E09 evaluation
    semantics (intersection of every declared rule list). An artifact whose
    selected profile declared NO rules for a field denies that field
    entirely (E09 default deny) -- represented by an empty rule set that
    matches nothing, so the conjunction can never silently widen.
    """
    visible_chain = (bundle.visible_chain or _DENY_ALL_CHAIN) + (
        local.visible_chain or _DENY_ALL_CHAIN
    )
    callable_chain = (bundle.callable_chain or _DENY_ALL_CHAIN) + (
        local.callable_chain or _DENY_ALL_CHAIN
    )
    return ActiveProfile(
        name=bundle.name,
        visible_chain=visible_chain,
        callable_chain=callable_chain,
        file_sha256=bundle.file_sha256,
        visible_rule_count=bundle.visible_rule_count + local.visible_rule_count,
        callable_rule_count=bundle.callable_rule_count + local.callable_rule_count,
    )
