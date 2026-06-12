"""Managed profile sync client PROTOTYPE (E27, fixture-only).

A local, fixture-only client that simulates how a future registered/team
profile assignment would be RECEIVED, VERIFIED, STORED, PREVIEWED, and
optionally STAGED into the local bundle library -- without real hosted
sync, registry API calls, entitlement server calls, or production signing
keys. The "registry" is a plain local directory in the E26 fixture layout
(``scripts/run-mcp-profile-distribution-fixture-e2e.py``): content-addressed
bundle bodies under ``bundles/``, carrier-signed metadata-only summaries
under ``summaries/``, and the verbatim E23 channel/assignment documents
under ``channels/`` and ``assignments/``. Anything that looks like a URL is
refused outright: hosted sync is NOT implemented and stays design-gated
behind the E23/E24 contracts -- only the transport may change later, never
the verification or the rules in this module.

Offline by construction: no network, no hosted calls, no telemetry, no
OAuth, no production keys. The sync state file contains identifiers, hashes,
and revisions only -- never key material, rule text, or local paths.

Behavior contract (``unlimited-skills mcp profiles managed ...``):

- **DEFAULT IS DRY-RUN.** ``sync`` without ``--apply`` reads the source,
  resolves the member's assignment with the E23 decision-6 conflict rules,
  verifies everything (routing signatures against the E15 trust store,
  the carrier summary against the source's own carrier keys, the full
  REAL E14 verification on the candidate bundle), and reports what WOULD
  change -- without touching the library, the trust store, or the sync
  state file. Zero mutation, provable.
- **``--apply`` stages, never activates.** A verified candidate is added
  to the E20 library through the real ``add_bundle`` (verify-before-store,
  content-addressed, idempotent on duplicate sha). Activation stays a
  SEPARATE explicit step (``mcp profiles library activate``): a sync
  client that silently activated would let a compromised or merely stale
  routing layer flip a fleet's enforcement without any human in the loop,
  so no code path here writes the active pointer, ever.
- **Anti-rollback watermarks.** The state file records the highest channel
  ``revision`` applied per channel identity (``name`` + owner ``key_id``).
  A source presenting a LOWER revision refuses the whole sync loudly with
  ``routing_revision_regression`` and the state stays untouched.
- **Fail-closed.** Every refusal is loud and exact: routing-layer refusals
  carry the E26 fixture reason names (``routing_signature_invalid``,
  ``routing_revision_regression``, ``unsigned_artifact_rejected``, ...);
  bundle verification refusals carry the unchanged reserved codes
  ``-32014``..``-32019``. No new numeric codes are invented here.

The routing-document loaders, the strict/forbidden-field checks, the E23
decision-6 conflict resolution, and the carrier-summary loader in this
module are the SHARED client pieces the E26 harness imports back -- the
harness's abuse battery is their regression suite.
"""

from __future__ import annotations

import base64
import hashlib
import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence

from .bundle_library import (
    BundleLibrary,
    BundleLibraryError,
    add_bundle,
    read_state,
    verify_bundle_file,
)
from .bundles import (
    CryptographyEd25519Backend,
    CrlError,
    TrustedKeysError,
    _load_crl,
    _parse_timestamp,
    canonical_bundle_bytes,
    load_trusted_keys,
    local_audience_ids,
)
from .trust_store import SHA256_RE, _atomic_write_json

SYNC_DIRNAME = ".unlimited-skills-managed-sync"
STATE_FILENAME = "state.json"
SHA_PREFIX_CHARS = 12

# The E23 conflict-resolution scheme specificity (decision 6, rung a).
SCHEME_RANK = {"host": 3, "team": 2, "org": 1}

# Anything URL-shaped refuses: hosted sync is design-gated (E23/E24).
_URL_RE = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*://")

# The E24 decision-20 forbidden-field denylist, encoded LOCALLY (the private
# registry contract is never read at run time). No routing payload may carry
# one of these property names at any depth -- the same boundary check the
# future hosted carrier must enforce.
FORBIDDEN_FIELDS = frozenset(
    {
        "prompt",
        "prompts",
        "task_text",
        "query",
        "messages",
        "tool_arguments",
        "tool_args",
        "tool_input",
        "tool_inputs",
        "tool_output",
        "tool_outputs",
        "tool_results",
        "tool_calls",
        "profile_rules",
        "profile_body",
        "bundle_body",
        "skill_body",
        "skill_bodies",
        "audit_log",
        "usage",
        "telemetry",
        "activation_history",
        "private_key",
        "private_keys",
        "signing_key",
        "key_material",
        "license_token",
        "registration_token",
        "device_proof",
        "join_code",
        "team_token",
        "local_path",
        "local_paths",
        "env",
        "env_values",
        "secret",
        "secrets",
    }
)

# Strict top-level vocabularies (closed-schema stance: unknown keys refuse).
_CHANNEL_KEYS = frozenset(
    {"channel_version", "comment", "name", "revision", "owner", "history", "current", "signature"}
)
_ASSIGNMENT_KEYS = frozenset(
    {
        "assignment_version",
        "comment",
        "audience",
        "channel",
        "mode",
        "bundle_sha256",
        "issuer",
        "revision",
        "issued_at",
        "expires_at",
        "signature",
    }
)
_SUMMARY_KEYS = frozenset(
    {
        "summary_version",
        "comment",
        "bundle_sha256",
        "issuer_key_id",
        "audience_schemes",
        "published_at",
        "expires_at",
        "size_bytes",
        "status",
        "signature",
    }
)

_STATE_TOP = frozenset(
    {
        "schema_version",
        "comment",
        "source_id",
        "source_hash",
        "watermarks",
        "last_sync",
        "last_good_bundle_sha256",
    }
)
_LAST_SYNC_KEYS = frozenset(
    {
        "at",
        "result",
        "assignment",
        "channel",
        "channel_owner_key_id",
        "channel_revision",
        "bundle_sha256",
        "applied",
    }
)


