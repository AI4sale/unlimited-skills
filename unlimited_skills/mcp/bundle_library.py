"""Local library and activation manager for signed MCP profile bundles (E20).

The operational gap this closes: "I have 5 bundle files. Which are
installed? Which is active? How do I roll back?" -- a LOCAL library of
signed profile bundles with install, list, status, pin/unpin,
activate/deactivate, rollback to a known-good bundle. No registry sync, no
hosted calls, no production signing keys.

Design (mirrors the E15 managed-store conventions in
``unlimited_skills/mcp/trust_store.py``):

- The library directory is ``<library root>/.unlimited-skills-bundles/``
  (override ``--library-dir``). Bundle files are stored IMMUTABLE and
  content-addressed as ``<sha256-prefix>-<name>.bundle.json``; the library
  never edits bundle bytes (that would break the signature).
- ``library-state.json`` (atomic writes: temp file + ``os.replace``) tracks
  the entries (sha256, name, issuer key_id, audience, validity window,
  added_at, source basename, pinned flag, verification status at add time),
  the single ACTIVE bundle sha (at most one), and an append-only activation
  history ``(sha, action, ts)`` that powers ``rollback``.
- Verification is the REAL E14 path -- :func:`verify_report` over
  :func:`resolve_bundle_state` -- never a reimplementation and never a
  bypass. ``add`` verifies BEFORE anything is stored (invalid bundles are
  refused outright with the exact refusal code; there is no quarantine
  mode), ``activate``/``rollback`` re-verify at activation time (keys and
  the CRL may have changed since ``add``), and ``doctor`` re-verifies every
  entry against the CURRENT trust store.
- Activation pointer: ``activate`` copies the verified stored bytes to
  ``<library>/active.bundle.json`` atomically (a plain file copy -- no
  symlinks, Windows-safe). The gateway is started with
  ``--profile-bundle <library>/active.bundle.json`` and reads it ONCE at
  startup (no hot reload, consistent with E10/E14); the gateway re-runs the
  full E14 verification itself, so a stale or since-revoked active copy
  still fails closed.
- Privacy/safety: no key material is ever stored beyond what the bundles
  already contain (public information only); no network; atomic state
  writes; audit-style outputs carry source BASENAMES, never the operator's
  absolute source paths; refusals are loud with the exact reserved codes.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence

from .bundle_publisher import BUNDLE_NAME_RE, REFUSAL_NAMES, verify_report
from .bundles import _parse_timestamp, local_audience_ids
from .trust_store import SHA256_RE, _atomic_write_json

DEFAULT_LIBRARY_DIRNAME = ".unlimited-skills-bundles"
STATE_FILENAME = "library-state.json"
ACTIVE_BUNDLE_FILENAME = "active.bundle.json"
SHA_PREFIX_CHARS = 12
MIN_REF_PREFIX = 8

SHA_PREFIX_RE = re.compile(r"^[0-9a-f]{8,64}$")

ACTION_ACTIVATE = "activate"
ACTION_DEACTIVATE = "deactivate"
ACTION_ROLLBACK = "rollback"
_ACTIONS = frozenset({ACTION_ACTIVATE, ACTION_DEACTIVATE, ACTION_ROLLBACK})

_STATE_TOP = frozenset({"schema_version", "comment", "entries", "active_sha256", "history"})
_ENTRY_KEYS = frozenset(
    {
        "sha256",
        "name",
        "file",
        "issuer_key_id",
        "audience",
        "issued_at",
        "expires_at",
        "added_at",
        "source",
        "pinned",
        "verification",
    }
)

REBUILD_GUIDANCE = (
    "the library state file is corrupt; move it aside and rebuild by re-adding "
    "the original bundle files with 'unlimited-skills mcp profiles library add' "
    "(stored bundle files are immutable and content-addressed, so nothing "
    "signed is lost)"
)


class BundleLibraryError(ValueError):
    """A library operation was refused (nothing was changed).

    ``code`` carries the E14 refusal code when the refusal came from real
    bundle verification (0 otherwise).
    """

    def __init__(self, message: str, code: int = 0) -> None:
        super().__init__(message)
        self.code = code


def default_library_dir(root: Path) -> Path:
    """The canonical library location under the library root."""
    return Path(root) / DEFAULT_LIBRARY_DIRNAME


def _utc_text(now: float) -> str:
    return datetime.fromtimestamp(now, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


@dataclass(frozen=True)
class BundleLibrary:
    """Paths of one local bundle library directory."""

    directory: Path

    @property
    def state_path(self) -> Path:
        return self.directory / STATE_FILENAME

    @property
    def active_bundle_path(self) -> Path:
        return self.directory / ACTIVE_BUNDLE_FILENAME

    def stored_path(self, entry: dict) -> Path:
        return self.directory / str(entry.get("file", ""))


def stored_filename(sha256: str, name: str) -> str:
    return f"{sha256[:SHA_PREFIX_CHARS]}-{name}.bundle.json"


# ---------------------------------------------------------------------------
# Atomic writes (the E15 pattern: temp file in the same directory + replace).


def _atomic_write_bytes(path: Path, data: bytes) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
        os.replace(tmp_name, path)
    except BaseException:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


# ---------------------------------------------------------------------------
# State file: tolerant read (management must DESCRIBE a broken library), the
# same stance as the E15 store readers. Writers always emit the strict shape.


def _default_state() -> dict:
    return {"schema_version": 1, "entries": [], "active_sha256": "", "history": []}


def read_state(library: BundleLibrary) -> tuple[dict, list[str]]:
    """Tolerant read of ``library-state.json``: normalized state + problems."""
    state = _default_state()
    path = library.state_path
    if not path.is_file():
        return state, []
    try:
        raw = path.read_bytes()
    except OSError:
        return state, [f"{STATE_FILENAME} is unreadable"]
    try:
        document = json.loads(raw.decode("utf-8-sig", errors="replace"))
    except json.JSONDecodeError:
        return state, [f"{STATE_FILENAME} is not valid JSON"]
    if not isinstance(document, dict):
        return state, [f"{STATE_FILENAME} must be a JSON object"]
    problems: list[str] = []
    if document.get("schema_version") != 1:
        problems.append(f"{STATE_FILENAME} must have schema_version 1")
    for key in document:
        if key not in _STATE_TOP:
            problems.append(f"{STATE_FILENAME}: unknown key {key!r}")
    entries = document.get("entries")
    if entries is None:
        entries = []
    elif not isinstance(entries, list):
        problems.append(f"{STATE_FILENAME}: 'entries' must be a list")
        entries = []
    cleaned_entries: list[dict] = []
    seen: set[str] = set()
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict):
            problems.append(f"{STATE_FILENAME}: entries[{index}] must be an object")
            continue
        sha = entry.get("sha256")
        if not isinstance(sha, str) or not SHA256_RE.match(sha):
            problems.append(f"{STATE_FILENAME}: entries[{index}].sha256 is missing or malformed")
            continue
        if sha in seen:
            problems.append(f"{STATE_FILENAME}: duplicate entry sha256 {sha[:SHA_PREFIX_CHARS]}")
            continue
        seen.add(sha)
        cleaned = {key: entry.get(key) for key in _ENTRY_KEYS if key in entry}
        cleaned["sha256"] = sha
        cleaned["name"] = str(entry.get("name", ""))
        cleaned["file"] = str(entry.get("file", "")) or stored_filename(sha, cleaned["name"])
        cleaned["pinned"] = bool(entry.get("pinned", False))
        cleaned["audience"] = (
            [str(item) for item in entry.get("audience", [])]
            if isinstance(entry.get("audience"), list)
            else []
        )
        cleaned_entries.append(cleaned)
    state["entries"] = cleaned_entries
    active = document.get("active_sha256", "")
    if isinstance(active, str) and (not active or SHA256_RE.match(active)):
        state["active_sha256"] = active
    else:
        problems.append(f"{STATE_FILENAME}: active_sha256 is malformed")
    history = document.get("history", [])
    if not isinstance(history, list):
        problems.append(f"{STATE_FILENAME}: 'history' must be a list")
        history = []
    cleaned_history: list[dict] = []
    for index, record in enumerate(history):
        if (
            not isinstance(record, dict)
            or not isinstance(record.get("sha256"), str)
            or record.get("action") not in _ACTIONS
        ):
            problems.append(f"{STATE_FILENAME}: history[{index}] is malformed")
            continue
        cleaned_history.append(
            {
                "sha256": record["sha256"],
                "action": record["action"],
                "ts": str(record.get("ts", "")),
            }
        )
    state["history"] = cleaned_history
    return state, problems


def _load_state_strict(library: BundleLibrary, operation: str) -> dict:
    """State for a MUTATING operation: any state-file problem is a refusal
    (mutating a half-understood state file could corrupt it further)."""
    state, problems = read_state(library)
    if problems:
        raise BundleLibraryError(
            f"{operation} refused: " + "; ".join(problems[:3]) + f" -- {REBUILD_GUIDANCE}"
        )
    return state


def _write_state(library: BundleLibrary, state: dict) -> None:
    _atomic_write_json(library.state_path, state)


# ---------------------------------------------------------------------------
# Verification: the REAL E14 path via the E19 verify wrapper.


def _bundle_document(raw: bytes) -> dict | None:
    try:
        document = json.loads(raw.decode("utf-8-sig", errors="replace"))
    except json.JSONDecodeError:
        return None
    return document if isinstance(document, dict) else None


def _selection_name(document: dict | None) -> str:
    """The selection used for verification: the bundle's ``default_profile``
    or its first profile name (exactly the E19 self-check rule)."""
    if not document:
        return ""
    default = document.get("default_profile")
    if isinstance(default, str) and default:
        return default
    profiles = document.get("profiles")
    if isinstance(profiles, dict) and profiles:
        return sorted(profiles)[0]
    return ""


def _verification_audience(document: dict | None, audience_ids: Sequence[str] | None) -> list[str]:
    """Audience identifiers used for library-side verification.

    Explicit ``--audience-id`` flags (or the env var) are used strictly when
    present. Otherwise the bundle's own first declared audience identifier
    is used (self-audience): the library then proves signature, validity
    window, revocation, and key trust -- audience BINDING stays enforced by
    the gateway at startup with the consumer's real identifiers.
    """
    ids = local_audience_ids(audience_ids)
    if ids:
        return ids
    if document:
        audience = document.get("audience")
        if isinstance(audience, list) and audience and isinstance(audience[0], str):
            return [audience[0]]
    return []


def verify_bundle_file(
    path: Path,
    trusted_keys_path: str | Path,
    audience_ids: Sequence[str] | None = None,
    now: float | None = None,
) -> dict:
    """Re-verify one bundle file through the REAL E14 path (E19 wrapper)."""
    try:
        raw = Path(path).read_bytes()
    except OSError:
        raw = b""
    document = _bundle_document(raw)
    return verify_report(
        Path(path),
        Path(trusted_keys_path) if str(trusted_keys_path) else "",
        audience_ids=_verification_audience(document, audience_ids),
        now=now,
        profile_name=_selection_name(document),
    )


_STATE_BY_CODE = {
    -32014: "invalid",
    -32015: "signature-invalid",
    -32016: "expired",
    -32017: "revoked",
    -32018: "audience-mismatch",
    -32019: "key-missing",
}


def _recheck_state(report: dict) -> str:
    if report["ok"]:
        return "ok"
    return _STATE_BY_CODE.get(report["code"], REFUSAL_NAMES.get(report["code"], "refused"))


# ---------------------------------------------------------------------------
# Reference resolution: full SHA-256, an 8+ char sha prefix, or a name.


def _resolve_entry(state: dict, ref: str) -> dict:
    ref = (ref or "").strip()
    if not ref:
        raise BundleLibraryError("a bundle reference (sha256, sha prefix, or name) is required")
    lowered = ref.lower()
    matches: list[dict]
    if SHA_PREFIX_RE.match(lowered):
        matches = [entry for entry in state["entries"] if entry["sha256"].startswith(lowered)]
        if not matches:  # a hex-looking NAME is still a valid name
            matches = [entry for entry in state["entries"] if entry["name"] == ref]
    else:
        matches = [entry for entry in state["entries"] if entry["name"] == ref]
    if not matches:
        raise BundleLibraryError(
            f"no library entry matches {ref!r}; run 'unlimited-skills mcp profiles "
            "library list' to see installed bundles"
        )
    if len(matches) > 1:
        shown = ", ".join(
            f"{entry['sha256'][:SHA_PREFIX_CHARS]} ({entry['name']})" for entry in matches
        )
        raise BundleLibraryError(
            f"reference {ref!r} is ambiguous between {len(matches)} entries: {shown}; "
            "use a longer sha prefix"
        )
    return matches[0]


def _derive_name(source: Path, explicit: str) -> str:
    name = (explicit or "").strip()
    if not name:
        name = source.name
        for suffix in (".bundle.json", ".json"):
            if name.endswith(suffix):
                name = name[: -len(suffix)]
                break
    if not BUNDLE_NAME_RE.match(name):
        raise BundleLibraryError(
            f"bundle name {name!r} must match {BUNDLE_NAME_RE.pattern}; pass --name"
        )
    return name


# ---------------------------------------------------------------------------
# add: verify FIRST (the real E14 path), then store content-addressed.


def add_bundle(
    library: BundleLibrary,
    file_path: Path,
    trusted_keys_path: str | Path = "",
    audience_ids: Sequence[str] | None = None,
    name: str = "",
    now: float | None = None,
) -> dict:
    """Install one signed bundle file into the library.

    The bundle is verified through the REAL :func:`resolve_bundle_state`
    against the trust store BEFORE anything is stored; any refusal (with its
    exact reserved code) means nothing is written -- there is no quarantine
    mode and no ``--allow-unverified`` (an unverifiable bundle has no
    business in an activation library). A duplicate sha256 is an idempotent
    no-op. The stored copy is immutable and content-addressed.
    """
    import time as _time

    if now is None:
        now = _time.time()
    source = Path(file_path).expanduser()
    try:
        raw = source.read_bytes()
    except OSError:
        raise BundleLibraryError(f"bundle file {source.name} is missing or unreadable") from None
    sha256 = hashlib.sha256(raw).hexdigest()
    state = _load_state_strict(library, "add")
    for entry in state["entries"]:
        if entry["sha256"] == sha256:
            return {
                "added": False,
                "already_present": True,
                "sha256": sha256,
                "name": entry["name"],
                "file": entry["file"],
            }

    report = verify_bundle_file(source, trusted_keys_path, audience_ids, now=now)
    if not report["ok"]:
        raise BundleLibraryError(
            f"add refused: the bundle does not verify ({report['code']} "
            f"{report['refusal']}): {report['message']} -- nothing was stored",
            code=report["code"],
        )

    document = _bundle_document(raw) or {}
    derived = _derive_name(source, name)
    for entry in state["entries"]:
        if entry["name"] == derived:
            raise BundleLibraryError(
                f"add refused: name {derived!r} is already used by entry "
                f"{entry['sha256'][:SHA_PREFIX_CHARS]}; pass --name to disambiguate"
            )
    filename = stored_filename(sha256, derived)
    issuer = document.get("issuer") if isinstance(document.get("issuer"), dict) else {}
    entry = {
        "sha256": sha256,
        "name": derived,
        "file": filename,
        "issuer_key_id": str(issuer.get("key_id", "")),
        "audience": [str(item) for item in document.get("audience", []) if isinstance(item, str)],
        "issued_at": str(document.get("issued_at", "")),
        "expires_at": str(document.get("expires_at", "")),
        "added_at": _utc_text(now),
        "source": source.name,  # basename only, never the absolute path
        "pinned": False,
        "verification": "verified",
    }
    stored = library.directory / filename
    _atomic_write_bytes(stored, raw)
    try:
        state["entries"].append(entry)
        _write_state(library, state)
    except BaseException:
        # Never leave an orphan bundle file behind a failed state write.
        try:
            stored.unlink()
        except OSError:
            pass
        raise
    return {
        "added": True,
        "already_present": False,
        "sha256": sha256,
        "name": derived,
        "file": filename,
        "issuer_key_id": entry["issuer_key_id"],
        "audience": entry["audience"],
        "expires_at": entry["expires_at"],
        "verification": "verified",
    }


# ---------------------------------------------------------------------------
# activate / deactivate / rollback.


def activate_bundle(
    library: BundleLibrary,
    ref: str,
    trusted_keys_path: str | Path = "",
    audience_ids: Sequence[str] | None = None,
    now: float | None = None,
    _action: str = ACTION_ACTIVATE,
) -> dict:
    """Activate one installed bundle (at most one is active).

    RE-verifies at activation time through the real E14 path -- keys and the
    CRL may have changed since ``add`` -- then copies the verified stored
    bytes to ``active.bundle.json`` (atomic plain-file copy; no symlinks)
    and records the activation in the append-only history. The gateway
    reads the pointer file ONCE at its next start: no hot reload.
    """
    import time as _time

    if now is None:
        now = _time.time()
    state = _load_state_strict(library, _action)
    entry = _resolve_entry(state, ref)
    stored = library.stored_path(entry)
    if not stored.is_file():
        raise BundleLibraryError(
            f"{_action} refused: stored bundle file {entry['file']} is missing; "
            "run 'unlimited-skills mcp profiles library doctor'"
        )
    report = verify_bundle_file(stored, trusted_keys_path, audience_ids, now=now)
    if not report["ok"]:
        raise BundleLibraryError(
            f"{_action} refused: bundle {entry['sha256'][:SHA_PREFIX_CHARS]} "
            f"({entry['name']}) no longer verifies ({report['code']} "
            f"{report['refusal']}): {report['message']} -- the active bundle was "
            "not changed",
            code=report["code"],
        )
    _atomic_write_bytes(library.active_bundle_path, stored.read_bytes())
    previous = state["active_sha256"]
    state["active_sha256"] = entry["sha256"]
    state["history"].append({"sha256": entry["sha256"], "action": _action, "ts": _utc_text(now)})
    _write_state(library, state)
    return {
        "activated": True,
        "action": _action,
        "sha256": entry["sha256"],
        "name": entry["name"],
        "previous_active_sha256": previous,
        "active_bundle_file": ACTIVE_BUNDLE_FILENAME,
        "note": (
            "no hot reload: the gateway reads the active bundle at startup; "
            "(re)start it with --profile-bundle "
            f"<library-dir>/{ACTIVE_BUNDLE_FILENAME}"
        ),
    }


def deactivate_bundle(library: BundleLibrary, now: float | None = None) -> dict:
    """Clear the active bundle (idempotent). Removes ``active.bundle.json``;
    a gateway restarted WITHOUT ``--profile-bundle`` runs in open
    no-profiles mode -- said loudly in the result."""
    import time as _time

    if now is None:
        now = _time.time()
    state = _load_state_strict(library, "deactivate")
    active = state["active_sha256"]
    if not active:
        return {"deactivated": False, "already_inactive": True, "sha256": ""}
    state["active_sha256"] = ""
    state["history"].append({"sha256": active, "action": ACTION_DEACTIVATE, "ts": _utc_text(now)})
    _write_state(library, state)
    try:
        library.active_bundle_path.unlink()
    except OSError:
        pass
    return {
        "deactivated": True,
        "already_inactive": False,
        "sha256": active,
        "note": (
            "no bundle is active: a gateway restarted without --profile-bundle "
            "runs in OPEN no-profiles mode (no enforcement); restarted against "
            f"the removed {ACTIVE_BUNDLE_FILENAME} it fails closed (-32014)"
        ),
    }


def rollback_bundle(
    library: BundleLibrary,
    trusted_keys_path: str | Path = "",
    audience_ids: Sequence[str] | None = None,
    now: float | None = None,
) -> dict:
    """Re-activate the previous known-good bundle from the history.

    Walks the activation history backwards (most recent first), skips the
    currently active sha, and RE-verifies each candidate through the real
    E14 path -- entries that are now revoked, expired, or otherwise refused
    are skipped LOUDLY (each skip is reported with its exact code) until one
    verifies. No candidate verifying is a refusal; nothing changes.
    """
    import time as _time

    if now is None:
        now = _time.time()
    state = _load_state_strict(library, "rollback")
    activations = [
        record["sha256"]
        for record in reversed(state["history"])
        if record["action"] in (ACTION_ACTIVATE, ACTION_ROLLBACK)
    ]
    seen: set[str] = set()
    candidates: list[str] = []
    for sha in activations:
        if sha not in seen:
            seen.add(sha)
            candidates.append(sha)
    active = state["active_sha256"]
    candidates = [sha for sha in candidates if sha != active]
    if not candidates:
        raise BundleLibraryError(
            "rollback refused: the activation history has no previous bundle to "
            "roll back to"
        )
    by_sha = {entry["sha256"]: entry for entry in state["entries"]}
    skipped: list[dict] = []
    for sha in candidates:
        entry = by_sha.get(sha)
        if entry is None:
            skipped.append({"sha256": sha, "name": "", "code": 0, "refusal": "removed-from-library"})
            continue
        stored = library.stored_path(entry)
        if not stored.is_file():
            skipped.append(
                {"sha256": sha, "name": entry["name"], "code": 0, "refusal": "stored-file-missing"}
            )
            continue
        report = verify_bundle_file(stored, trusted_keys_path, audience_ids, now=now)
        if not report["ok"]:
            skipped.append(
                {
                    "sha256": sha,
                    "name": entry["name"],
                    "code": report["code"],
                    "refusal": report["refusal"],
                }
            )
            continue
        result = activate_bundle(
            library,
            sha,
            trusted_keys_path,
            audience_ids,
            now=now,
            _action=ACTION_ROLLBACK,
        )
        result["rolled_back"] = True
        result["skipped"] = skipped
        return result
    raise BundleLibraryError(
        "rollback refused: no previous bundle in the history still verifies "
        "against the current trust store -- skipped: "
        + "; ".join(
            f"{item['sha256'][:SHA_PREFIX_CHARS]} ({item['name'] or '?'}): "
            f"{item['refusal']}"
            for item in skipped
        )
    )


# ---------------------------------------------------------------------------
# pin / unpin / remove.


def set_pinned(library: BundleLibrary, ref: str, pinned: bool) -> dict:
    operation = "pin" if pinned else "unpin"
    state = _load_state_strict(library, operation)
    entry = _resolve_entry(state, ref)
    changed = entry["pinned"] != pinned
    entry["pinned"] = pinned
    if changed:
        _write_state(library, state)
    return {
        "pinned": pinned,
        "changed": changed,
        "sha256": entry["sha256"],
        "name": entry["name"],
    }


def remove_bundle(library: BundleLibrary, ref: str, force: bool = False, now: float | None = None) -> dict:
    """Remove one installed bundle from the library.

    Pinned entries ALWAYS refuse (unpin first; ``--force`` does not override
    a pin -- that is what pinning is for). The ACTIVE entry refuses without
    ``--force``; with ``--force`` it is deactivated first (recorded in the
    history) and then removed.
    """
    import time as _time

    if now is None:
        now = _time.time()
    state = _load_state_strict(library, "remove")
    entry = _resolve_entry(state, ref)
    if entry["pinned"]:
        raise BundleLibraryError(
            f"remove refused: bundle {entry['sha256'][:SHA_PREFIX_CHARS]} "
            f"({entry['name']}) is PINNED; unpin it first (--force does not "
            "override a pin)"
        )
    deactivated = False
    if state["active_sha256"] == entry["sha256"]:
        if not force:
            raise BundleLibraryError(
                f"remove refused: bundle {entry['sha256'][:SHA_PREFIX_CHARS]} "
                f"({entry['name']}) is the ACTIVE bundle; deactivate it first or "
                "pass --force (which deactivates, then removes)"
            )
        state["active_sha256"] = ""
        state["history"].append(
            {"sha256": entry["sha256"], "action": ACTION_DEACTIVATE, "ts": _utc_text(now)}
        )
        deactivated = True
    state["entries"] = [item for item in state["entries"] if item["sha256"] != entry["sha256"]]
    _write_state(library, state)
    if deactivated:
        try:
            library.active_bundle_path.unlink()
        except OSError:
            pass
    stored = library.stored_path(entry)
    try:
        stored.unlink()
    except OSError:
        pass
    return {
        "removed": True,
        "deactivated": deactivated,
        "sha256": entry["sha256"],
        "name": entry["name"],
    }


# ---------------------------------------------------------------------------
# status / list / inspect.


def status_report(
    library: BundleLibrary,
    trusted_keys_path: str | Path = "",
    audience_ids: Sequence[str] | None = None,
    now: float | None = None,
) -> dict:
    import time as _time

    if now is None:
        now = _time.time()
    state, problems = read_state(library)
    active_sha = state["active_sha256"]
    active: dict = {}
    if active_sha:
        entry = next((item for item in state["entries"] if item["sha256"] == active_sha), None)
        if entry is None:
            problems.append(
                f"active_sha256 {active_sha[:SHA_PREFIX_CHARS]} has no library entry"
            )
        else:
            days_left: float | None = None
            try:
                days_left = (_parse_timestamp(entry["expires_at"]) - now) / 86400.0
            except (ValueError, KeyError, TypeError):
                pass
            stored = library.stored_path(entry)
            report = verify_bundle_file(stored, trusted_keys_path, audience_ids, now=now)
            active = {
                "sha256": entry["sha256"],
                "name": entry["name"],
                "issuer_key_id": entry.get("issuer_key_id", ""),
                "expires_at": entry.get("expires_at", ""),
                "days_left": round(days_left, 1) if days_left is not None else None,
                "pinned": entry["pinned"],
                "verifies_now": report["ok"],
                "recheck": _recheck_state(report),
            }
    return {
        "library_dir": str(library.directory),
        "library_exists": library.directory.is_dir(),
        "trusted_keys": str(trusted_keys_path),
        "active": active,
        "counts": {
            "total": len(state["entries"]),
            "pinned": sum(1 for entry in state["entries"] if entry["pinned"]),
        },
        "history_records": len(state["history"]),
        "active_bundle_file": (
            ACTIVE_BUNDLE_FILENAME if library.active_bundle_path.is_file() else ""
        ),
        "problems": problems,
    }


def list_report(
    library: BundleLibrary,
    trusted_keys_path: str | Path = "",
    audience_ids: Sequence[str] | None = None,
    now: float | None = None,
) -> dict:
    import time as _time

    if now is None:
        now = _time.time()
    state, problems = read_state(library)
    entries = []
    for entry in sorted(state["entries"], key=lambda item: (item["name"], item["sha256"])):
        stored = library.stored_path(entry)
        if stored.is_file():
            report = verify_bundle_file(stored, trusted_keys_path, audience_ids, now=now)
            recheck = _recheck_state(report)
        else:
            recheck = "file-missing"
        entries.append(
            {
                "sha256": entry["sha256"],
                "name": entry["name"],
                "issuer_key_id": entry.get("issuer_key_id", ""),
                "audience": entry.get("audience", []),
                "expires_at": entry.get("expires_at", ""),
                "added_at": entry.get("added_at", ""),
                "source": entry.get("source", ""),
                "active": entry["sha256"] == state["active_sha256"],
                "pinned": entry["pinned"],
                "state": recheck,
            }
        )
    return {"library_dir": str(library.directory), "entries": entries, "problems": problems}


def inspect_report(
    library: BundleLibrary,
    ref: str,
    trusted_keys_path: str | Path = "",
    audience_ids: Sequence[str] | None = None,
    now: float | None = None,
) -> dict:
    import time as _time

    if now is None:
        now = _time.time()
    state, problems = read_state(library)
    if problems:
        raise BundleLibraryError("inspect refused: " + "; ".join(problems[:3]) + f" -- {REBUILD_GUIDANCE}")
    entry = _resolve_entry(state, ref)
    stored = library.stored_path(entry)
    document: dict | None = None
    if stored.is_file():
        document = _bundle_document(stored.read_bytes())
        report = verify_bundle_file(stored, trusted_keys_path, audience_ids, now=now)
    else:
        report = {"ok": False, "code": 0, "refusal": "stored-file-missing", "message": ""}
    profiles = document.get("profiles") if document and isinstance(document.get("profiles"), dict) else {}
    profile_rules = {
        name: {
            "visible_rules": len(spec.get("visible") or []) if isinstance(spec, dict) else 0,
            "callable_rules": len(spec.get("callable") or []) if isinstance(spec, dict) else 0,
        }
        for name, spec in profiles.items()
    }
    return {
        "sha256": entry["sha256"],
        "name": entry["name"],
        "file": entry["file"],
        "source": entry.get("source", ""),
        "added_at": entry.get("added_at", ""),
        "pinned": entry["pinned"],
        "active": entry["sha256"] == state["active_sha256"],
        "issuer_key_id": entry.get("issuer_key_id", ""),
        "audience": entry.get("audience", []),
        "issued_at": entry.get("issued_at", ""),
        "expires_at": entry.get("expires_at", ""),
        "default_profile": str(document.get("default_profile", "")) if document else "",
        "allowed_upstream_namespaces": (
            list(document.get("allowed_upstream_namespaces", [])) if document else []
        ),
        "profiles": profile_rules,
        "verification": {
            "ok": report["ok"],
            "code": report["code"],
            "refusal": report["refusal"],
            "state": (
                "stored-file-missing"
                if report["refusal"] == "stored-file-missing"
                else _recheck_state(report)
            ),
        },
    }


# ---------------------------------------------------------------------------
# doctor: re-verify everything against the CURRENT trust store/CRL.


def doctor_report(
    library: BundleLibrary,
    trusted_keys_path: str | Path = "",
    audience_ids: Sequence[str] | None = None,
    now: float | None = None,
) -> dict:
    """Offline library self-check; exit 0 ok / 1 problems.

    PROBLEMS (exit 1): a corrupt/unreadable state file (with rebuild
    guidance), an entry whose stored file is missing or whose bytes no
    longer match the recorded sha256 (corruption -- the signature would
    refuse anyway, but say it plainly), an ACTIVE bundle that no longer
    verifies (the gateway would fail closed at its next start), an active
    pointer file whose bytes do not match the active entry, an active sha
    with no library entry, an active sha never recorded in the history.

    WARNINGS (exit 0): non-active entries that no longer verify (expired /
    revoked / key-missing -- they only block activation), orphan
    ``*.bundle.json`` files in the library dir that no entry references,
    history records naming entries no longer installed, an active entry set
    while ``active.bundle.json`` is missing.
    """
    import time as _time

    if now is None:
        now = _time.time()
    problems: list[str] = []
    warnings: list[str] = []
    checks: list[dict] = []

    def check(name: str, ok: bool, detail: str = "") -> None:
        checks.append({"check": name, "ok": ok, "detail": detail})

    if not library.directory.is_dir():
        check("library_dir", True, "no bundle library (nothing to check)")
        return {
            "library_dir": str(library.directory),
            "status": "ok",
            "checks": checks,
            "problems": problems,
            "warnings": warnings,
            "exit_code": 0,
        }
    check("library_dir", True, str(library.directory))

    state, state_problems = read_state(library)
    if state_problems:
        detail = "; ".join(state_problems[:5]) + f" -- {REBUILD_GUIDANCE}"
        check("state_file", False, detail)
        problems.extend(state_problems)
        problems.append(REBUILD_GUIDANCE)
    else:
        check("state_file", True, f"{len(state['entries'])} entr(ies), {len(state['history'])} history record(s)")

    active_sha = state["active_sha256"]
    entry_files: set[str] = set()
    entry_results: list[str] = []
    entry_problem_found = False
    for entry in state["entries"]:
        label = f"{entry['sha256'][:SHA_PREFIX_CHARS]} ({entry['name']})"
        entry_files.add(entry["file"])
        stored = library.stored_path(entry)
        is_active = entry["sha256"] == active_sha
        if not stored.is_file():
            problems.append(f"entry {label}: stored file {entry['file']} is missing")
            entry_results.append(f"{label}: file-missing")
            entry_problem_found = True
            continue
        actual_sha = hashlib.sha256(stored.read_bytes()).hexdigest()
        if actual_sha != entry["sha256"]:
            problems.append(
                f"entry {label}: stored bytes no longer match the recorded sha256 "
                "(corrupt or edited; stored bundles are immutable)"
            )
            entry_results.append(f"{label}: corrupt")
            entry_problem_found = True
            continue
        report = verify_bundle_file(stored, trusted_keys_path, audience_ids, now=now)
        recheck = _recheck_state(report)
        entry_results.append(f"{label}: {recheck}" + (" [active]" if is_active else ""))
        if report["ok"]:
            continue
        message = (
            f"entry {label} no longer verifies against the current trust store "
            f"({report['code']} {report['refusal']})"
        )
        if is_active:
            problems.append(
                f"ACTIVE {message}; the gateway would fail closed at its next start "
                "-- rollback or activate a verifying bundle"
            )
            entry_problem_found = True
        else:
            warnings.append(f"{message}; it cannot be activated or rolled back to")
    check("entries_reverified", not entry_problem_found, "; ".join(entry_results) or "no entries")

    # Active pointer consistency.
    if active_sha:
        entry = next((item for item in state["entries"] if item["sha256"] == active_sha), None)
        if entry is None:
            detail = f"active_sha256 {active_sha[:SHA_PREFIX_CHARS]} has no library entry"
            check("active_pointer", False, detail)
            problems.append(detail)
        elif not library.active_bundle_path.is_file():
            detail = (
                f"{ACTIVE_BUNDLE_FILENAME} is missing while {active_sha[:SHA_PREFIX_CHARS]} "
                "is recorded active; re-run activate"
            )
            check("active_pointer", False, detail)
            warnings.append(detail)
        else:
            pointer_sha = hashlib.sha256(library.active_bundle_path.read_bytes()).hexdigest()
            if pointer_sha != active_sha:
                detail = (
                    f"{ACTIVE_BUNDLE_FILENAME} bytes do not match the active entry "
                    f"{active_sha[:SHA_PREFIX_CHARS]} (stale or tampered pointer copy); "
                    "re-run activate"
                )
                check("active_pointer", False, detail)
                problems.append(detail)
            else:
                check("active_pointer", True, f"{ACTIVE_BUNDLE_FILENAME} matches the active entry")
    else:
        if library.active_bundle_path.is_file():
            detail = (
                f"{ACTIVE_BUNDLE_FILENAME} exists but no bundle is recorded active; "
                "deactivate again or activate a bundle"
            )
            check("active_pointer", False, detail)
            problems.append(detail)
        else:
            check("active_pointer", True, "no active bundle")

    # Orphan files: *.bundle.json in the library dir no entry references.
    orphans = sorted(
        path.name
        for path in library.directory.glob("*.bundle.json")
        if path.name not in entry_files and path.name != ACTIVE_BUNDLE_FILENAME
    )
    for orphan in orphans:
        warnings.append(f"orphan file {orphan} is not referenced by any library entry")
    check("orphan_files", True, "; ".join(orphans) or "none")

    # History consistency.
    known = {entry["sha256"] for entry in state["entries"]}
    history_unknown = sorted(
        {record["sha256"][:SHA_PREFIX_CHARS] for record in state["history"] if record["sha256"] not in known}
    )
    for sha in history_unknown:
        warnings.append(f"history names bundle {sha} that is no longer installed")
    if active_sha and not any(
        record["sha256"] == active_sha and record["action"] in (ACTION_ACTIVATE, ACTION_ROLLBACK)
        for record in state["history"]
    ):
        detail = (
            f"active bundle {active_sha[:SHA_PREFIX_CHARS]} has no activation record "
            "in the history (state edited by hand?)"
        )
        check("history_consistency", False, detail)
        problems.append(detail)
    else:
        check("history_consistency", True, f"{len(state['history'])} record(s)")

    status = "problems" if problems else "ok"
    return {
        "library_dir": str(library.directory),
        "status": status,
        "checks": checks,
        "problems": problems,
        "warnings": warnings,
        "exit_code": 1 if problems else 0,
    }


# ---------------------------------------------------------------------------
# Human renderers (text mode; --json prints the report dicts verbatim).
# Source paths appear as basenames only; key material never appears at all.


def format_status(report: dict) -> str:
    lines = [f"MCP bundle library: {report['library_dir']}"]
    active = report["active"]
    if active:
        days = active["days_left"]
        days_text = f"{days} day(s) left" if days is not None else "expiry unknown"
        lines.append(
            f"active: {active['sha256'][:SHA_PREFIX_CHARS]} ({active['name']}) -- "
            f"issuer {active['issuer_key_id']}, expires {active['expires_at']} "
            f"({days_text}), recheck={active['recheck']}"
        )
    else:
        lines.append("active: none (a gateway without --profile-bundle runs in open mode)")
    counts = report["counts"]
    lines.append(f"entries: {counts['total']} total, {counts['pinned']} pinned")
    lines.append(f"trust store in use: {report['trusted_keys'] or '<none configured>'}")
    if report["problems"]:
        lines.append("problems:")
        lines.extend(f"  - {problem}" for problem in report["problems"])
    else:
        lines.append("problems: none")
    return "\n".join(lines)


def format_list(report: dict) -> str:
    lines = [f"MCP bundle library: {report['library_dir']}"]
    if not report["entries"]:
        lines.append("no bundles installed")
    for entry in report["entries"]:
        flags = "".join(
            [" [active]" if entry["active"] else "", " [pinned]" if entry["pinned"] else ""]
        )
        lines.append(
            f"  {entry['sha256'][:SHA_PREFIX_CHARS]} {entry['name']}: state={entry['state']}"
            f"{flags} issuer={entry['issuer_key_id']} expires={entry['expires_at']} "
            f"added={entry['added_at']} source={entry['source']}"
        )
    if report["problems"]:
        lines.append("problems:")
        lines.extend(f"  - {problem}" for problem in report["problems"])
    return "\n".join(lines)


def format_inspect(report: dict) -> str:
    verification = report["verification"]
    verdict = (
        "verifies now"
        if verification["ok"]
        else f"REFUSED now ({verification['code']} {verification['refusal']})"
    )
    lines = [
        f"bundle {report['sha256']} ({report['name']})",
        f"file: {report['file']} (source {report['source']}, added {report['added_at']})",
        f"active: {report['active']}; pinned: {report['pinned']}",
        f"issuer: {report['issuer_key_id']}; audience: [{', '.join(report['audience'])}]",
        f"validity: {report['issued_at']} .. {report['expires_at']}",
        f"default_profile: {report['default_profile'] or '<none>'}",
        f"namespace ceiling: {len(report['allowed_upstream_namespaces'])} rule(s)",
        "profiles: "
        + (
            ", ".join(
                f"{name} ({spec['visible_rules']}v/{spec['callable_rules']}c)"
                for name, spec in sorted(report["profiles"].items())
            )
            or "<none>"
        ),
        f"current re-verification: {verdict}",
    ]
    return "\n".join(lines)


def format_doctor(report: dict) -> str:
    lines = [f"MCP bundle library doctor: {report['library_dir']} -- {report['status']}"]
    for item in report["checks"]:
        mark = "ok" if item["ok"] else "PROBLEM"
        detail = f": {item['detail']}" if item["detail"] else ""
        lines.append(f"  [{mark}] {item['check']}{detail}")
    for warning in report["warnings"]:
        lines.append(f"  warning: {warning}")
    for problem in report["problems"]:
        lines.append(f"  problem: {problem}")
    return "\n".join(lines)
