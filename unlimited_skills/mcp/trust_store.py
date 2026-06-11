"""Managed local trust store for signed MCP profile bundles (E15).

A management layer OVER the E14 verification artifacts -- never a bypass and
never a change to verification semantics (`unlimited_skills/mcp/bundles.py`
still performs every trust decision):

- ``<store>/trusted-keys.json`` is the EXACT E14 trusted-keys format
  (``load_trusted_keys``) -- one source of truth; the store manages that
  file, the gateway keeps reading it unchanged.
- ``<store>/crl.json`` is the EXACT E14 local CRL format (``_load_crl``):
  ``revoked_bundles`` (SHA-256 hex) and ``revoked_key_ids``.
- ``<store>/trust-metadata.json`` is a store-only sidecar
  (``schemas/mcp-trust-store-metadata.schema.json``) for display names,
  informational scopes, ``not_before``, import timestamps, and the
  append-only revocation history. It is NEVER read by verification.

The canonical store location is ``<library root>/.unlimited-skills-trust/``;
explicit ``--trusted-keys`` / ``crl_path`` paths keep working everywhere.

Everything here is OFFLINE: no network, no registry sync, no hosted calls.
The store holds PUBLIC keys only -- ``import`` refuses anything that looks
like private key material before any byte is written. Writes are atomic
(temp file + ``os.replace``). Output never contains full key bytes beyond an
abbreviated SHA-256 fingerprint.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import os
import re
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence

from .bundles import (
    ED25519_PUBLIC_KEY_BYTES,
    TIMESTAMP_RE,
    TrustedKeysError,
    _parse_timestamp,
    load_trusted_keys,
)
from .profiles import KEY_ID_RE, MAX_KEY_ID_LENGTH

DEFAULT_STORE_DIRNAME = ".unlimited-skills-trust"
TRUSTED_KEYS_FILENAME = "trusted-keys.json"
CRL_FILENAME = "crl.json"
METADATA_FILENAME = "trust-metadata.json"

DEFAULT_EXPIRING_SOON_DAYS = 30
DEFAULT_SCOPE = "profile-bundles"
MAX_DISPLAY_LENGTH = 128
MAX_SCOPES = 16
MAX_REASON_LENGTH = 256
FINGERPRINT_HEX_CHARS = 16

SCOPE_RE = re.compile(r"^[a-z][a-z0-9-]{0,63}$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")

# Private-material refusal heuristics (import is public-keys-only).
_PRIVATE_TEXT_MARKERS = (
    "PRIVATE KEY",  # any PEM "-----BEGIN ... PRIVATE KEY-----" variant
    "BEGIN OPENSSH PRIVATE",
)
_PRIVATE_JSON_FIELDS = frozenset(
    {"private_key", "private", "secret", "secret_key", "seed", "d", "priv", "signing_key"}
)
# Decoded lengths that look like private material rather than a wrong key:
# 64 = Ed25519 seed+public concatenation, 48 = PKCS#8 DER Ed25519 private key.
_PRIVATE_LENGTH_HINTS = {64: "a 64-byte Ed25519 seed+public pair", 48: "a 48-byte PKCS#8 private key"}

_TRUSTED_KEYS_TOP = frozenset({"schema_version", "comment", "keys"})
_TRUSTED_KEY_KEYS = frozenset({"key_id", "algorithm", "public_key", "not_after", "comment"})
_CRL_TOP = frozenset({"schema_version", "comment", "revoked_bundles", "revoked_key_ids"})
_METADATA_TOP = frozenset({"schema_version", "comment", "keys", "revocations"})
_METADATA_KEY_KEYS = frozenset(
    {"display", "scopes", "not_before", "imported_at", "comment"}
)
_METADATA_REVOCATION_KEYS = frozenset({"key_id", "bundle_sha256", "revoked_at", "reason"})


class TrustStoreError(ValueError):
    """A trust-store management operation was refused (nothing was written)."""


def default_store_dir(root: Path) -> Path:
    """The canonical managed store location under the library root."""
    return Path(root) / DEFAULT_STORE_DIRNAME


def managed_trusted_keys_path(root: Path) -> Path:
    """Where the gateway looks for the managed trusted-keys file when
    ``--trusted-keys`` is omitted (used only if the file exists)."""
    return default_store_dir(root) / TRUSTED_KEYS_FILENAME


def key_fingerprint(public_key: bytes) -> str:
    """Abbreviated SHA-256 fingerprint -- the only key-derived bytes the
    store ever prints (never the full key)."""
    return hashlib.sha256(public_key).hexdigest()[:FINGERPRINT_HEX_CHARS]


def _format_timestamp(now: float) -> str:
    return datetime.fromtimestamp(now, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


@dataclass(frozen=True)
class TrustStore:
    """Paths of one managed trust store directory."""

    directory: Path

    @property
    def trusted_keys_path(self) -> Path:
        return self.directory / TRUSTED_KEYS_FILENAME

    @property
    def crl_path(self) -> Path:
        return self.directory / CRL_FILENAME

    @property
    def metadata_path(self) -> Path:
        return self.directory / METADATA_FILENAME


# ---------------------------------------------------------------------------
# Atomic writes (temp file in the same directory + os.replace).


def _atomic_write_json(path: Path, document: dict) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    serialized = json.dumps(document, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    fd, tmp_name = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(serialized)
        os.replace(tmp_name, path)
    except BaseException:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


# ---------------------------------------------------------------------------
# Tolerant readers: management must be able to DESCRIBE a broken store, so
# these collect problems instead of raising (verification keeps using the
# strict E14 loaders unchanged).


def _read_json(path: Path) -> tuple[object, list[str]]:
    try:
        raw = Path(path).read_bytes()
    except OSError:
        return None, [f"{path.name} is unreadable"]
    try:
        return json.loads(raw.decode("utf-8-sig", errors="replace")), []
    except json.JSONDecodeError:
        return None, [f"{path.name} is not valid JSON"]


@dataclass
class RawKeyEntry:
    """One trusted-keys entry as read tolerantly (may be partially invalid)."""

    key_id: str = ""
    public_key: bytes = b""
    not_after: float | None = None
    not_after_text: str = ""
    comment: str = ""
    problems: list[str] = field(default_factory=list)


def _read_trusted_keys_raw(path: Path) -> tuple[list[RawKeyEntry], list[str]]:
    """Tolerant read of the E14 trusted-keys file: entries + file problems."""
    document, problems = _read_json(path)
    if problems:
        return [], problems
    if not isinstance(document, dict):
        return [], [f"{path.name} must be a JSON object"]
    if document.get("schema_version") != 1:
        problems.append(f"{path.name} must have schema_version 1")
    for key in document:
        if key not in _TRUSTED_KEYS_TOP:
            problems.append(f"{path.name}: unknown key {key!r}")
    raw_entries = document.get("keys")
    if not isinstance(raw_entries, list):
        problems.append(f"{path.name}: 'keys' must be a list")
        return [], problems
    entries: list[RawKeyEntry] = []
    seen: set[str] = set()
    for index, raw in enumerate(raw_entries):
        label = f"keys[{index}]"
        entry = RawKeyEntry()
        if not isinstance(raw, dict):
            entry.problems.append(f"{label} must be an object")
            entries.append(entry)
            continue
        for key in raw:
            if key not in _TRUSTED_KEY_KEYS:
                entry.problems.append(f"{label}: unknown key {key!r}")
        key_id = raw.get("key_id")
        if isinstance(key_id, str) and 1 <= len(key_id) <= MAX_KEY_ID_LENGTH and KEY_ID_RE.match(key_id):
            entry.key_id = key_id
            if key_id in seen:
                entry.problems.append(f"duplicate key_id {key_id!r}")
            seen.add(key_id)
        else:
            entry.problems.append(f"{label}.key_id is missing or malformed")
        if raw.get("algorithm") != "ed25519":
            entry.problems.append(f"{label}.algorithm must be 'ed25519'")
        public_b64 = raw.get("public_key")
        if isinstance(public_b64, str):
            try:
                decoded = base64.b64decode(public_b64, validate=True)
            except (ValueError, TypeError, binascii.Error):
                decoded = b""
            if len(decoded) == ED25519_PUBLIC_KEY_BYTES:
                entry.public_key = decoded
            else:
                entry.problems.append(f"{label}.public_key is not a raw 32-byte Ed25519 key")
        else:
            entry.problems.append(f"{label}.public_key must be a base64 string")
        if "not_after" in raw:
            value = raw["not_after"]
            if isinstance(value, str) and TIMESTAMP_RE.match(value):
                entry.not_after_text = value
                entry.not_after = _parse_timestamp(value)
            else:
                entry.problems.append(f"{label}.not_after must be an RFC 3339 UTC timestamp")
        if isinstance(raw.get("comment"), str):
            entry.comment = raw["comment"]
        entries.append(entry)
    return entries, problems


def _read_crl_raw(path: Path) -> tuple[dict, list[str]]:
    """Tolerant read of the E14 CRL file: normalized document + problems."""
    empty = {"schema_version": 1, "revoked_bundles": [], "revoked_key_ids": []}
    document, problems = _read_json(path)
    if problems:
        return empty, problems
    if not isinstance(document, dict):
        return empty, [f"{path.name} must be a JSON object"]
    if document.get("schema_version") != 1:
        problems.append(f"{path.name} must have schema_version 1")
    for key in document:
        if key not in _CRL_TOP:
            problems.append(f"{path.name}: unknown key {key!r}")
    for field_name in ("revoked_bundles", "revoked_key_ids"):
        values = document.get(field_name, [])
        if not isinstance(values, list) or not all(isinstance(item, str) for item in values):
            problems.append(f"{path.name}: '{field_name}' must be a list of strings")
            document[field_name] = []
        else:
            document.setdefault(field_name, values)
    return document, problems


def _default_metadata() -> dict:
    return {"schema_version": 1, "keys": {}, "revocations": []}


def _read_metadata_raw(path: Path) -> tuple[dict, list[str]]:
    document, problems = _read_json(path)
    if problems:
        return _default_metadata(), problems
    if not isinstance(document, dict):
        return _default_metadata(), [f"{path.name} must be a JSON object"]
    if document.get("schema_version") != 1:
        problems.append(f"{path.name} must have schema_version 1")
    for key in document:
        if key not in _METADATA_TOP:
            problems.append(f"{path.name}: unknown key {key!r}")
    keys = document.get("keys")
    if keys is None:
        document["keys"] = {}
    elif not isinstance(keys, dict):
        problems.append(f"{path.name}: 'keys' must be an object")
        document["keys"] = {}
    revocations = document.get("revocations")
    if revocations is None:
        document["revocations"] = []
    elif not isinstance(revocations, list):
        problems.append(f"{path.name}: 'revocations' must be a list")
        document["revocations"] = []
    return document, problems


# ---------------------------------------------------------------------------
# Key state.

STATE_ACTIVE = "active"
STATE_EXPIRING_SOON = "expiring_soon"
STATE_EXPIRED = "expired"
STATE_REVOKED = "revoked"


def _key_state(
    entry: RawKeyEntry, revoked_ids: frozenset[str], now: float, expiring_seconds: float
) -> str:
    if entry.key_id and entry.key_id in revoked_ids:
        return STATE_REVOKED
    if entry.not_after is not None:
        if now >= entry.not_after:
            return STATE_EXPIRED
        if now >= entry.not_after - expiring_seconds:
            return STATE_EXPIRING_SOON
    return STATE_ACTIVE


# ---------------------------------------------------------------------------
# Reports: status / list.


def _expiring_seconds(expiring_days: int) -> float:
    return max(0, int(expiring_days)) * 86400.0


def status_report(
    store: TrustStore,
    now: float | None = None,
    expiring_days: int = DEFAULT_EXPIRING_SOON_DAYS,
) -> dict:
    import time as _time

    if now is None:
        now = _time.time()
    entries, key_problems = _read_trusted_keys_raw(store.trusted_keys_path) if store.trusted_keys_path.is_file() else ([], [])
    crl_exists = store.crl_path.is_file()
    empty_crl = {"schema_version": 1, "revoked_bundles": [], "revoked_key_ids": []}
    crl, crl_problems = _read_crl_raw(store.crl_path) if crl_exists else (empty_crl, [])
    metadata_exists = store.metadata_path.is_file()
    _, metadata_problems = _read_metadata_raw(store.metadata_path) if metadata_exists else (_default_metadata(), [])
    revoked_ids = frozenset(crl.get("revoked_key_ids", []))
    seconds = _expiring_seconds(expiring_days)
    counts = {STATE_ACTIVE: 0, STATE_EXPIRING_SOON: 0, STATE_EXPIRED: 0, STATE_REVOKED: 0}
    entry_problems: list[str] = []
    for entry in entries:
        counts[_key_state(entry, revoked_ids, now, seconds)] += 1
        entry_problems.extend(entry.problems)
    problems = key_problems + entry_problems + crl_problems + metadata_problems
    try:
        crl_size = store.crl_path.stat().st_size if crl_exists else 0
    except OSError:
        crl_size = 0
    return {
        "store_dir": str(store.directory),
        "store_exists": store.directory.is_dir(),
        "trusted_keys": {
            "path": str(store.trusted_keys_path),
            "exists": store.trusted_keys_path.is_file(),
        },
        "counts": {
            "total": len(entries),
            "active": counts[STATE_ACTIVE],
            "expiring_soon": counts[STATE_EXPIRING_SOON],
            "expired": counts[STATE_EXPIRED],
            "revoked": counts[STATE_REVOKED],
        },
        "crl": {
            "path": str(store.crl_path),
            "exists": crl_exists,
            "size_bytes": crl_size,
            "revoked_key_ids": len(crl.get("revoked_key_ids", [])),
            "revoked_bundles": len(crl.get("revoked_bundles", [])),
        },
        "metadata": {"path": str(store.metadata_path), "exists": metadata_exists},
        "expiring_days": int(expiring_days),
        "problems": problems,
    }


def list_keys_report(
    store: TrustStore,
    now: float | None = None,
    expiring_days: int = DEFAULT_EXPIRING_SOON_DAYS,
) -> dict:
    import time as _time

    if now is None:
        now = _time.time()
    entries, key_problems = _read_trusted_keys_raw(store.trusted_keys_path) if store.trusted_keys_path.is_file() else ([], [])
    crl, crl_problems = _read_crl_raw(store.crl_path) if store.crl_path.is_file() else ({"revoked_key_ids": []}, [])
    metadata, metadata_problems = _read_metadata_raw(store.metadata_path) if store.metadata_path.is_file() else (_default_metadata(), [])
    revoked_ids = frozenset(crl.get("revoked_key_ids", []))
    seconds = _expiring_seconds(expiring_days)
    keys = []
    problems = key_problems + crl_problems + metadata_problems
    for entry in entries:
        meta = metadata.get("keys", {}).get(entry.key_id, {}) if entry.key_id else {}
        if not isinstance(meta, dict):
            meta = {}
        keys.append(
            {
                "key_id": entry.key_id,
                "fingerprint": key_fingerprint(entry.public_key) if entry.public_key else "",
                "display": str(meta.get("display", "")),
                "scopes": list(meta.get("scopes", [])) if isinstance(meta.get("scopes"), list) else [],
                "not_before": str(meta.get("not_before", "")),
                "not_after": entry.not_after_text,
                "state": _key_state(entry, revoked_ids, now, seconds),
                "comment": entry.comment,
            }
        )
        problems.extend(entry.problems)
    keys.sort(key=lambda item: item["key_id"])
    return {"store_dir": str(store.directory), "keys": keys, "problems": problems}


# ---------------------------------------------------------------------------
# Import (public keys only; refuses private material BEFORE any write).


def _refuse_private_text(text: str, source: str) -> None:
    upper = text.upper()
    for marker in _PRIVATE_TEXT_MARKERS:
        if marker in upper:
            raise TrustStoreError(
                f"{source} looks like PRIVATE key material ({marker.title()} marker); "
                "the trust store holds PUBLIC keys only and nothing was written"
            )


def _decode_public_key(public_b64: str, source: str) -> bytes:
    _refuse_private_text(public_b64, source)
    try:
        decoded = base64.b64decode(public_b64.strip(), validate=True)
    except (ValueError, TypeError, binascii.Error):
        raise TrustStoreError(f"{source} is not valid base64; nothing was written") from None
    hint = _PRIVATE_LENGTH_HINTS.get(len(decoded))
    if hint:
        raise TrustStoreError(
            f"{source} decodes to {hint}, which looks like PRIVATE key material; "
            "the trust store holds PUBLIC keys only and nothing was written"
        )
    if len(decoded) != ED25519_PUBLIC_KEY_BYTES:
        raise TrustStoreError(
            f"{source} must decode to a raw {ED25519_PUBLIC_KEY_BYTES}-byte Ed25519 "
            f"PUBLIC key (got {len(decoded)} bytes); nothing was written"
        )
    return decoded


def _validate_key_id(key_id: str) -> str:
    if not isinstance(key_id, str) or not 1 <= len(key_id) <= MAX_KEY_ID_LENGTH or not KEY_ID_RE.match(key_id):
        raise TrustStoreError("key_id must be a bounded opaque identifier (E09 key_id grammar)")
    return key_id


def _validate_timestamp(value: str, label: str) -> str:
    if not isinstance(value, str) or not TIMESTAMP_RE.match(value):
        raise TrustStoreError(f"{label} must be an RFC 3339 UTC timestamp ending in 'Z'")
    return value


def load_key_file(path: Path) -> dict:
    """Read a small JSON key file for ``import`` (public key + metadata).

    Refuses private-material field names and PEM private markers loudly,
    before the caller touches the store.
    """
    try:
        raw = Path(path).read_text(encoding="utf-8-sig", errors="replace")
    except OSError:
        raise TrustStoreError(f"key file {path} is missing or unreadable") from None
    _refuse_private_text(raw, f"key file {path}")
    try:
        document = json.loads(raw)
    except json.JSONDecodeError:
        raise TrustStoreError(f"key file {path} is not valid JSON") from None
    if not isinstance(document, dict):
        raise TrustStoreError(f"key file {path} must be a JSON object")
    lowered = {str(key).lower() for key in document}
    private_fields = sorted(lowered & _PRIVATE_JSON_FIELDS)
    if private_fields:
        raise TrustStoreError(
            f"key file {path} contains PRIVATE key material field(s) "
            f"{', '.join(private_fields)}; the trust store holds PUBLIC keys only "
            "and nothing was written"
        )
    return document


def import_key(
    store: TrustStore,
    key_id: str,
    public_key_b64: str,
    display: str = "",
    scopes: Sequence[str] | None = None,
    not_before: str = "",
    not_after: str = "",
    comment: str = "",
    now: float | None = None,
) -> dict:
    """Add one PUBLIC key to the managed trusted-keys file (E14 format).

    - Re-importing the same ``key_id`` with the SAME material is an
      idempotent no-op.
    - The same ``key_id`` with DIFFERENT material is a loud refusal --
      silent key replacement is exactly what a trust store must not do.
    - Anything that looks like PRIVATE material is refused before any write.
    """
    import time as _time

    if now is None:
        now = _time.time()
    key_id = _validate_key_id(key_id)
    public_key = _decode_public_key(public_key_b64, "public_key")
    if display and len(display) > MAX_DISPLAY_LENGTH:
        raise TrustStoreError(f"display must be at most {MAX_DISPLAY_LENGTH} characters")
    cleaned_scopes = [scope.strip() for scope in (scopes or []) if scope and scope.strip()]
    if not cleaned_scopes:
        cleaned_scopes = [DEFAULT_SCOPE]
    if len(cleaned_scopes) > MAX_SCOPES:
        raise TrustStoreError(f"at most {MAX_SCOPES} scopes are allowed")
    for scope in cleaned_scopes:
        if not SCOPE_RE.match(scope):
            raise TrustStoreError(f"scope {scope!r} must match {SCOPE_RE.pattern}")
    if not_before:
        not_before = _validate_timestamp(not_before, "not_before")
    if not_after:
        not_after = _validate_timestamp(not_after, "not_after")
    if not_before and not_after and _parse_timestamp(not_before) >= _parse_timestamp(not_after):
        raise TrustStoreError("not_before must be strictly before not_after")

    document: dict
    if store.trusted_keys_path.is_file():
        entries, problems = _read_trusted_keys_raw(store.trusted_keys_path)
        entry_problems = [problem for entry in entries for problem in entry.problems]
        if problems or entry_problems:
            raise TrustStoreError(
                "the managed trusted-keys file has problems; run "
                "'unlimited-skills mcp trust doctor' and fix it before importing: "
                + "; ".join((problems + entry_problems)[:3])
            )
        for entry in entries:
            if entry.key_id == key_id:
                if entry.public_key == public_key:
                    return {
                        "imported": False,
                        "already_present": True,
                        "key_id": key_id,
                        "fingerprint": key_fingerprint(public_key),
                    }
                raise TrustStoreError(
                    f"key_id {key_id!r} already exists with DIFFERENT key material "
                    f"(existing fingerprint {key_fingerprint(entry.public_key)}, "
                    f"offered fingerprint {key_fingerprint(public_key)}); refusing to "
                    "replace a trusted key silently -- revoke and import under a new "
                    "key_id instead"
                )
        raw_document, _ = _read_json(store.trusted_keys_path)
        document = raw_document if isinstance(raw_document, dict) else {"schema_version": 1, "keys": []}
    else:
        document = {"schema_version": 1, "keys": []}

    new_entry: dict = {
        "key_id": key_id,
        "algorithm": "ed25519",
        "public_key": base64.b64encode(public_key).decode("ascii"),
    }
    if not_after:
        new_entry["not_after"] = not_after
    if comment:
        new_entry["comment"] = comment
    document.setdefault("keys", []).append(new_entry)

    metadata, metadata_problems = (
        _read_metadata_raw(store.metadata_path)
        if store.metadata_path.is_file()
        else (_default_metadata(), [])
    )
    if metadata_problems:
        raise TrustStoreError(
            "the trust-store metadata file has problems; run "
            "'unlimited-skills mcp trust doctor' and fix it before importing: "
            + "; ".join(metadata_problems[:3])
        )
    key_meta: dict = {"imported_at": _format_timestamp(now), "scopes": cleaned_scopes}
    if display:
        key_meta["display"] = display
    if not_before:
        key_meta["not_before"] = not_before
    metadata["keys"][key_id] = key_meta

    _atomic_write_json(store.trusted_keys_path, document)
    _atomic_write_json(store.metadata_path, metadata)
    # Round-trip sanity: the file the gateway will read must load strictly.
    try:
        load_trusted_keys(store.trusted_keys_path)
    except TrustedKeysError as exc:  # pragma: no cover - defensive
        raise TrustStoreError(f"written trusted-keys file failed strict validation: {exc}") from None
    return {
        "imported": True,
        "already_present": False,
        "key_id": key_id,
        "fingerprint": key_fingerprint(public_key),
        "scopes": cleaned_scopes,
        "trusted_keys_path": str(store.trusted_keys_path),
    }


# ---------------------------------------------------------------------------
# Revoke (append-only local CRL; idempotent; never deletes history).


def revoke(
    store: TrustStore,
    key_id: str = "",
    bundle_sha256: str = "",
    reason: str = "",
    now: float | None = None,
) -> dict:
    """Add a key_id or bundle SHA-256 to the managed local CRL (E14 format).

    Idempotent: an already-listed target is a no-op success. Entries are
    only ever appended -- revocation history is never deleted. The reason
    (optional) is recorded in the metadata sidecar, never in the CRL (the
    E14 CRL format has no reason field and stays untouched).
    """
    import time as _time

    if now is None:
        now = _time.time()
    if bool(key_id) == bool(bundle_sha256):
        raise TrustStoreError("revoke needs exactly one of key_id or bundle_sha256")
    if key_id:
        key_id = _validate_key_id(key_id)
    if bundle_sha256:
        bundle_sha256 = bundle_sha256.strip().lower()
        if not SHA256_RE.match(bundle_sha256):
            raise TrustStoreError("bundle_sha256 must be 64 lowercase hex characters")
    if reason and len(reason) > MAX_REASON_LENGTH:
        raise TrustStoreError(f"reason must be at most {MAX_REASON_LENGTH} characters")

    if store.crl_path.is_file():
        crl, problems = _read_crl_raw(store.crl_path)
        if problems:
            raise TrustStoreError(
                "the managed CRL file has problems; run 'unlimited-skills mcp trust "
                "doctor' and fix it before revoking: " + "; ".join(problems[:3])
            )
    else:
        crl = {"schema_version": 1, "revoked_bundles": [], "revoked_key_ids": []}

    target_field = "revoked_key_ids" if key_id else "revoked_bundles"
    target_value = key_id or bundle_sha256
    already = target_value in crl.get(target_field, [])
    if already:
        return {
            "revoked": False,
            "already_revoked": True,
            "key_id": key_id,
            "bundle_sha256": bundle_sha256,
            "crl_path": str(store.crl_path),
        }
    crl.setdefault(target_field, []).append(target_value)

    metadata, metadata_problems = (
        _read_metadata_raw(store.metadata_path)
        if store.metadata_path.is_file()
        else (_default_metadata(), [])
    )
    if metadata_problems:
        raise TrustStoreError(
            "the trust-store metadata file has problems; run 'unlimited-skills mcp "
            "trust doctor' and fix it before revoking: " + "; ".join(metadata_problems[:3])
        )
    record: dict = {"revoked_at": _format_timestamp(now)}
    if key_id:
        record["key_id"] = key_id
    if bundle_sha256:
        record["bundle_sha256"] = bundle_sha256
    if reason:
        record["reason"] = reason
    metadata["revocations"].append(record)

    _atomic_write_json(store.crl_path, crl)
    _atomic_write_json(store.metadata_path, metadata)
    return {
        "revoked": True,
        "already_revoked": False,
        "key_id": key_id,
        "bundle_sha256": bundle_sha256,
        "crl_path": str(store.crl_path),
    }


# ---------------------------------------------------------------------------
# Doctor (offline self-check; exit 0 ok / 1 problems).


def doctor_report(
    store: TrustStore,
    now: float | None = None,
    expiring_days: int = DEFAULT_EXPIRING_SOON_DAYS,
) -> dict:
    """Offline store self-check.

    PROBLEMS (exit 1): malformed/unreadable store files, duplicate key_ids,
    expired keys with no active key remaining (expired-but-not-rotated), a
    CRL that exists but cannot be read, a revoked key still listed in the
    trusted-keys file with no metadata revocation record (revoked outside
    the store, unexplained), world-writable store files (POSIX only).

    WARNINGS (exit 0): keys expiring soon, expired keys while an active key
    remains, an empty trusted-keys file (the gateway would refuse with
    bundle_key_missing), revoked-with-explanation keys still listed,
    metadata entries for unknown key_ids.
    """
    import time as _time

    if now is None:
        now = _time.time()
    problems: list[str] = []
    warnings: list[str] = []
    checks: list[dict] = []

    def check(name: str, ok: bool, detail: str = "") -> None:
        checks.append({"check": name, "ok": ok, "detail": detail})

    if not store.directory.is_dir():
        check("store_dir", True, "no managed trust store (nothing to check)")
        return {
            "store_dir": str(store.directory),
            "status": "ok",
            "checks": checks,
            "problems": problems,
            "warnings": warnings,
            "exit_code": 0,
        }
    check("store_dir", True, str(store.directory))

    # Trusted-keys file shape.
    entries: list[RawKeyEntry] = []
    if store.trusted_keys_path.is_file():
        entries, file_problems = _read_trusted_keys_raw(store.trusted_keys_path)
        entry_problems = [problem for entry in entries for problem in entry.problems]
        shape_problems = file_problems + entry_problems
        check(
            "trusted_keys_shape",
            not shape_problems,
            "; ".join(shape_problems[:5]) or f"{len(entries)} key(s)",
        )
        problems.extend(shape_problems)
        if not shape_problems and not entries:
            warnings.append(
                "trusted-keys file lists no keys; gateway verification would refuse "
                "with bundle_key_missing (-32019)"
            )
        # Strict-loader agreement: what the gateway will actually do.
        try:
            load_trusted_keys(store.trusted_keys_path)
            check("gateway_strict_load", True, "load_trusted_keys accepts the file")
        except TrustedKeysError as exc:
            detail = f"gateway would refuse with bundle_key_missing: {exc}"
            check("gateway_strict_load", False, detail)
            if not shape_problems and entries:
                problems.append(detail)
    else:
        check("trusted_keys_shape", True, "no trusted-keys file yet (empty store)")
        warnings.append("no trusted-keys file yet; import a key first")

    # CRL readability.
    revoked_ids: frozenset[str] = frozenset()
    if store.crl_path.is_file():
        crl, crl_problems = _read_crl_raw(store.crl_path)
        check("crl_readable", not crl_problems, "; ".join(crl_problems[:5]) or "CRL parses")
        problems.extend(crl_problems)
        revoked_ids = frozenset(crl.get("revoked_key_ids", []))
    else:
        check("crl_readable", True, "no CRL file (no revocations recorded)")

    # Metadata shape.
    metadata = _default_metadata()
    if store.metadata_path.is_file():
        metadata, metadata_problems = _read_metadata_raw(store.metadata_path)
        check("metadata_shape", not metadata_problems, "; ".join(metadata_problems[:5]) or "metadata parses")
        problems.extend(metadata_problems)
    else:
        check("metadata_shape", True, "no metadata sidecar (optional)")

    # Key lifecycle: duplicates, expiry, rotation, revocation explanations.
    seconds = _expiring_seconds(expiring_days)
    seen: set[str] = set()
    duplicate_ids: set[str] = set()
    states: dict[str, str] = {}
    for entry in entries:
        if not entry.key_id:
            continue
        if entry.key_id in seen:
            duplicate_ids.add(entry.key_id)
        seen.add(entry.key_id)
        states[entry.key_id] = _key_state(entry, revoked_ids, now, seconds)
    check(
        "duplicate_key_ids",
        not duplicate_ids,
        "; ".join(f"duplicate key_id {key_id!r}" for key_id in sorted(duplicate_ids)) or "all key_ids unique",
    )

    active = [key_id for key_id, state in states.items() if state in (STATE_ACTIVE, STATE_EXPIRING_SOON)]
    expired = [key_id for key_id, state in states.items() if state == STATE_EXPIRED]
    expiring = [key_id for key_id, state in states.items() if state == STATE_EXPIRING_SOON]
    revoked_listed = [key_id for key_id, state in states.items() if state == STATE_REVOKED]
    for key_id in sorted(expiring):
        warnings.append(f"key '{key_id}' expires within {int(expiring_days)} day(s); plan a rotation")
    if expired and not active:
        detail = (
            f"expired key(s) {', '.join(sorted(expired))} with NO active key remaining "
            "(expired-but-not-rotated); the gateway would refuse with bundle_key_missing"
        )
        check("rotation", False, detail)
        problems.append(detail)
    else:
        for key_id in sorted(expired):
            warnings.append(f"key '{key_id}' is past its not_after; remove it after the rotation overlap")
        check("rotation", True, f"{len(active)} active key(s)")

    explained = set()
    for record in metadata.get("revocations", []):
        if isinstance(record, dict) and isinstance(record.get("key_id"), str):
            explained.add(record["key_id"])
    unexplained = sorted(set(revoked_listed) - explained)
    if unexplained:
        detail = (
            "revoked key(s) still listed in trusted-keys with no metadata revocation "
            f"record (revoked outside the store?): {', '.join(unexplained)}"
        )
        check("revocation_explained", False, detail)
        problems.append(detail)
    else:
        check("revocation_explained", True, "every revoked key has a revocation record")
        for key_id in sorted(set(revoked_listed) & explained):
            warnings.append(
                f"key '{key_id}' is revoked but still listed in trusted-keys; "
                "the CRL wins (verification refuses), entry kept for history"
            )

    for key_id in sorted(set(metadata.get("keys", {})) - seen):
        warnings.append(f"metadata names key_id '{key_id}' that is not in the trusted-keys file")

    # File permissions sanity (best-effort; meaningful mostly on POSIX).
    permission_problems: list[str] = []
    for path in (store.trusted_keys_path, store.crl_path, store.metadata_path):
        if not path.is_file():
            continue
        if not os.access(path, os.R_OK):
            permission_problems.append(f"{path.name} is not readable")
        if os.name == "posix":
            try:
                if path.stat().st_mode & 0o002:
                    permission_problems.append(f"{path.name} is world-writable")
            except OSError:
                permission_problems.append(f"{path.name} could not be stat'ed")
    check("file_permissions", not permission_problems, "; ".join(permission_problems) or "ok (best-effort)")
    problems.extend(permission_problems)

    status = "problems" if problems else "ok"
    return {
        "store_dir": str(store.directory),
        "status": status,
        "checks": checks,
        "problems": problems,
        "warnings": warnings,
        "exit_code": 1 if problems else 0,
    }


# ---------------------------------------------------------------------------
# Human renderers (text mode; --json prints the report dicts verbatim).


def format_status(report: dict) -> str:
    counts = report["counts"]
    crl = report["crl"]
    lines = [
        f"MCP trust store: {report['store_dir']}",
        (
            f"trusted keys: {counts['total']} total -- {counts['active']} active, "
            f"{counts['expiring_soon']} expiring soon (<= {report['expiring_days']} d), "
            f"{counts['expired']} expired, {counts['revoked']} revoked"
        ),
        (
            f"CRL: {'present' if crl['exists'] else 'absent'} ({crl['size_bytes']} bytes), "
            f"{crl['revoked_key_ids']} revoked key id(s), {crl['revoked_bundles']} revoked bundle(s)"
        ),
        f"metadata sidecar: {'present' if report['metadata']['exists'] else 'absent'}",
    ]
    if report["problems"]:
        lines.append("problems:")
        lines.extend(f"  - {problem}" for problem in report["problems"])
    else:
        lines.append("problems: none")
    return "\n".join(lines)


def format_key_list(report: dict) -> str:
    if not report["keys"]:
        lines = [f"MCP trust store: {report['store_dir']}", "no trusted keys"]
    else:
        lines = [f"MCP trust store: {report['store_dir']}"]
        for key in report["keys"]:
            display = f" ({key['display']})" if key["display"] else ""
            window = f"{key['not_before'] or '-'} .. {key['not_after'] or '-'}"
            scopes = ",".join(key["scopes"]) or "-"
            lines.append(
                f"  {key['key_id']}{display}: state={key['state']} "
                f"fingerprint={key['fingerprint']} scopes={scopes} validity={window}"
            )
    if report["problems"]:
        lines.append("problems:")
        lines.extend(f"  - {problem}" for problem in report["problems"])
    return "\n".join(lines)


def format_doctor(report: dict) -> str:
    lines = [f"MCP trust store doctor: {report['store_dir']} -- {report['status']}"]
    for item in report["checks"]:
        mark = "ok" if item["ok"] else "PROBLEM"
        detail = f": {item['detail']}" if item["detail"] else ""
        lines.append(f"  [{mark}] {item['check']}{detail}")
    for warning in report["warnings"]:
        lines.append(f"  warning: {warning}")
    for problem in report["problems"]:
        lines.append(f"  problem: {problem}")
    return "\n".join(lines)