class DistributionRefusal(ValueError):
    """A distribution/sync-layer refusal with a stable reason name.

    ``reason`` is the E26 fixture reason vocabulary (plus the sync-client
    additions documented in docs/mcp-managed-sync.md). ``code`` carries the
    reserved E14 refusal code when the refusal came from real bundle
    verification (0 otherwise) -- never a newly invented numeric code.
    """

    def __init__(self, reason: str, message: str, code: int = 0) -> None:
        super().__init__(message)
        self.reason = reason
        self.code = code


def forbidden_field_names(value: object) -> set[str]:
    """Every E24 decision-20 denylisted property name present at any depth."""
    found: set[str] = set()
    if isinstance(value, dict):
        for key, item in value.items():
            if key in FORBIDDEN_FIELDS:
                found.add(key)
            found |= forbidden_field_names(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            found |= forbidden_field_names(item)
    return found


def _strict_document(document: object, allowed: frozenset[str], label: str) -> dict:
    if not isinstance(document, dict):
        raise DistributionRefusal("schema_invalid", f"{label}: not a JSON object")
    # The decision-20 boundary check runs FIRST: a denylisted name refuses
    # with the specific code even when it is also an unknown key.
    found = forbidden_field_names(document)
    if found:
        raise DistributionRefusal(
            "forbidden_field_rejected",
            f"{label}: forbidden field names refused: {', '.join(sorted(found))}",
        )
    unknown = sorted(set(document) - allowed)
    if unknown:
        raise DistributionRefusal(
            "schema_invalid", f"{label}: unknown keys refused: {', '.join(unknown)}"
        )
    return document


def channel_semantic_errors(document: dict) -> list[str]:
    """The E23 semantic load rules (tests/test_mcp_distribution_schemas.py)."""
    errors: list[str] = []
    if document.get("channel_version") != 1:
        errors.append("channel_version must be the const 1")
    history = document.get("history")
    if not isinstance(history, list) or not history:
        return errors + ["history must be a non-empty array"]
    active = [record for record in history if record.get("status") == "active"]
    if len(active) != 1:
        errors.append(f"history must contain exactly one active record, found {len(active)}")
    elif document.get("current") != active[0].get("bundle_sha256"):
        errors.append("current must equal the active record's bundle_sha256")
    stamps = [record.get("published_at", "") for record in history]
    if any(later < earlier for earlier, later in zip(stamps, stamps[1:])):
        errors.append("history published_at must be non-decreasing")
    return errors


def assignment_semantic_errors(document: dict) -> list[str]:
    errors: list[str] = []
    if document.get("assignment_version") != 1:
        errors.append("assignment_version must be the const 1")
    mode = document.get("mode")
    if mode == "pin" and "bundle_sha256" not in document:
        errors.append("pin mode requires bundle_sha256")
    if mode == "follow" and "bundle_sha256" in document:
        errors.append("follow mode forbids bundle_sha256 (the channel owns the pointer)")
    if not document.get("issued_at", "") < document.get("expires_at", ""):
        errors.append("issued_at must be strictly before expires_at")
    return errors


def _routing_crl(crl_path: Path | str) -> tuple[frozenset[str], frozenset[str]]:
    """The member's local CRL for ROUTING-document checks.

    No CRL file configured/present means nothing is locally revoked (the
    E15 store's own stance). A PRESENT but unreadable/corrupt CRL stays the
    fail-closed :class:`CrlError` -- "cannot prove not-revoked" never
    degrades to "trusted".
    """
    if not str(crl_path) or not Path(crl_path).is_file():
        return frozenset(), frozenset()
    return _load_crl(Path(crl_path))


def verify_routing_document(
    document: dict,
    kind: str,
    trusted_keys_path: Path,
    crl_path: Path,
    now: float,
) -> str:
    """Client check of one routing file under the SIGNED-DISTRIBUTION policy
    (E23 decision 1, registered tier): strict keys, the semantic load rules,
    a REQUIRED signature whose key_id equals the owner/issuer key_id, the
    key present and unexpired in the member's E15 trusted-keys file, not
    revoked by the local CRL, and a valid detached Ed25519 signature over
    the canonical JSON. Returns the verified key_id or raises
    :class:`DistributionRefusal` -- routing files grant no capability either
    way (the routed bundle still passes the unchanged E14 verification)."""
    if kind == "channel":
        _strict_document(document, _CHANNEL_KEYS, "channel")
        errors = channel_semantic_errors(document)
        owner_key_id = str(document.get("owner", {}).get("key_id", ""))
    else:
        _strict_document(document, _ASSIGNMENT_KEYS, "assignment")
        errors = assignment_semantic_errors(document)
        owner_key_id = str(document.get("issuer", {}).get("key_id", ""))
    if errors:
        raise DistributionRefusal("schema_invalid", f"{kind}: {errors[0]}")
    signature = document.get("signature")
    if not isinstance(signature, dict):
        raise DistributionRefusal(
            "routing_unsigned",
            f"{kind} is unsigned; the signed-distribution policy refuses unsigned "
            "routing files outright",
        )
    if signature.get("key_id") != owner_key_id:
        raise DistributionRefusal(
            "routing_signature_invalid",
            f"{kind} signature key_id does not equal the owner/issuer key_id",
        )
    keys = load_trusted_keys(trusted_keys_path)
    entry = keys.get(owner_key_id)
    if entry is None or (entry.not_after is not None and now > entry.not_after):
        raise DistributionRefusal(
            "routing_key_missing",
            f"{kind} signing key is not in the member's trusted-keys file (or expired)",
        )
    _, revoked_key_ids = _routing_crl(crl_path)
    if owner_key_id in revoked_key_ids:
        raise DistributionRefusal(
            "routing_key_revoked", f"{kind} signing key is revoked by the local CRL"
        )
    try:
        raw_signature = base64.b64decode(str(signature.get("value", "")), validate=True)
    except (ValueError, TypeError):
        raise DistributionRefusal(
            "routing_signature_invalid", f"{kind} signature value is not valid base64"
        ) from None
    backend = CryptographyEd25519Backend()
    if not backend.verify(entry.public_key, canonical_bundle_bytes(document), raw_signature):
        raise DistributionRefusal(
            "routing_signature_invalid",
            f"{kind} signature does not verify (tampered after signing)",
        )
    return owner_key_id


def resolve_assignments(
    entries: list[tuple[str, dict]], member_ids: list[str], now: float
) -> tuple[str, str, list[str]]:
    """The E23 decision-6 deterministic conflict resolution.

    ``entries`` are ``(label, assignment document)`` pairs that already
    passed :func:`verify_routing_document`. Returns ``(status, winner_label,
    detail_labels)`` with status ``none`` (no assignment matches the member),
    ``expired`` (matches exist but every one is expired -- no NEW activation
    is directed, named loudly), ``tie`` (residual exact tie, refused loudly
    with both labels), or ``ok`` with the single deterministic winner:
    host: beats team: beats org:, then pin beats follow, then highest
    revision, then latest issued_at.
    """
    member = set(member_ids)
    matching = [
        (label, document)
        for label, document in entries
        if set(document.get("audience", [])) & member
    ]
    if not matching:
        return ("none", "", [])
    live = [
        (label, document)
        for label, document in matching
        if now < _parse_timestamp(document["expires_at"])
    ]
    if not live:
        return ("expired", "", sorted(label for label, _ in matching))

    def sort_key(label: str, document: dict) -> tuple:
        specificity = max(
            SCHEME_RANK[identifier.split(":", 1)[0]]
            for identifier in set(document["audience"]) & member
        )
        return (
            specificity,
            1 if document["mode"] == "pin" else 0,
            document["revision"],
            document["issued_at"],
        )

    best = max(sort_key(label, document) for label, document in live)
    winners = sorted(
        label for label, document in live if sort_key(label, document) == best
    )
    if len(winners) > 1:
        return ("tie", "", winners)
    return ("ok", winners[0], [])


def load_summary_document(raw: object, carrier_public_keys: dict[str, bytes]) -> dict:
    """Strict client-side loader for the carrier-signed summary: closed key
    set, forbidden-field boundary, and a REQUIRED carrier signature verified
    against the source's own carrier public keys (never the member's trust
    store -- carrier trust and capability trust stay separate)."""
    document = _strict_document(raw, _SUMMARY_KEYS, "summary")
    if document.get("summary_version") != 1:
        raise DistributionRefusal("schema_invalid", "summary_version must be the const 1")
    signature = document.get("signature")
    if not isinstance(signature, dict):
        raise DistributionRefusal(
            "unsigned_artifact_rejected",
            "summary is unsigned; the carrier envelope signature is required "
            "(downgrade-to-unsigned refused)",
        )
    public_key = carrier_public_keys.get(str(signature.get("key_id", "")))
    if public_key is None:
        raise DistributionRefusal(
            "routing_key_missing", "summary signed by an unknown carrier key"
        )
    try:
        raw_signature = base64.b64decode(str(signature.get("value", "")), validate=True)
    except (ValueError, TypeError):
        raise DistributionRefusal(
            "routing_signature_invalid", "summary signature value is not valid base64"
        ) from None
    backend = CryptographyEd25519Backend()
    if not backend.verify(public_key, canonical_bundle_bytes(document), raw_signature):
        raise DistributionRefusal(
            "routing_signature_invalid", "summary signature does not verify"
        )
    return document


# ---------------------------------------------------------------------------
# The fixture SOURCE: a local directory in the E26 fixture-registry layout.
# Explicitly NOT a transport client: file reads only, no network imports, no
# daemon, no schedule. URL-shaped sources refuse before anything is read.


HOSTED_GATED_MESSAGE = (
    "hosted sync is not implemented; the registered/team transport is design "
    "gated behind the E23/E24 contracts -- pass a LOCAL fixture-source "
    "directory in the E26 layout instead"
)


class FixtureSource:
    """Read-only view over one fixture-source directory (E26 layout)."""

    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self.bundles_dir = self.root / "bundles"
        self.summaries_dir = self.root / "summaries"
        self.channels_dir = self.root / "channels"
        self.assignments_dir = self.root / "assignments"

    def validate_layout(self) -> None:
        if not self.root.is_dir():
            raise DistributionRefusal(
                "source_invalid", "the fixture-source directory does not exist"
            )
        missing = sorted(
            directory.name
            for directory in (self.assignments_dir, self.channels_dir, self.bundles_dir)
            if not directory.is_dir()
        )
        if missing:
            raise DistributionRefusal(
                "source_invalid",
                "the fixture-source directory is not in the E26 layout "
                f"(missing: {', '.join(missing)})",
            )

    def _read_json(self, path: Path, label: str) -> object:
        try:
            raw = path.read_bytes()
        except OSError:
            raise DistributionRefusal(
                "source_invalid", f"{label} is missing or unreadable in the source"
            ) from None
        try:
            return json.loads(raw.decode("utf-8-sig", errors="replace"))
        except json.JSONDecodeError:
            raise DistributionRefusal(
                "schema_invalid", f"{label} is not valid JSON"
            ) from None

    def carrier_public_keys(self) -> dict[str, bytes]:
        document = self._read_json(self.root / "public-keys.json", "public-keys.json")
        if not isinstance(document, dict) or document.get("schema_version") != 1:
            raise DistributionRefusal(
                "schema_invalid", "public-keys.json must be an object with schema_version 1"
            )
        keys: dict[str, bytes] = {}
        entries = document.get("keys")
        if not isinstance(entries, list) or not entries:
            raise DistributionRefusal(
                "schema_invalid", "public-keys.json must list at least one carrier key"
            )
        for entry in entries:
            if (
                not isinstance(entry, dict)
                or entry.get("algorithm") != "ed25519"
                or not isinstance(entry.get("key_id"), str)
                or not isinstance(entry.get("public_key"), str)
            ):
                raise DistributionRefusal(
                    "schema_invalid", "public-keys.json carries a malformed carrier key"
                )
            try:
                keys[entry["key_id"]] = base64.b64decode(entry["public_key"], validate=True)
            except (ValueError, TypeError):
                raise DistributionRefusal(
                    "schema_invalid", "public-keys.json carrier key is not valid base64"
                ) from None
        return keys

    def assignments(self) -> list[tuple[str, dict]]:
        entries: list[tuple[str, dict]] = []
        for path in sorted(self.assignments_dir.glob("*.assignment.json")):
            label = path.name[: -len(".assignment.json")]
            document = self._read_json(path, path.name)
            if not isinstance(document, dict):
                raise DistributionRefusal(
                    "schema_invalid", f"{path.name}: not a JSON object"
                )
            entries.append((label, document))
        return entries

    def channel(self, name: str, owner_key_id: str) -> dict:
        path = self.channels_dir / f"{owner_key_id}.{name}.channel.json"
        if not path.is_file():
            raise DistributionRefusal(
                "channel_missing",
                f"the source has no channel document for '{name}' owned by "
                f"'{owner_key_id}' (the assignment's full identity pair)",
            )
        document = self._read_json(path, path.name)
        if not isinstance(document, dict):
            raise DistributionRefusal("schema_invalid", f"{path.name}: not a JSON object")
        return document

    def summary(self, bundle_sha256: str) -> object:
        path = self.summaries_dir / f"{bundle_sha256}.summary.json"
        if not path.is_file():
            raise DistributionRefusal(
                "source_invalid",
                "the source carries no carrier summary for the candidate bundle "
                f"{bundle_sha256[:SHA_PREFIX_CHARS]} (metadata-only summaries are "
                "part of the carrier contract)",
            )
        return self._read_json(path, path.name)

    def bundle_path(self, bundle_sha256: str) -> Path:
        path = self.bundles_dir / f"{bundle_sha256}.bundle.json"
        if not path.is_file():
            raise DistributionRefusal(
                "source_invalid",
                "the source carries no bundle body for the candidate "
                f"{bundle_sha256[:SHA_PREFIX_CHARS]}",
            )
        data = path.read_bytes()
        if hashlib.sha256(data).hexdigest() != bundle_sha256:
            raise DistributionRefusal(
                "content_address_mismatch",
                "stored source bytes do not match the requested content address",
            )
        return path

    def fingerprint(self) -> str:
        """SHA-256 over the sorted (basename, content sha) routing inventory.

        A stable content identity for "did the source change since the last
        sync" -- basenames and hashes only, never absolute paths.
        """
        lines: list[str] = []
        for directory in (self.channels_dir, self.assignments_dir, self.summaries_dir):
            if not directory.is_dir():
                continue
            for path in sorted(directory.glob("*.json")):
                digest = hashlib.sha256(path.read_bytes()).hexdigest()
                lines.append(f"{path.name}:{digest}")
        return hashlib.sha256("\n".join(lines).encode("utf-8")).hexdigest()


def refuse_url_source(source: str) -> None:
    """Refuse anything URL-shaped: hosted sync is design-gated (E23/E24)."""
    if _URL_RE.match(str(source).strip()):
        raise DistributionRefusal("source_url_rejected", HOSTED_GATED_MESSAGE)


# ---------------------------------------------------------------------------
# Sync state file: <library>/.unlimited-skills-managed-sync/state.json,
# written atomically (the E15/E20 temp-file + os.replace pattern). Contents
# are identifiers, hashes, and revisions ONLY: source id (basename) and
# content fingerprint, per-channel revision watermarks, the last sync
# result, and the last-good bundle sha. Never key material, never rule
# text, never local paths.


def sync_state_path(library: BundleLibrary) -> Path:
    return library.directory / SYNC_DIRNAME / STATE_FILENAME


def _default_sync_state() -> dict:
    return {
        "schema_version": 1,
        "source_id": "",
        "source_hash": "",
        "watermarks": {},
        "last_sync": {},
        "last_good_bundle_sha256": "",
    }


def _utc_text(now: float) -> str:
    return datetime.fromtimestamp(now, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def watermark_key(name: str, owner_key_id: str) -> str:
    return f"{name}@{owner_key_id}"


def read_sync_state(path: Path) -> tuple[dict, list[str]]:
    """Tolerant read of the sync state: normalized state + problems.

    Reading tolerates damage so ``status``/``doctor`` can DESCRIBE a broken
    state; the mutating ``sync --apply`` path refuses on any problem.
    """
    state = _default_sync_state()
    path = Path(path)
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
    state["source_id"] = str(document.get("source_id", ""))
    source_hash = document.get("source_hash", "")
    if isinstance(source_hash, str) and (not source_hash or SHA256_RE.match(source_hash)):
        state["source_hash"] = source_hash
    else:
        problems.append(f"{STATE_FILENAME}: source_hash is malformed")
    watermarks = document.get("watermarks", {})
    if not isinstance(watermarks, dict):
        problems.append(f"{STATE_FILENAME}: 'watermarks' must be an object")
        watermarks = {}
    cleaned: dict[str, int] = {}
    for identity, revision in watermarks.items():
        if (
            not isinstance(identity, str)
            or "@" not in identity
            or not isinstance(revision, int)
            or isinstance(revision, bool)
            or revision < 1
        ):
            problems.append(
                f"{STATE_FILENAME}: watermark {str(identity)[:64]!r} is malformed "
                "(expected 'name@owner_key_id' -> revision >= 1)"
            )
            continue
        cleaned[identity] = revision
    state["watermarks"] = cleaned
    last_sync = document.get("last_sync", {})
    if not isinstance(last_sync, dict):
        problems.append(f"{STATE_FILENAME}: 'last_sync' must be an object")
        last_sync = {}
    state["last_sync"] = {key: last_sync[key] for key in _LAST_SYNC_KEYS if key in last_sync}
    sha = last_sync.get("bundle_sha256", "")
    if not isinstance(sha, str) or (sha and not SHA256_RE.match(sha)):
        problems.append(f"{STATE_FILENAME}: last_sync.bundle_sha256 is malformed")
        state["last_sync"].pop("bundle_sha256", None)
    last_good = document.get("last_good_bundle_sha256", "")
    if isinstance(last_good, str) and (not last_good or SHA256_RE.match(last_good)):
        state["last_good_bundle_sha256"] = last_good
    else:
        problems.append(f"{STATE_FILENAME}: last_good_bundle_sha256 is malformed")
    return state, problems


def _load_sync_state_strict(path: Path, operation: str) -> dict:
    state, problems = read_sync_state(path)
    if problems:
        raise DistributionRefusal(
            "state_invalid",
            f"{operation} refused: " + "; ".join(problems[:3]) + " -- move the "
            "sync state file aside and re-run sync against the source",
        )
    return state


# ---------------------------------------------------------------------------
# sync: resolve -> verify -> preview (dry-run default) -> optionally stage.


def _member_ids(audience_ids: Sequence[str] | None) -> list[str]:
    ids = local_audience_ids(audience_ids)
    if not ids:
        raise DistributionRefusal(
            "audience_unconfigured",
            "managed sync needs the member's audience identifiers; pass "
            "--audience-id (or set UNLIMITED_SKILLS_MCP_AUDIENCE)",
        )
    return ids


def sync_managed_profile(
    library: BundleLibrary,
    source: str | Path,
    trusted_keys_path: str | Path = "",
    crl_path: str | Path = "",
    audience_ids: Sequence[str] | None = None,
    apply: bool = False,
    now: float | None = None,
) -> dict:
    """One managed sync pass against a fixture-source directory.

    DRY-RUN by default: resolves, verifies, and reports without writing
    anything anywhere. With ``apply=True`` the verified candidate is staged
    into the E20 library (``add_bundle``: verify-before-store) and the sync
    state file is written atomically. Activation is NEVER performed here.
    Any refusal raises :class:`DistributionRefusal` and leaves the library,
    trust store, and state file untouched.
    """
    if now is None:
        now = time.time()
    refuse_url_source(str(source))
    fixture = FixtureSource(Path(source).expanduser())
    fixture.validate_layout()
    member_ids = _member_ids(audience_ids)
    if not str(trusted_keys_path):
        raise DistributionRefusal(
            "routing_key_missing",
            "managed sync needs the member's trusted-keys file; pass "
            "--trusted-keys or create the managed trust store (E15)",
        )
    state_path = sync_state_path(library)
    # The strict read runs for DRY-RUN too: previewing against a corrupt
    # watermark file would report a movement that apply must then refuse.
    state = _load_sync_state_strict(state_path, "sync")

    # 1. Receive + verify every assignment in the source (fail-closed: a
    #    tampered routing file anywhere refuses the whole sync loudly).
    try:
        entries = fixture.assignments()
        for label, document in entries:
            verify_routing_document(
                document, "assignment", Path(trusted_keys_path), Path(str(crl_path)), now
            )
    except TrustedKeysError as exc:
        raise DistributionRefusal("routing_key_missing", str(exc)) from None
    except CrlError as exc:
        raise DistributionRefusal("crl_unreadable", str(exc)) from None

    # 2. Resolve the member's assignment (E23 decision-6 conflict rules).
    status, winner_label, named = resolve_assignments(entries, member_ids, now)
    report: dict = {
        "synced": False,
        "dry_run": not apply,
        "source_id": fixture.root.name,
        "source_hash": fixture.fingerprint(),
        "member_audience": list(member_ids),
        "assignments_seen": len(entries),
        "resolution": status,
    }
    if status == "tie":
        raise DistributionRefusal(
            "assignment_tie",
            "assignment conflict tie refused; nothing staged, fix the routing "
            f"files: {', '.join(named)}",
        )
    if status in ("none", "expired"):
        report["expired_assignments"] = named
        report["note"] = (
            "no live assignment matches this member; nothing to stage"
            if status == "none"
            else "every matching assignment is EXPIRED; no new staging is "
            "directed (the active bundle keeps working until its own expiry)"
        )
        return report
    winner = dict(entries[[label for label, _ in entries].index(winner_label)][1])
    report["assignment"] = {
        "label": winner_label,
        "mode": winner["mode"],
        "revision": winner["revision"],
        "expires_at": winner["expires_at"],
    }

    # 3. Verify the channel and enforce the anti-rollback watermark.
    try:
        channel = fixture.channel(
            winner["channel"]["name"], winner["channel"]["owner_key_id"]
        )
        verify_routing_document(
            channel, "channel", Path(trusted_keys_path), Path(str(crl_path)), now
        )
    except TrustedKeysError as exc:
        raise DistributionRefusal("routing_key_missing", str(exc)) from None
    except CrlError as exc:
        raise DistributionRefusal("crl_unreadable", str(exc)) from None
    wanted = winner["channel"]
    if (
        channel["name"] != wanted["name"]
        or channel["owner"]["key_id"] != wanted["owner_key_id"]
    ):
        raise DistributionRefusal(
            "channel_identity_mismatch",
            "channel does not match the assignment's full identity pair "
            "(name + owner key id)",
        )
    identity = watermark_key(channel["name"], channel["owner"]["key_id"])
    applied_watermark = int(state["watermarks"].get(identity, 0))
    if channel["revision"] < applied_watermark:
        raise DistributionRefusal(
            "routing_revision_regression",
            f"the source presents channel revision {channel['revision']} below "
            f"the applied watermark {applied_watermark}; refusing the sync "
            "(possible replay) -- the state file is untouched",
        )
    report["channel"] = {
        "name": channel["name"],
        "owner_key_id": channel["owner"]["key_id"],
        "revision": channel["revision"],
        "watermark_before": applied_watermark,
        "watermark_after": max(applied_watermark, int(channel["revision"])),
    }

    # 4. Resolve the candidate pointer: pin wins over channel movement.
    candidate = (
        winner["bundle_sha256"] if winner["mode"] == "pin" else channel["current"]
    )
    report["bundle_sha256"] = candidate

    # 5. Carrier summary: metadata-only, carrier-signed, never capability.
    summary = load_summary_document(
        fixture.summary(candidate), fixture.carrier_public_keys()
    )
    if summary.get("bundle_sha256") != candidate:
        raise DistributionRefusal(
            "content_address_mismatch",
            "the carrier summary does not name the candidate content address",
        )
    if summary.get("status") == "revoked":
        raise DistributionRefusal(
            "bundle_revoked",
            "the carrier marks the candidate bundle revoked; refusing to stage "
            "(authoritative revocation stays the local E15 CRL either way)",
        )
    report["summary_status"] = str(summary.get("status", ""))

    # 6. Full REAL E14 verification on the candidate bundle body.
    bundle_path = fixture.bundle_path(candidate)
    verification = verify_bundle_file(
        bundle_path, trusted_keys_path, audience_ids=member_ids, now=now
    )
    if not verification["ok"]:
        raise DistributionRefusal(
            verification["refusal"],
            f"the candidate bundle does not verify ({verification['code']} "
            f"{verification['refusal']}): {verification['message']} -- nothing "
            "was staged",
            code=verification["code"],
        )
    report["verification"] = {"ok": True, "via": "resolve_bundle_state (E14)"}

    # 7. Preview against the library (no mutation yet).
    library_state, library_problems = read_state(library)
    if library_problems:
        raise DistributionRefusal(
            "state_invalid",
            "the bundle library state file has problems; run 'unlimited-skills "
            "mcp profiles library doctor' first",
        )
    already_staged = any(
        entry["sha256"] == candidate for entry in library_state["entries"]
    )
    active_sha = library_state["active_sha256"]
    report["would_stage"] = not already_staged
    report["already_staged"] = already_staged
    report["active_bundle_sha256"] = active_sha
    report["drift"] = bool(active_sha) and active_sha != candidate
    report["activation_note"] = (
        "managed sync NEVER activates; review and run 'unlimited-skills mcp "
        "profiles library activate <ref>' explicitly"
    )
    if not apply:
        return report

    # 8. --apply: stage through the REAL E20 add (verify-before-store), then
    #    record the sync state atomically. Still no activation, ever.
    if not already_staged:
        try:
            added = add_bundle(
                library,
                bundle_path,
                trusted_keys_path=trusted_keys_path,
                audience_ids=member_ids,
                name=f"managed-{candidate[:SHA_PREFIX_CHARS]}",
                now=now,
            )
        except BundleLibraryError as exc:
            raise DistributionRefusal(
                "library_add_refused",
                f"the library refused the staged add: {exc}",
                code=exc.code,
            ) from None
        report["staged_as"] = added["name"]
    state["source_id"] = fixture.root.name
    state["source_hash"] = report["source_hash"]
    state["watermarks"][identity] = report["channel"]["watermark_after"]
    state["last_sync"] = {
        "at": _utc_text(now),
        "result": "ok",
        "assignment": winner_label,
        "channel": channel["name"],
        "channel_owner_key_id": channel["owner"]["key_id"],
        "channel_revision": int(channel["revision"]),
        "bundle_sha256": candidate,
        "applied": True,
    }
    state["last_good_bundle_sha256"] = candidate
    _atomic_write_json(sync_state_path(library), state)
    report["synced"] = True
    report["state_file"] = f"{SYNC_DIRNAME}/{STATE_FILENAME}"
    return report


# ---------------------------------------------------------------------------
# status: the recorded sync state vs the library, offline.


def managed_status_report(
    library: BundleLibrary,
    trusted_keys_path: str | Path = "",
    audience_ids: Sequence[str] | None = None,
    now: float | None = None,
) -> dict:
    if now is None:
        now = time.time()
    state, problems = read_sync_state(sync_state_path(library))
    library_state, library_problems = read_state(library)
    problems = problems + [f"library: {problem}" for problem in library_problems]
    last_sync = state["last_sync"]
    expected = str(last_sync.get("bundle_sha256", ""))
    active = library_state["active_sha256"]
    staged_not_activated = sorted(
        {
            sha
            for sha in (expected, state["last_good_bundle_sha256"])
            if sha
            and sha != active
            and any(entry["sha256"] == sha for entry in library_state["entries"])
        }
    )
    drift: dict = {}
    if expected:
        drift = {
            "expected_bundle_sha256": expected,
            "active_bundle_sha256": active,
            "in_sync": bool(active) and active == expected,
        }
    return {
        "synced_ever": bool(last_sync),
        "source_id": state["source_id"],
        "source_hash": state["source_hash"],
        "watermarks": dict(state["watermarks"]),
        "last_sync": dict(last_sync),
        "last_good_bundle_sha256": state["last_good_bundle_sha256"],
        "staged_not_activated": staged_not_activated,
        "drift": drift,
        "trusted_keys": Path(str(trusted_keys_path)).name if str(trusted_keys_path) else "",
        "problems": problems,
    }


# ---------------------------------------------------------------------------
# last-good: show / re-stage the last-good bundle recorded by sync history.
# Restoring delegates to the REAL E20 machinery (add_bundle / verification)
# and never bypasses it; activation stays the explicit library step.


def last_good_report(
    library: BundleLibrary,
    trusted_keys_path: str | Path = "",
    audience_ids: Sequence[str] | None = None,
    restore: bool = False,
    source: str | Path = "",
    now: float | None = None,
) -> dict:
    if now is None:
        now = time.time()
    state, problems = read_sync_state(sync_state_path(library))
    sha = state["last_good_bundle_sha256"]
    if not sha:
        return {
            "last_good_bundle_sha256": "",
            "available": False,
            "restored": False,
            "note": "no managed sync history records a last-good bundle yet",
            "problems": problems,
            "exit_code": 1,
        }
    member_ids = local_audience_ids(audience_ids)
    library_state, _ = read_state(library)
    entry = next(
        (item for item in library_state["entries"] if item["sha256"] == sha), None
    )
    report: dict = {
        "last_good_bundle_sha256": sha,
        "available": entry is not None,
        "in_library": entry is not None,
        "active": library_state["active_sha256"] == sha,
        "restored": False,
        "problems": problems,
        "exit_code": 0,
    }
    if entry is not None:
        verification = verify_bundle_file(
            library.stored_path(entry), trusted_keys_path, member_ids or None, now=now
        )
        report["verifies_now"] = verification["ok"]
        if not verification["ok"]:
            report["refusal_code"] = verification["code"]
            report["refusal"] = verification["refusal"]
            report["exit_code"] = 1
        if restore and verification["ok"]:
            report["restored"] = True
            report["note"] = (
                "the last-good bundle is staged and verifies; activation stays "
                "the explicit step: 'unlimited-skills mcp profiles library "
                f"activate {entry['name']}'"
            )
        return report
    if not restore:
        report["note"] = (
            "the last-good bundle is no longer in the library; re-run with "
            "--restore --source <fixture dir> to re-stage it"
        )
        report["exit_code"] = 1
        return report
    if not str(source):
        raise DistributionRefusal(
            "source_invalid",
            "restore needs --source (the fixture-source directory) when the "
            "last-good bundle is no longer in the library",
        )
    refuse_url_source(str(source))
    fixture = FixtureSource(Path(source).expanduser())
    fixture.validate_layout()
    bundle_path = fixture.bundle_path(sha)
    try:
        added = add_bundle(
            library,
            bundle_path,
            trusted_keys_path=trusted_keys_path,
            audience_ids=member_ids or None,
            name=f"managed-{sha[:SHA_PREFIX_CHARS]}",
            now=now,
        )
    except BundleLibraryError as exc:
        raise DistributionRefusal(
            "library_add_refused",
            f"the library refused the re-stage: {exc}",
            code=exc.code,
        ) from None
    report["available"] = True
    report["in_library"] = True
    report["restored"] = True
    report["verifies_now"] = True
    report["staged_as"] = added["name"]
    report["note"] = (
        "re-staged through the real library add (verified before store); "
        "activation stays the explicit library step"
    )
    return report


# ---------------------------------------------------------------------------
# doctor: offline self-checks over the sync state, the staged bundles, and
# (optionally, with a source) replay detection and assignment expiry.


def managed_doctor_report(
    library: BundleLibrary,
    trusted_keys_path: str | Path = "",
    audience_ids: Sequence[str] | None = None,
    source: str | Path = "",
    expiring_days: int = 14,
    now: float | None = None,
) -> dict:
    if now is None:
        now = time.time()
    problems: list[str] = []
    warnings: list[str] = []
    checks: list[dict] = []

    def check(name: str, ok: bool, detail: str = "") -> None:
        checks.append({"check": name, "ok": ok, "detail": detail})

    state_path = sync_state_path(library)
    state, state_problems = read_sync_state(state_path)
    if not state_path.is_file():
        check("state_file", True, "no managed sync state (never synced)")
    elif state_problems:
        check("state_file", False, "; ".join(state_problems[:5]))
        problems.extend(state_problems)
    else:
        check(
            "state_file",
            True,
            f"{len(state['watermarks'])} watermark(s), last result "
            f"{str(state['last_sync'].get('result', '')) or 'none'}",
        )

    member_ids = local_audience_ids(audience_ids)
    library_state, library_problems = read_state(library)
    for problem in library_problems:
        warnings.append(f"library: {problem}")

    # Staged bundles recorded by the sync history must still verify.
    recorded = sorted(
        {
            sha
            for sha in (
                str(state["last_sync"].get("bundle_sha256", "")),
                state["last_good_bundle_sha256"],
            )
            if sha
        }
    )
    staged_results: list[str] = []
    staged_problem = False
    for sha in recorded:
        entry = next(
            (item for item in library_state["entries"] if item["sha256"] == sha), None
        )
        if entry is None:
            warnings.append(
                f"sync-recorded bundle {sha[:SHA_PREFIX_CHARS]} is no longer in "
                "the library (last-good --restore --source can re-stage it)"
            )
            staged_results.append(f"{sha[:SHA_PREFIX_CHARS]}: not-in-library")
            continue
        verification = verify_bundle_file(
            library.stored_path(entry), trusted_keys_path, member_ids or None, now=now
        )
        if verification["ok"]:
            staged_results.append(f"{sha[:SHA_PREFIX_CHARS]}: ok")
        else:
            staged_problem = True
            problems.append(
                f"sync-staged bundle {sha[:SHA_PREFIX_CHARS]} no longer verifies "
                f"({verification['code']} {verification['refusal']})"
            )
            staged_results.append(
                f"{sha[:SHA_PREFIX_CHARS]}: {verification['refusal']}"
            )
    check("staged_bundles", not staged_problem, "; ".join(staged_results) or "none recorded")

    # Drift: the assignment's expected bundle vs what is actually active.
    expected = str(state["last_sync"].get("bundle_sha256", ""))
    active = library_state["active_sha256"]
    if expected and active and active != expected:
        detail = (
            f"the last sync expected {expected[:SHA_PREFIX_CHARS]} but "
            f"{active[:SHA_PREFIX_CHARS]} is active (assignment points at one "
            "bundle, you run another)"
        )
        check("drift", True, detail)
        warnings.append(detail)
    elif expected and not active:
        detail = (
            f"the last sync staged {expected[:SHA_PREFIX_CHARS]} but no bundle "
            "is active (staged-not-activated; activate explicitly when ready)"
        )
        check("drift", True, detail)
        warnings.append(detail)
    else:
        check("drift", True, "active bundle matches the last sync" if expected else "never synced")

    # Source-backed checks (offline file reads; entirely optional).
    if str(source):
        refuse_url_source(str(source))
        fixture = FixtureSource(Path(source).expanduser())
        try:
            fixture.validate_layout()
        except DistributionRefusal as exc:
            check("source_layout", False, str(exc))
            problems.append(str(exc))
        else:
            check("source_layout", True, fixture.root.name)
            # Watermark monotonicity vs the source (replay detection).
            replay_found = False
            for identity, watermark in sorted(state["watermarks"].items()):
                name, _, owner_key_id = identity.partition("@")
                try:
                    channel = fixture.channel(name, owner_key_id)
                except DistributionRefusal:
                    warnings.append(
                        f"watermarked channel '{identity}' is absent from the "
                        "source (withheld or renamed)"
                    )
                    continue
                revision = channel.get("revision")
                if isinstance(revision, int) and revision < watermark:
                    replay_found = True
                    problems.append(
                        f"source channel '{identity}' presents revision "
                        f"{revision} BELOW the applied watermark {watermark} "
                        "(replay/rollback attempt; sync would refuse with "
                        "routing_revision_regression)"
                    )
            check(
                "watermark_monotonicity",
                not replay_found,
                f"{len(state['watermarks'])} watermark(s) compared",
            )
            # Assignment expiry warnings for this member.
            if member_ids:
                expiring: list[str] = []
                expired: list[str] = []
                try:
                    for label, document in fixture.assignments():
                        if not set(document.get("audience", [])) & set(member_ids):
                            continue
                        try:
                            expires = _parse_timestamp(str(document.get("expires_at", "")))
                        except ValueError:
                            continue
                        if expires <= now:
                            expired.append(label)
                        elif expires - now <= expiring_days * 86400.0:
                            expiring.append(label)
                except DistributionRefusal as exc:
                    warnings.append(f"assignments unreadable: {exc}")
                for label in expired:
                    warnings.append(
                        f"assignment '{label}' is EXPIRED; it directs no new "
                        "staging until reissued"
                    )
                for label in expiring:
                    warnings.append(
                        f"assignment '{label}' expires within {expiring_days} "
                        "day(s); ask the issuer for a reissue"
                    )
                check(
                    "assignment_expiry",
                    True,
                    f"{len(expired)} expired, {len(expiring)} expiring soon",
                )

    status = "problems" if problems else "ok"
    return {
        "status": status,
        "checks": checks,
        "problems": problems,
        "warnings": warnings,
        "exit_code": 1 if problems else 0,
    }


# ---------------------------------------------------------------------------
# Human renderers (text mode; --json prints the report dicts verbatim).
# Text carries sha PREFIXES and basenames only -- never absolute paths,
# never key material, never 32+ char hex blobs.


def _prefix(sha256: str) -> str:
    return sha256[:SHA_PREFIX_CHARS] if sha256 else "<none>"


def format_sync(report: dict) -> str:
    mode = "DRY-RUN (no mutation)" if report["dry_run"] else "APPLY"
    lines = [
        f"managed profile sync [{mode}]: source '{report['source_id']}' "
        f"({report['assignments_seen']} assignment file(s) verified)",
        f"resolution: {report['resolution']}",
    ]
    if report["resolution"] in ("none", "expired"):
        lines.append(report.get("note", ""))
        for label in report.get("expired_assignments", []):
            lines.append(f"  expired: {label}")
        return "\n".join(line for line in lines if line)
    assignment = report["assignment"]
    channel = report["channel"]
    lines.append(
        f"assignment: {assignment['label']} (mode={assignment['mode']}, "
        f"revision={assignment['revision']}, expires {assignment['expires_at']})"
    )
    lines.append(
        f"channel: {channel['name']} r{channel['revision']} "
        f"(watermark {channel['watermark_before']} -> {channel['watermark_after']})"
    )
    lines.append(
        f"candidate bundle: {_prefix(report['bundle_sha256'])} "
        f"(carrier summary status: {report['summary_status']}; E14: verified)"
    )
    if report["already_staged"]:
        lines.append("library: candidate already staged (idempotent)")
    elif report["dry_run"]:
        lines.append("library: candidate WOULD be staged (pass --apply)")
    else:
        lines.append(f"library: staged as {report.get('staged_as', '')} (NOT activated)")
    if report["drift"]:
        lines.append(
            f"drift: active bundle {_prefix(report['active_bundle_sha256'])} "
            f"differs from the assignment's {_prefix(report['bundle_sha256'])}"
        )
    lines.append(report["activation_note"])
    if report["dry_run"]:
        lines.append("dry-run: the library, trust store, and sync state were not touched")
    return "\n".join(lines)


def format_managed_status(report: dict) -> str:
    if not report["synced_ever"]:
        lines = ["managed profile sync: never synced (no state recorded)"]
    else:
        last = report["last_sync"]
        lines = [
            f"managed profile sync: source '{report['source_id']}' "
            f"(fingerprint {_prefix(report['source_hash'])})",
            f"last sync: {last.get('at', '')} result={last.get('result', '')} "
            f"assignment={last.get('assignment', '')} "
            f"channel={last.get('channel', '')} r{last.get('channel_revision', '')}",
            f"last-good bundle: {_prefix(report['last_good_bundle_sha256'])}",
        ]
        for identity, revision in sorted(report["watermarks"].items()):
            lines.append(f"  watermark {identity}: r{revision}")
    staged = report["staged_not_activated"]
    if staged:
        lines.append(
            "staged but NOT activated: "
            + ", ".join(_prefix(sha) for sha in staged)
            + " (activation is the explicit library step)"
        )
    drift = report["drift"]
    if drift:
        if drift["in_sync"]:
            lines.append("drift: none (the active bundle matches the last sync)")
        else:
            lines.append(
                f"DRIFT: assignment expects {_prefix(drift['expected_bundle_sha256'])} "
                f"but {_prefix(drift['active_bundle_sha256'])} is active"
            )
    for problem in report["problems"]:
        lines.append(f"problem: {problem}")
    return "\n".join(lines)


def format_last_good(report: dict) -> str:
    sha = report["last_good_bundle_sha256"]
    if not sha:
        return "managed sync last-good: none recorded yet"
    lines = [
        f"managed sync last-good bundle: {_prefix(sha)} "
        f"(in library: {report['in_library']}, active: {report['active']})"
    ]
    if "verifies_now" in report:
        if report["verifies_now"]:
            lines.append("re-verification: ok (real E14 path)")
        else:
            lines.append(
                f"re-verification: REFUSED ({report['refusal_code']} "
                f"{report['refusal']})"
            )
    if report["restored"]:
        lines.append(f"restored: yes{(' as ' + report['staged_as']) if report.get('staged_as') else ''}")
    if report.get("note"):
        lines.append(report["note"])
    for problem in report["problems"]:
        lines.append(f"problem: {problem}")
    return "\n".join(lines)


def format_managed_doctor(report: dict) -> str:
    lines = [f"managed sync doctor: {report['status']}"]
    for item in report["checks"]:
        mark = "ok" if item["ok"] else "PROBLEM"
        detail = f": {item['detail']}" if item["detail"] else ""
        lines.append(f"  [{mark}] {item['check']}{detail}")
    for warning in report["warnings"]:
        lines.append(f"  warning: {warning}")
    for problem in report["problems"]:
        lines.append(f"  problem: {problem}")
    return "\n".join(lines)
