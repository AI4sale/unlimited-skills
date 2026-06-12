"""E26: MCP registered/team distribution fixture E2E harness (fixture mode only).

ONE end-to-end workflow proving the PLANNED hosted distribution flow (E23
channels/assignments + the E24 registry carrier contract) can be tested
safely BEFORE any production registry sync is implemented. Everything hosted
is a FIXTURE: the "registry" is a plain local directory (content-addressed
bundle bodies, signed metadata-only summaries, signed channel/assignment
documents per the E23 schemas), and the registry envelope/authorization
behavior is MODELED by fixture functions implementing the E24 access-check
semantics (entitlement table, anti-oracle ``unknown_or_unauthorized``,
metadata-only until authorized). Everything client-side is the REAL stack:
E19 publisher ceremony, E15 trust store, E14 verification, E20 library,
E16 rollout dry-run, E17 audit replay, the real gateway startup resolution,
and the E11 audit inspector -- composed exactly like the E21 operator
acceptance suite (``scripts/run-mcp-operator-acceptance.py``), with shared
state across steps.

The flow (23 steps, one shared state):

  fixture registry seeded -> signed channel + assignment published ->
  fixture entitlement gate (allowed / denied / anti-oracle) -> client
  fetch through the access-check gate -> E14 verify -> E20 library add ->
  E16/E17 rollout + replay due diligence -> activate -> gateway resolve ->
  abuse battery (tampered channel/assignment, unsigned downgrade, stale
  revision replay, channel-name squatting, expired assignment, expired
  bundle under an injected clock, wrong audience, conflict resolution +
  loud tie refusal, poisoned active pointer, revoked bundle -> fail-closed
  + library rollback to last-good with the carrier offline) -> E11
  audit/report (refusal codes visible, redaction self-check PASS).

The verification clock is the run's start time, pinned ONCE per run (the
E21 stance); the expiry abuse steps inject explicit offset clocks on top.

Each step's report entry cites the E25 abuse-case test ids (``ABT-NNx``,
docs/mcp-distribution-abuse-test-plan.md) it covers or models; the ids
owned by the future registry suite are exercised here only as FIXTURE
models of the contract (see docs/mcp-distribution-e2e-harness.md for the
exact traceability and the modeled-vs-covered split).

Exit code 0 only when every selected step passes. ``--step NAME`` runs the
workflow up to and including NAME (earlier steps are prerequisites of the
one shared flow and stay in the report). The ``--json`` report validates
against ``schemas/mcp-distribution-e2e-report.schema.json`` and carries key
facts only: names, SHA-256 PREFIXES, counts, refusal codes/reasons,
statuses, basenames -- never key material, signature values, full hashes,
or local paths. ``--fixture-mode`` is accepted for symmetry with the other
runners: fixture mode is the ONLY mode this harness has.

Hard safety, by construction: ephemeral DEV keys are generated per run
inside a private temp directory and never leave it; no production keys, no
hosted calls, no registry sync, no real entitlement service, no OAuth, no
MCP resources or prompts, no network, no telemetry. The real library root,
managed trust store, and default audit log are never touched. Requires the
optional ``cryptography`` package (the E19 publisher has no fallback
signature scheme -- without it the harness refuses to run, exit 2).
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import itertools
import json
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from unlimited_skills.commands.mcp import _resolve_gateway_profile_state  # noqa: E402
from unlimited_skills.mcp import audit_inspector  # noqa: E402
from unlimited_skills.mcp.audit import AuditLog, scrub_paths  # noqa: E402
from unlimited_skills.mcp.audit_replay import replay_audit  # noqa: E402
from unlimited_skills.mcp.bundle_library import (  # noqa: E402
    ACTIVE_BUNDLE_FILENAME,
    BundleLibrary,
    BundleLibraryError,
    activate_bundle,
    add_bundle,
    read_state,
    rollback_bundle,
)
from unlimited_skills.mcp.bundle_publisher import (  # noqa: E402
    PublisherError,
    SigningKey,
    cryptography_available,
    generate_keypair,
    load_signing_key,
    publish_bundle,
    verify_report,
)
from unlimited_skills.mcp.bundles import (  # noqa: E402
    BUNDLE_AUDIENCE_MISMATCH,
    BUNDLE_EXPIRED,
    BUNDLE_REVOKED,
    BUNDLE_SIGNATURE_INVALID,
    _parse_timestamp,
    canonical_bundle_bytes,
    load_trusted_keys,
)

# E27: the routing-document loaders, the strict/forbidden-field checks, the
# E23 decision-6 conflict resolution, and the carrier-summary loader are the
# REAL client module now (unlimited_skills/mcp/managed_sync.py) -- the
# harness imports them back, exactly as docs/mcp-distribution-e2e-harness.md
# promised, and this abuse battery is their regression suite.
from unlimited_skills.mcp.managed_sync import (  # noqa: E402
    FORBIDDEN_FIELDS,
    SCHEME_RANK,
    DistributionRefusal,
    forbidden_field_names,
    load_summary_document,
    resolve_assignments,
    verify_routing_document,
)
from unlimited_skills.mcp.profile_rollout import plan_rollout  # noqa: E402
from unlimited_skills.mcp.profiles import ActiveProfile, FailClosedProfile  # noqa: E402
from unlimited_skills.mcp.trust_store import (  # noqa: E402
    TrustStore,
    TrustStoreError,
    import_key,
    load_key_file,
    revoke,
)

REPORT_TYPE = "mcp-distribution-e2e-report"
REPORT_SCHEMA_VERSION = 1

DAY = 86400.0

ISSUER_KEY_ID = "distribution-issuer-2026"
OTHER_OWNER_KEY_ID = "distribution-other-owner-2026"
CARRIER_KEY_ID = "fixture-registry-carrier-2026"

CHANNEL_NAME = "stable"
AUDIENCE = "team:distribution"
HOST_AUDIENCE = "host:distribution-fixture-ci"
WRONG_AUDIENCE = "team:somewhere-else"
MEMBER_AUDIENCES = (AUDIENCE, HOST_AUDIENCE)

MEMBER_ENTITLED = "member-entitled"
MEMBER_UNENTITLED = "member-unentitled"
MEMBER_UNKNOWN = "member-unknown"

SHA_PREFIX = 12
MAX_ERROR_CHARS = 512

# SCHEME_RANK (the E23 decision-6 specificity), FORBIDDEN_FIELDS (the E24
# decision-20 denylist), and the strict routing-document vocabularies live
# in unlimited_skills/mcp/managed_sync.py (E27) and are imported above.

# Profile-affecting env vars are neutralized for the duration of one run so
# the workflow is deterministic regardless of the operator's shell.
_NEUTRALIZED_ENV = ("UNLIMITED_SKILLS_MCP_PROFILE", "UNLIMITED_SKILLS_MCP_AUDIENCE")

PROFILE_DOC = {
    "schema_version": 1,
    "default_profile": "dev",
    "profiles": {
        "dev": {"visible": ["fake.*"], "callable": ["fake.*"]},
        "reviewer": {"extends": "dev", "visible": ["fake.echo"], "callable": ["fake.echo"]},
    },
}

# What-if fixture tools for the E16 dry-run: two inside the profile's
# namespace, one legacy tool outside it (hidden under the proposed policy).
TOOLS_FIXTURE = [
    {"upstream": "fake", "name": "echo", "description": "echoes its input"},
    {"upstream": "fake", "name": "add", "description": "adds two numbers"},
    {"upstream": "legacy", "name": "export", "description": "legacy bulk export"},
]

EMPTY_CRL = {"schema_version": 1, "revoked_bundles": [], "revoked_key_ids": []}


class StepError(AssertionError):
    """One harness step's assertion failed (the workflow stops)."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise StepError(message)


def _prefix(sha256: str) -> str:
    return sha256[:SHA_PREFIX]


def _utc(epoch: float) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(epoch))


# ---------------------------------------------------------------------------
# Routing-document construction and FIXTURE client-side verification. The
# documents follow the E23 file contracts exactly (the schemas/tests own the
# format); signing reuses the REAL canonical JSON (canonical_bundle_bytes)
# and the keygen signing-key format. This is the fixture stand-in for the
# future client routing-resolution module -- the step interface the hosted
# implementation must swap in behind.


def sign_routing_document(document: dict, key: SigningKey) -> dict:
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    message = canonical_bundle_bytes(document)
    signature = Ed25519PrivateKey.from_private_bytes(key.seed).sign(message)
    document["signature"] = {
        "algorithm": "ed25519",
        "key_id": key.key_id,
        "value": base64.b64encode(signature).decode("ascii"),
    }
    return document


def build_channel(
    name: str, owner: SigningKey, history: list[dict], revision: int
) -> dict:
    active = [record for record in history if record["status"] == "active"]
    document = {
        "channel_version": 1,
        "name": name,
        "revision": revision,
        "owner": {"key_id": owner.key_id, "display": "Distribution fixture team"},
        "history": history,
        "current": active[0]["bundle_sha256"],
    }
    return sign_routing_document(document, owner)


def build_assignment(
    audience: list[str],
    channel_name: str,
    owner_key_id: str,
    mode: str,
    issuer: SigningKey,
    revision: int,
    issued_at: str,
    expires_at: str,
    bundle_sha256: str = "",
) -> dict:
    document = {
        "assignment_version": 1,
        "audience": list(audience),
        "channel": {"name": channel_name, "owner_key_id": owner_key_id},
        "mode": mode,
        "issuer": {"key_id": issuer.key_id, "display": "Distribution fixture team"},
        "revision": revision,
        "issued_at": issued_at,
        "expires_at": expires_at,
    }
    if mode == "pin":
        document["bundle_sha256"] = bundle_sha256
    return sign_routing_document(document, issuer)


# verify_routing_document (the SIGNED-DISTRIBUTION client check) and
# resolve_assignments (the E23 decision-6 conflict resolution) are imported
# from unlimited_skills/mcp/managed_sync.py (E27): the abuse battery below
# is their regression suite.


# ---------------------------------------------------------------------------
# The FIXTURE registry: a local directory standing in for the future hosted
# carrier. Bundle bodies are content-addressed opaque blobs; summaries are
# metadata-only and carrier-signed (the two-signature model: the carrier key
# is deliberately NOT in the member's trust store); channels/assignments are
# the verbatim E23 files. The access-check function models the E24 decision-4
# authorization chain with a fixture entitlement table and the anti-oracle
# ``unknown_or_unauthorized`` answer. NOTHING here is hosted: no network, no
# endpoints, no daemon -- file reads and writes inside one temp directory.


class FixtureRegistry:
    def __init__(self, root: Path, carrier: SigningKey, clock: float) -> None:
        self.root = Path(root)
        self.carrier = carrier
        self.clock = clock
        self.bundles_dir = self.root / "bundles"
        self.summaries_dir = self.root / "summaries"
        self.channels_dir = self.root / "channels"
        self.assignments_dir = self.root / "assignments"
        for directory in (
            self.bundles_dir,
            self.summaries_dir,
            self.channels_dir,
            self.assignments_dir,
        ):
            directory.mkdir(parents=True, exist_ok=True)
        # The carrier's PUBLIC key, served the way GET /v1/public-keys would
        # (E24 decision 10): carrier trust only, never issuer keys.
        (self.root / "public-keys.json").write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "keys": [
                        {
                            "key_id": carrier.key_id,
                            "algorithm": "ed25519",
                            "public_key": base64.b64encode(carrier.public_key).decode("ascii"),
                        }
                    ],
                },
                sort_keys=True,
            ),
            encoding="utf-8",
        )
        self.entitlements_path = self.root / "entitlements.json"
        self.revision_index: dict[tuple[str, str], int] = {}
        self.assignment_labels: list[str] = []

    # -- publisher-facing fixture surface ---------------------------------

    def put_bundle(self, source: Path) -> str:
        data = Path(source).read_bytes()
        sha256 = hashlib.sha256(data).hexdigest()
        (self.bundles_dir / f"{sha256}.bundle.json").write_bytes(data)
        return sha256

    def put_summary(self, bundle_path: Path, status: str = "active") -> dict:
        """Metadata-only signed summary (E24 decision 2 shape, fixture): the
        field set cannot represent a bundle body, profile rules, or tool
        names; audience SCHEMES only, never the identifiers."""
        data = Path(bundle_path).read_bytes()
        document = json.loads(data.decode("utf-8"))
        summary = {
            "summary_version": 1,
            "bundle_sha256": hashlib.sha256(data).hexdigest(),
            "issuer_key_id": document["issuer"]["key_id"],
            "audience_schemes": sorted(
                {identifier.split(":", 1)[0] for identifier in document["audience"]}
            ),
            "published_at": document["issued_at"],
            "expires_at": document["expires_at"],
            "size_bytes": len(data),
            "status": status,
        }
        sign_routing_document(summary, self.carrier)
        path = self.summaries_dir / f"{summary['bundle_sha256']}.summary.json"
        path.write_text(json.dumps(summary, sort_keys=True), encoding="utf-8")
        return summary

    def put_channel(self, document: dict) -> Path:
        """Store one E23 channel document. Models the E24 decision-18 publish
        gates: unsigned documents are refused outright, the signature key_id
        must equal owner.key_id, and the revision must be strictly greater
        than the stored revision for the channel identity."""
        if "signature" not in document:
            raise DistributionRefusal(
                "unsigned_artifact_rejected",
                "fixture registry refuses unsigned channel documents (decision 18)",
            )
        if document["signature"].get("key_id") != document["owner"]["key_id"]:
            raise DistributionRefusal(
                "owner_key_mismatch",
                "channel signature key_id does not match owner.key_id",
            )
        identity = (document["name"], document["owner"]["key_id"])
        stored = self.revision_index.get(identity, 0)
        if document["revision"] <= stored:
            raise DistributionRefusal(
                "revision_regression",
                f"channel revision {document['revision']} is not greater than the "
                f"stored revision {stored}",
            )
        self.revision_index[identity] = document["revision"]
        path = self.channels_dir / f"{identity[1]}.{identity[0]}.channel.json"
        path.write_text(json.dumps(document, sort_keys=True), encoding="utf-8")
        return path

    def put_assignment(self, label: str, document: dict) -> Path:
        if "signature" not in document:
            raise DistributionRefusal(
                "unsigned_artifact_rejected",
                "fixture registry refuses unsigned assignment documents (decision 18)",
            )
        path = self.assignments_dir / f"{label}.assignment.json"
        path.write_text(json.dumps(document, sort_keys=True), encoding="utf-8")
        if label not in self.assignment_labels:
            self.assignment_labels.append(label)
        return path

    def register_members(self, members: dict[str, dict]) -> None:
        """The fixture entitlement table: member id -> audiences + the
        ``mcp_profile_sync`` feature decision (E24 decision 5, modeled)."""
        self.entitlements_path.write_text(
            json.dumps({"schema_version": 1, "members": members}, sort_keys=True),
            encoding="utf-8",
        )

    # -- consumer-facing fixture surface ----------------------------------

    def _member(self, member_id: str) -> dict | None:
        table = json.loads(self.entitlements_path.read_text(encoding="utf-8"))
        entry = table["members"].get(member_id)
        return entry if isinstance(entry, dict) else None

    def get_channel(self, name: str, owner_key_id: str) -> dict | None:
        path = self.channels_dir / f"{owner_key_id}.{name}.channel.json"
        if not path.is_file():
            return None
        return json.loads(path.read_text(encoding="utf-8"))

    def list_assignments(self, member_id: str) -> list[tuple[str, dict]]:
        """Assignments whose audience intersects the member's identifiers --
        metadata only; receiving an assignment grants nothing."""
        member = self._member(member_id)
        if member is None or not member.get("mcp_profile_sync"):
            return []
        audiences = set(member.get("audiences", []))
        entries: list[tuple[str, dict]] = []
        for label in self.assignment_labels:
            path = self.assignments_dir / f"{label}.assignment.json"
            document = json.loads(path.read_text(encoding="utf-8"))
            if set(document.get("audience", [])) & audiences:
                entries.append((label, document))
        return entries

    def read_summary(self, bundle_sha256: str) -> dict | None:
        """Metadata-only summary lookup (the listing surface a denied member
        may still see for shas in its own scope -- never a body)."""
        path = self.summaries_dir / f"{bundle_sha256}.summary.json"
        if not path.is_file():
            return None
        return json.loads(path.read_text(encoding="utf-8"))

    def access_check(self, member_id: str, bundle_sha256: str) -> dict:
        """The E24 decision-4 authorization chain, modeled as one fixture
        function: registered -> entitled -> matching unexpired assignment ->
        sha reachable from that assignment -> bundle not revoked. A sha that
        does not exist and a sha outside the caller's scope answer with the
        byte-identical anti-oracle code ``unknown_or_unauthorized``."""
        member = self._member(member_id)
        if member is None:
            return {"authorized": False, "reason_code": "not_registered"}
        if not member.get("mcp_profile_sync"):
            return {"authorized": False, "reason_code": "no_profile_sync_entitlement"}
        audiences = set(member.get("audiences", []))
        matching: list[dict] = []
        for label in self.assignment_labels:
            path = self.assignments_dir / f"{label}.assignment.json"
            document = json.loads(path.read_text(encoding="utf-8"))
            if not set(document.get("audience", [])) & audiences:
                continue
            if self.clock >= _parse_timestamp(document["expires_at"]):
                continue
            matching.append(document)
        if not matching:
            return {"authorized": False, "reason_code": "audience_mismatch"}
        reachable: set[str] = set()
        for document in matching:
            if document["mode"] == "pin":
                reachable.add(document["bundle_sha256"])
            channel = self.get_channel(
                document["channel"]["name"], document["channel"]["owner_key_id"]
            )
            if channel is not None:
                reachable.add(channel["current"])
                reachable.update(
                    record["bundle_sha256"] for record in channel["history"]
                )
        if bundle_sha256 not in reachable:
            # Deliberately indistinguishable: nonexistent and out-of-scope
            # answer the same code and shape (anti-oracle, E24).
            return {"authorized": False, "reason_code": "unknown_or_unauthorized"}
        summary = self.read_summary(bundle_sha256)
        if summary is not None and summary.get("status") == "revoked":
            return {"authorized": False, "reason_code": "bundle_revoked"}
        return {"authorized": True, "reason_code": "ok"}

    def fetch_bundle(self, member_id: str, bundle_sha256: str, dest_dir: Path) -> Path:
        """The download gate: the FULL access-check chain first, then a plain
        file copy with the content address re-checked against the bytes (the
        E24 download hardening). Denials never move bytes."""
        check = self.access_check(member_id, bundle_sha256)
        if not check["authorized"]:
            raise DistributionRefusal(
                check["reason_code"],
                f"fixture registry refused the download: {check['reason_code']}",
            )
        data = (self.bundles_dir / f"{bundle_sha256}.bundle.json").read_bytes()
        if hashlib.sha256(data).hexdigest() != bundle_sha256:
            raise DistributionRefusal(
                "content_address_mismatch",
                "stored bytes do not match the requested content address",
            )
        dest_dir.mkdir(parents=True, exist_ok=True)
        destination = dest_dir / f"{_prefix(bundle_sha256)}-fetched.bundle.json"
        destination.write_bytes(data)
        return destination


# load_summary_document (the strict carrier-summary loader) is imported
# from unlimited_skills/mcp/managed_sync.py (E27).


# ---------------------------------------------------------------------------
# Shared workflow state.


class DistributionContext:
    """Shared state of the one fixture distribution workflow."""

    def __init__(self, base: Path, now: float) -> None:
        self.base = base
        self.now = now
        self.store = TrustStore(base / "trust-store")
        self.library = BundleLibrary(base / "bundle-library")
        self.profiles_path = base / "team-profiles.json"
        self.tools_fixture_path = base / "tools-fixture.json"
        self.staging = base / "publisher-staging"
        self.client_incoming = base / "client-incoming"
        self.unentitled_incoming = base / "unentitled-incoming"
        self.audit = AuditLog(base / "audit" / "mcp-audit.jsonl")
        self.history_audit_path = base / "history" / "mcp-audit.jsonl"
        self.keys: dict[str, SigningKey] = {}
        self.key_paths: dict[str, dict[str, Path]] = {}
        self.bundle_paths: dict[str, Path] = {}
        self.bundle_shas: dict[str, str] = {}
        self.fetched_paths: dict[str, Path] = {}
        self.registry: FixtureRegistry | None = None
        self.carrier_public_keys: dict[str, bytes] = {}
        self.channel_revisions: dict[int, dict] = {}
        self.assignment: dict = {}
        self.assignment_label = "team-distribution-follow"
        self.watermarks: dict[tuple[str, str], int] = {}

    def verify_kwargs(self) -> dict:
        return {
            "trusted_keys_path": self.store.trusted_keys_path,
            "audience_ids": [AUDIENCE],
            "now": self.now,
        }

    def gateway_args(self) -> SimpleNamespace:
        return SimpleNamespace(
            profiles="",
            profile="",
            profile_bundle=str(self.library.active_bundle_path),
            trusted_keys=str(self.store.trusted_keys_path),
            audience_id=[AUDIENCE],
            require_signed_profiles=True,
            root="",
        )

    def verify_routing(self, document: dict, kind: str) -> str:
        return verify_routing_document(
            document,
            kind,
            self.store.trusted_keys_path,
            self.store.crl_path,
            now=self.now,
        )

    def record_refusal(self, message: str, code: int | None = None, reason: str = "") -> None:
        extra: dict = {}
        if code is not None:
            extra["code"] = code
        if reason:
            extra["reason"] = reason
        self.audit.record(
            tool="tools_call",
            upstream="fake",
            ok=False,
            error=message,
            profile="",
            extra=extra,
        )


# ---------------------------------------------------------------------------
# The 23 steps. Each runs the REAL client machinery (or the documented
# fixture model of the registry side), asserts the operator-visible outcome,
# and returns (facts, covered ABT ids). Facts carry prefixes/counts/reasons
# only -- never key material, full hashes, or local paths.


def step_keygen(ctx: DistributionContext) -> tuple[dict, list[str]]:
    for key_id, display in (
        (ISSUER_KEY_ID, "Distribution issuer (DEV)"),
        (OTHER_OWNER_KEY_ID, "Other channel owner (DEV)"),
        (CARRIER_KEY_ID, "Fixture registry carrier (DEV)"),
    ):
        result = generate_keypair(
            ctx.base / "keys" / key_id, key_id=key_id, display=display, now=ctx.now
        )
        _require(result["generated"] is True, f"{key_id}: keygen did not generate")
        _require(result["dev_only"] is True, f"{key_id}: keygen must be DEV-only")
        ctx.keys[key_id] = load_signing_key(Path(result["private_key_path"]))
        ctx.key_paths[key_id] = {
            "private": Path(result["private_key_path"]),
            "public": Path(result["public_key_path"]),
        }
    return (
        {
            "key_ids": [ISSUER_KEY_ID, OTHER_OWNER_KEY_ID, CARRIER_KEY_ID],
            "algorithm": "ed25519",
            "dev_only": True,
            "ephemeral": True,
        },
        [],
    )


def step_trust_import(ctx: DistributionContext) -> tuple[dict, list[str]]:
    # Capability trust: the ISSUER and the other-owner keys go into the
    # member's E15 store. The CARRIER key deliberately does NOT -- carrier
    # trust never becomes capability trust (E24 decision 10).
    for key_id in (ISSUER_KEY_ID, OTHER_OWNER_KEY_ID):
        public_doc = load_key_file(ctx.key_paths[key_id]["public"])
        result = import_key(
            ctx.store,
            key_id=key_id,
            public_key_b64=str(public_doc["public_key"]),
            display=f"{key_id} (DEV)",
            now=ctx.now,
        )
        _require(result["imported"] is True, f"{key_id}: trust import refused")
    ctx.store.crl_path.parent.mkdir(parents=True, exist_ok=True)
    ctx.store.crl_path.write_text(json.dumps(EMPTY_CRL), encoding="utf-8")
    ctx.carrier_public_keys = {
        CARRIER_KEY_ID: ctx.keys[CARRIER_KEY_ID].public_key
    }
    keys = load_trusted_keys(ctx.store.trusted_keys_path)
    _require(CARRIER_KEY_ID not in keys, "the carrier key must NOT be capability trust")
    return (
        {
            "imported": sorted(keys),
            "carrier_key_in_trust_store": False,
            "public_keys_only": True,
            "crl_file": ctx.store.crl_path.name,
        },
        [],
    )


def step_publish(ctx: DistributionContext) -> tuple[dict, list[str]]:
    ctx.profiles_path.write_text(json.dumps(PROFILE_DOC), encoding="utf-8")
    issuer_private = ctx.key_paths[ISSUER_KEY_ID]["private"]
    for offset, name, audience, previous in (
        (0.0, "team-v1", list(MEMBER_AUDIENCES), ""),
        (10.0, "team-v2", list(MEMBER_AUDIENCES), "previous"),
        (20.0, "other-team-v1", [WRONG_AUDIENCE], ""),
    ):
        result = publish_bundle(
            ctx.profiles_path,
            issuer_private,
            audience=audience,
            expires_days=30,
            out_dir=ctx.staging,
            name=name,
            crl_path=str(ctx.store.crl_path),
            previous=str(ctx.bundle_paths["team-v1"]) if previous else "",
            now=ctx.now + offset,
        )
        _require(result["published"] is True, f"{name}: ceremony did not publish")
        _require(
            result["verification"]["ok"] is True,
            f"{name}: the post-package self-check did not pass",
        )
        ctx.bundle_paths[name] = ctx.staging / f"{name}.bundle.json"
        ctx.bundle_shas[name] = result["bundle_sha256"]
    _require(
        len(set(ctx.bundle_shas.values())) == 3,
        "the three published bundles must have distinct SHA-256s",
    )
    return (
        {
            "bundles": ["team-v1", "team-v2", "other-team-v1"],
            "v1_sha_prefix": _prefix(ctx.bundle_shas["team-v1"]),
            "v2_sha_prefix": _prefix(ctx.bundle_shas["team-v2"]),
            "issuer_key_id": ISSUER_KEY_ID,
            "self_check": "resolve_bundle_state (E14)",
        },
        [],
    )


def step_registry_seed(ctx: DistributionContext) -> tuple[dict, list[str]]:
    registry = FixtureRegistry(
        ctx.base / "fixture-registry", ctx.keys[CARRIER_KEY_ID], clock=ctx.now
    )
    ctx.registry = registry
    for name in ("team-v1", "team-v2", "other-team-v1"):
        stored = registry.put_bundle(ctx.bundle_paths[name])
        _require(stored == ctx.bundle_shas[name], f"{name}: content address drifted")
        summary = registry.put_summary(ctx.bundle_paths[name])
        loaded = load_summary_document(summary, ctx.carrier_public_keys)
        _require(
            loaded["bundle_sha256"] == ctx.bundle_shas[name],
            f"{name}: summary does not name the stored sha",
        )
        _require(
            forbidden_field_names(loaded) == set(),
            f"{name}: summary carries forbidden fields",
        )
        _require(
            "profiles" not in loaded and "tool" not in json.dumps(sorted(loaded)),
            f"{name}: summary must be metadata-only (no body fields)",
        )
    registry.register_members(
        {
            MEMBER_ENTITLED: {
                "audiences": list(MEMBER_AUDIENCES),
                "mcp_profile_sync": True,
            },
            MEMBER_UNENTITLED: {
                "audiences": list(MEMBER_AUDIENCES),
                "mcp_profile_sync": False,
            },
        }
    )
    return (
        {
            "registry_dir": registry.root.name,
            "bundles_stored": 3,
            "summaries_signed": 3,
            "content_addressed": True,
            "carrier_key_id": CARRIER_KEY_ID,
            "registered_members": 2,
        },
        [],
    )


def step_channel_publish(ctx: DistributionContext) -> tuple[dict, list[str]]:
    registry = ctx.registry
    issuer = ctx.keys[ISSUER_KEY_ID]
    v1_record = {
        "bundle_sha256": ctx.bundle_shas["team-v1"],
        "published_at": _utc(ctx.now - 900),
        "status": "active",
    }
    revision1 = build_channel(CHANNEL_NAME, issuer, [dict(v1_record)], revision=1)
    registry.put_channel(revision1)
    ctx.channel_revisions[1] = revision1
    history = [
        {**v1_record, "status": "superseded"},
        {
            "bundle_sha256": ctx.bundle_shas["team-v2"],
            "published_at": _utc(ctx.now - 600),
            "status": "active",
        },
    ]
    revision2 = build_channel(CHANNEL_NAME, issuer, history, revision=2)
    registry.put_channel(revision2)
    ctx.channel_revisions[2] = revision2
    # The fixture publish gate refuses unsigned channels (decision 18 model).
    unsigned = {key: value for key, value in revision2.items() if key != "signature"}
    unsigned_refused = ""
    try:
        registry.put_channel(unsigned)
    except DistributionRefusal as exc:
        unsigned_refused = exc.reason
    _require(
        unsigned_refused == "unsigned_artifact_rejected",
        "the fixture registry must refuse unsigned channel publishes",
    )
    return (
        {
            "channel": CHANNEL_NAME,
            "owner_key_id": ISSUER_KEY_ID,
            "revisions_published": [1, 2],
            "current_sha_prefix": _prefix(revision2["current"]),
            "history_records": len(history),
            "unsigned_publish_refused": unsigned_refused,
        },
        [],
    )


def step_assignment_issue(ctx: DistributionContext) -> tuple[dict, list[str]]:
    assignment = build_assignment(
        [AUDIENCE],
        CHANNEL_NAME,
        ISSUER_KEY_ID,
        "follow",
        ctx.keys[ISSUER_KEY_ID],
        revision=1,
        issued_at=_utc(ctx.now - 600),
        expires_at=_utc(ctx.now + 60 * DAY),
    )
    ctx.assignment = assignment
    ctx.registry.put_assignment(ctx.assignment_label, assignment)
    _require(
        ctx.verify_routing(assignment, "assignment") == ISSUER_KEY_ID,
        "the issued assignment must verify against the member's trust store",
    )
    return (
        {
            "label": ctx.assignment_label,
            "audience": [AUDIENCE],
            "mode": "follow",
            "revision": 1,
            "signed": True,
        },
        [],
    )


def step_entitlement_gate(ctx: DistributionContext) -> tuple[dict, list[str]]:
    registry = ctx.registry
    v2_sha = ctx.bundle_shas["team-v2"]
    allowed = registry.access_check(MEMBER_ENTITLED, v2_sha)
    _require(
        allowed == {"authorized": True, "reason_code": "ok"},
        "the entitled member must be authorized for the assigned bundle",
    )
    denied = registry.access_check(MEMBER_UNENTITLED, v2_sha)
    _require(
        denied == {"authorized": False, "reason_code": "no_profile_sync_entitlement"},
        "the unentitled member must be denied with the exact reason code",
    )
    unknown = registry.access_check(MEMBER_UNKNOWN, v2_sha)
    _require(
        unknown["reason_code"] == "not_registered",
        "an unknown member must be refused as not registered",
    )
    # The denial never moves bytes; the metadata-only summary stays readable
    # and structurally cannot carry a body.
    body_refused = ""
    try:
        registry.fetch_bundle(MEMBER_UNENTITLED, v2_sha, ctx.unentitled_incoming)
    except DistributionRefusal as exc:
        body_refused = exc.reason
    _require(
        body_refused == "no_profile_sync_entitlement",
        "the unentitled download must refuse before any bytes move",
    )
    _require(
        not any(ctx.unentitled_incoming.glob("*")),
        "no bundle bytes may land in the unentitled member's directory",
    )
    summary = load_summary_document(registry.read_summary(v2_sha), ctx.carrier_public_keys)
    _require(
        "profiles" not in summary and forbidden_field_names(summary) == set(),
        "the denied member's metadata view must stay body-free",
    )
    # Anti-oracle: a sha outside the member's scope and a truly nonexistent
    # sha answer byte-identically (ABT-13a, modeled as fixture behavior).
    foreign = registry.access_check(MEMBER_ENTITLED, ctx.bundle_shas["other-team-v1"])
    nonexistent = registry.access_check(MEMBER_ENTITLED, "0" * 64)
    _require(
        json.dumps(foreign, sort_keys=True) == json.dumps(nonexistent, sort_keys=True),
        "foreign and nonexistent shas must be indistinguishable",
    )
    _require(
        foreign["reason_code"] == "unknown_or_unauthorized",
        "the anti-oracle answer must be unknown_or_unauthorized",
    )
    # ABT-14b: the SAME files delivered as plain local files verify and
    # activate with zero entitlement consultation -- entitlement gates the
    # carrier, never verification (E24 decision 6).
    local_copy = ctx.unentitled_incoming / "local-transport.bundle.json"
    ctx.unentitled_incoming.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(ctx.bundle_paths["team-v2"], local_copy)
    local_report = verify_report(
        local_copy, ctx.store.trusted_keys_path, audience_ids=[AUDIENCE], now=ctx.now
    )
    _require(
        local_report["ok"] is True,
        "local out-of-band delivery must verify without any entitlement",
    )
    return (
        {
            "entitled_reason": allowed["reason_code"],
            "unentitled_reason": denied["reason_code"],
            "unknown_member_reason": unknown["reason_code"],
            "denied_body_bytes_moved": False,
            "metadata_only_for_denied": True,
            "anti_oracle_identical": True,
            "anti_oracle_reason": foreign["reason_code"],
            "local_transport_verifies": True,
            "entitlement_never_consulted": True,
        },
        ["ABT-13a", "ABT-14a", "ABT-14b"],
    )


def step_client_fetch(ctx: DistributionContext) -> tuple[dict, list[str]]:
    registry = ctx.registry
    entries = registry.list_assignments(MEMBER_ENTITLED)
    _require(len(entries) == 1, f"expected exactly one assignment, got {len(entries)}")
    for _, document in entries:
        ctx.verify_routing(document, "assignment")
    status, winner, _ = resolve_assignments(entries, list(MEMBER_AUDIENCES), now=ctx.now)
    _require(status == "ok" and winner == ctx.assignment_label, "resolution must pick the assignment")
    assignment = dict(entries[0][1])
    channel = registry.get_channel(
        assignment["channel"]["name"], assignment["channel"]["owner_key_id"]
    )
    resolved_sha = apply_channel(ctx, channel, assignment)
    _require(
        resolved_sha == ctx.bundle_shas["team-v2"],
        "follow mode must resolve the channel's current bundle (team-v2)",
    )
    _require(
        ctx.watermarks[(CHANNEL_NAME, ISSUER_KEY_ID)] == 2,
        "the channel watermark must record revision 2",
    )
    ctx.fetched_paths["team-v2"] = registry.fetch_bundle(
        MEMBER_ENTITLED, resolved_sha, ctx.client_incoming
    )
    # The prior history sha stays fetchable for rollback (E24 decision 13).
    ctx.fetched_paths["team-v1"] = registry.fetch_bundle(
        MEMBER_ENTITLED, ctx.bundle_shas["team-v1"], ctx.client_incoming
    )
    return (
        {
            "assignments_listed": 1,
            "resolution": status,
            "winner": winner,
            "resolved_sha_prefix": _prefix(resolved_sha),
            "watermark_revision": 2,
            "fetched": ["team-v2", "team-v1"],
            "content_address_rechecked": True,
        },
        [],
    )


def apply_channel(ctx: DistributionContext, channel: dict, assignment: dict) -> str:
    """Fixture client application of a channel under one assignment: verify
    the channel document, require the FULL identity pair match, refuse
    revision regression against the per-identity watermark, then resolve the
    pointer (pin wins over channel movement)."""
    ctx.verify_routing(channel, "channel")
    wanted = assignment["channel"]
    if (
        channel["name"] != wanted["name"]
        or channel["owner"]["key_id"] != wanted["owner_key_id"]
    ):
        raise DistributionRefusal(
            "channel_identity_mismatch",
            "channel does not match the assignment's full identity pair "
            "(name + owner key id)",
        )
    identity = (channel["name"], channel["owner"]["key_id"])
    applied = ctx.watermarks.get(identity, 0)
    if channel["revision"] < applied:
        raise DistributionRefusal(
            "routing_revision_regression",
            f"channel revision {channel['revision']} is below the applied "
            f"watermark {applied}",
        )
    ctx.watermarks[identity] = max(applied, channel["revision"])
    if assignment["mode"] == "pin":
        return assignment["bundle_sha256"]
    return channel["current"]


def step_client_verify(ctx: DistributionContext) -> tuple[dict, list[str]]:
    for name in ("team-v2", "team-v1"):
        report = verify_report(
            ctx.fetched_paths[name],
            ctx.store.trusted_keys_path,
            audience_ids=[AUDIENCE],
            now=ctx.now,
        )
        _require(report["ok"] is True, f"{name}: fetched bundle refused: {report['refusal']}")
        _require(
            report["bundle_sha256"] == ctx.bundle_shas[name],
            f"{name}: fetched bundle sha drifted",
        )
    return (
        {
            "verified": ["team-v2", "team-v1"],
            "verified_via": "resolve_bundle_state (E14)",
            "profile": "dev",
        },
        [],
    )


def step_library_add(ctx: DistributionContext) -> tuple[dict, list[str]]:
    added = []
    for name in ("team-v1", "team-v2"):
        result = add_bundle(
            ctx.library, ctx.fetched_paths[name], name=name, **ctx.verify_kwargs()
        )
        _require(result["added"] is True, f"{name}: library add refused")
        _require(
            result["verification"] == "verified",
            f"{name}: add must verify BEFORE storing",
        )
        added.append({"sha_prefix": _prefix(result["sha256"])})
    return (
        {"added": len(added), "verified_before_store": True, "content_addressed": True},
        [],
    )


def step_rollout_replay(ctx: DistributionContext) -> tuple[dict, list[str]]:
    # Operator due diligence BEFORE activation: the E16 dry-run reports the
    # full would-be surface of the routed bundle, and the E17 replay scores
    # it against real historical traffic shapes.
    ctx.tools_fixture_path.write_text(json.dumps(TOOLS_FIXTURE), encoding="utf-8")
    plan = plan_rollout(
        root=ctx.base,
        bundle_path=str(ctx.fetched_paths["team-v2"]),
        trusted_keys_path=str(ctx.store.trusted_keys_path),
        audience_ids=[AUDIENCE],
        tools_fixture_path=str(ctx.tools_fixture_path),
        now=ctx.now,
        env_name="",
    )
    tools = plan["tools"]
    _require(plan["blockers"] == [], f"rollout plan has blockers: {plan['blockers'][:2]}")
    _require(plan["verification"]["ok"] is True, "rollout plan verification failed")
    _require(
        tools["visible"] == 2 and tools["hidden"] == 1,
        "the legacy tool must be reported hidden BEFORE activation",
    )
    history = AuditLog(ctx.history_audit_path)
    history.record(tool="profile_loaded", ok=True, profile="dev")
    for _ in range(5):
        history.record(
            tool="tools_call",
            upstream="fake",
            duration_ms=12.5,
            ok=True,
            arguments={"tool": "fake.echo"},
            profile="dev",
        )
    history.record(
        tool="tools_call",
        upstream="legacy",
        duration_ms=40.0,
        ok=True,
        arguments={"tool": "legacy.export"},
        profile="dev",
    )
    replay = replay_audit(
        ctx.history_audit_path,
        root=ctx.base,
        bundle_path=str(ctx.fetched_paths["team-v2"]),
        trusted_keys_path=str(ctx.store.trusted_keys_path),
        audience_ids=[AUDIENCE],
        now=ctx.now,
        env_name="",
    )
    recommendation = replay["recommendation"]["status"]
    _require(
        recommendation in ("safe", "safe_with_warnings"),
        f"replay recommendation is {recommendation!r} (the rollout is blocked)",
    )
    return (
        {
            "plan_mode": plan["profile_state"]["mode"],
            "tools_total": tools["total"],
            "visible": tools["visible"],
            "hidden": tools["hidden"],
            "replayed": replay["impact"]["replayed"],
            "newly_denied": replay["impact"]["newly_denied"],
            "recommendation": recommendation,
            "before_activation": True,
        },
        ["ABT-03b"],
    )


def step_activate(ctx: DistributionContext) -> tuple[dict, list[str]]:
    first = activate_bundle(ctx.library, "team-v1", **ctx.verify_kwargs())
    _require(first["activated"] is True, "activating team-v1 failed")
    second = activate_bundle(ctx.library, "team-v2", **ctx.verify_kwargs())
    _require(second["activated"] is True, "activating team-v2 failed")
    _require(
        second["previous_active_sha256"] == ctx.bundle_shas["team-v1"],
        "team-v1 must be recorded as the previously active bundle",
    )
    state, _ = read_state(ctx.library)
    actions = [record["action"] for record in state["history"]]
    _require(actions == ["activate", "activate"], f"unexpected history actions: {actions}")
    return (
        {
            "active_sha_prefix": _prefix(second["sha256"]),
            "previous_sha_prefix": _prefix(second["previous_active_sha256"]),
            "pointer_file": ACTIVE_BUNDLE_FILENAME,
            "history_actions": actions,
            "reverified_at_activation": True,
        },
        [],
    )


def step_gateway_resolve(ctx: DistributionContext) -> tuple[dict, list[str]]:
    state, note = _resolve_gateway_profile_state(ctx.gateway_args())
    _require(
        isinstance(state, ActiveProfile),
        f"gateway resolution did not produce an ActiveProfile: {note}",
    )
    _require(state.name == "dev", f"gateway resolved profile {state.name!r}")
    _require(state.is_callable("fake", "echo"), "fake.echo must be callable")
    _require(not state.is_visible("legacy", "export"), "legacy.export must stay hidden")
    provenance = state.provenance
    _require(
        provenance is not None and provenance.bundle_sha256 == ctx.bundle_shas["team-v2"],
        "the gateway must resolve the ACTIVE routed bundle (team-v2)",
    )
    ctx.audit.record(tool="tools_search", upstream="", ok=True, profile=state.name)
    return (
        {
            "profile": state.name,
            "require_signed_profiles": True,
            "bundle_sha_prefix": _prefix(provenance.bundle_sha256),
            "issuer_key_id": provenance.issuer_key_id,
            "legacy_export_hidden": True,
        },
        [],
    )


def step_abuse_tampered_channel(ctx: DistributionContext) -> tuple[dict, list[str]]:
    tampered = json.loads(json.dumps(ctx.channel_revisions[2]))
    tampered["revision"] = 3  # an attacker bumps the revision to force movement
    reason = ""
    try:
        apply_channel(ctx, tampered, ctx.assignment)
    except DistributionRefusal as exc:
        reason = exc.reason
        ctx.record_refusal(scrub_paths(str(exc)), reason=reason)
    _require(
        reason == "routing_signature_invalid",
        f"tampered channel must refuse routing_signature_invalid (got {reason!r})",
    )
    _require(
        ctx.watermarks[(CHANNEL_NAME, ISSUER_KEY_ID)] == 2,
        "a refused channel must not move the watermark",
    )
    state, _ = _resolve_gateway_profile_state(ctx.gateway_args())
    _require(
        isinstance(state, ActiveProfile),
        "the active bundle must keep working after a refused routing file",
    )
    return (
        {
            "refused": reason,
            "watermark_unchanged": True,
            "active_bundle_unaffected": True,
        },
        ["ABT-01a"],
    )


def step_abuse_tampered_assignment(ctx: DistributionContext) -> tuple[dict, list[str]]:
    tampered = json.loads(json.dumps(ctx.assignment))
    tampered["mode"] = "pin"  # an attacker pins the fleet to an old sha
    tampered["bundle_sha256"] = ctx.bundle_shas["team-v1"]
    reason = ""
    try:
        ctx.verify_routing(tampered, "assignment")
    except DistributionRefusal as exc:
        reason = exc.reason
        ctx.record_refusal(scrub_paths(str(exc)), reason=reason)
    _require(
        reason == "routing_signature_invalid",
        f"tampered assignment must refuse routing_signature_invalid (got {reason!r})",
    )
    return ({"refused": reason, "nothing_activated": True}, ["ABT-01a"])


def step_abuse_unsigned_downgrade(ctx: DistributionContext) -> tuple[dict, list[str]]:
    refusals: dict[str, str] = {}
    stripped_channel = {
        key: value for key, value in ctx.channel_revisions[2].items() if key != "signature"
    }
    try:
        ctx.verify_routing(stripped_channel, "channel")
    except DistributionRefusal as exc:
        refusals["channel_stripped"] = exc.reason
    stripped_assignment = {
        key: value for key, value in ctx.assignment.items() if key != "signature"
    }
    try:
        ctx.verify_routing(stripped_assignment, "assignment")
    except DistributionRefusal as exc:
        refusals["assignment_stripped"] = exc.reason
    summary = ctx.registry.read_summary(ctx.bundle_shas["team-v2"])
    unsigned_summary = {key: value for key, value in summary.items() if key != "signature"}
    try:
        load_summary_document(unsigned_summary, ctx.carrier_public_keys)
    except DistributionRefusal as exc:
        refusals["summary_unsigned"] = exc.reason
    undeclared = dict(summary)
    undeclared["registry_hint"] = "unexpected"  # an undeclared envelope key
    try:
        load_summary_document(undeclared, ctx.carrier_public_keys)
    except DistributionRefusal as exc:
        refusals["summary_unknown_key"] = exc.reason
    smuggled = dict(summary)
    smuggled["profile_rules"] = ["fake.*"]  # a decision-20 denylisted field
    try:
        load_summary_document(smuggled, ctx.carrier_public_keys)
    except DistributionRefusal as exc:
        refusals["summary_forbidden_field"] = exc.reason
    future_version = json.loads(json.dumps(ctx.channel_revisions[2]))
    future_version["channel_version"] = 2  # schema-evolution downgrade probe
    try:
        ctx.verify_routing(future_version, "channel")
    except DistributionRefusal as exc:
        refusals["channel_version_2"] = exc.reason
    expected = {
        "channel_stripped": "routing_unsigned",
        "assignment_stripped": "routing_unsigned",
        "summary_unsigned": "unsigned_artifact_rejected",
        "summary_unknown_key": "schema_invalid",
        "summary_forbidden_field": "forbidden_field_rejected",
        "channel_version_2": "schema_invalid",
    }
    _require(refusals == expected, f"downgrade refusals drifted: {refusals}")
    for reason in sorted(set(refusals.values())):
        ctx.record_refusal(f"distribution downgrade refused: {reason}", reason=reason)
    return (
        {"refused": refusals, "nothing_activated": True},
        ["ABT-01a", "ABT-02b", "ABT-12b", "ABT-22a"],
    )


def step_abuse_stale_replay(ctx: DistributionContext) -> tuple[dict, list[str]]:
    # A legitimately signed but SUPERSEDED channel revision is re-delivered.
    reason = ""
    try:
        apply_channel(ctx, ctx.channel_revisions[1], ctx.assignment)
    except DistributionRefusal as exc:
        reason = exc.reason
        ctx.record_refusal(scrub_paths(str(exc)), reason=reason)
    _require(
        reason == "routing_revision_regression",
        f"stale channel replay must refuse revision regression (got {reason!r})",
    )
    _require(
        ctx.watermarks[(CHANNEL_NAME, ISSUER_KEY_ID)] == 2,
        "the applied watermark must be unchanged after the replay",
    )
    # Channel-name squatting: a same-named channel signed by a DIFFERENT
    # trusted key never satisfies an assignment naming owner key A.
    squatter = build_channel(
        CHANNEL_NAME,
        ctx.keys[OTHER_OWNER_KEY_ID],
        [
            {
                "bundle_sha256": ctx.bundle_shas["team-v1"],
                "published_at": _utc(ctx.now - 300),
                "status": "active",
            }
        ],
        revision=1,
    )
    squat_reason = ""
    try:
        apply_channel(ctx, squatter, ctx.assignment)
    except DistributionRefusal as exc:
        squat_reason = exc.reason
        ctx.record_refusal(scrub_paths(str(exc)), reason=squat_reason)
    _require(
        squat_reason == "channel_identity_mismatch",
        f"the squatted channel must refuse the identity pair (got {squat_reason!r})",
    )
    # ...while as its OWN identity it is a distinct channel with an
    # independent watermark (revision 1 is fine there: ABT-23b).
    _require(
        (CHANNEL_NAME, OTHER_OWNER_KEY_ID) not in ctx.watermarks,
        "the other-owner identity must have an independent (empty) watermark",
    )
    return (
        {
            "stale_replay_refused": reason,
            "watermark_unchanged": True,
            "squatting_refused": squat_reason,
            "independent_identity_watermarks": True,
        },
        ["ABT-04a", "ABT-08a", "ABT-23b"],
    )


def step_abuse_expired_assignment(ctx: DistributionContext) -> tuple[dict, list[str]]:
    expired = build_assignment(
        [AUDIENCE],
        CHANNEL_NAME,
        ISSUER_KEY_ID,
        "follow",
        ctx.keys[ISSUER_KEY_ID],
        revision=1,
        issued_at=_utc(ctx.now - 60 * DAY),
        expires_at=_utc(ctx.now - 30 * DAY),  # already past at the run clock
    )
    ctx.verify_routing(expired, "assignment")  # signed and well-formed...
    status, winner, named = resolve_assignments(
        [("expired-routing", expired)], list(MEMBER_AUDIENCES), now=ctx.now
    )
    _require(
        status == "expired" and winner == "" and named == ["expired-routing"],
        "an expired assignment must direct no NEW activation and be named loudly",
    )
    # ...but the already-activated bundle keeps working (decision 5): the
    # gateway still resolves the active bundle under the signed policy.
    state, _ = _resolve_gateway_profile_state(ctx.gateway_args())
    _require(
        isinstance(state, ActiveProfile)
        and state.provenance.bundle_sha256 == ctx.bundle_shas["team-v2"],
        "assignment expiry must never deactivate a verified bundle",
    )
    # With a live assignment alongside, resolution simply ignores the
    # expired one.
    status_mixed, winner_mixed, _ = resolve_assignments(
        [("expired-routing", expired), (ctx.assignment_label, ctx.assignment)],
        list(MEMBER_AUDIENCES),
        now=ctx.now,
    )
    _require(
        status_mixed == "ok" and winner_mixed == ctx.assignment_label,
        "a live assignment must win over an expired one",
    )
    # The CAPABILITY clock stays the bundle's own signed expiry (ABT-06a):
    # the same bundle keeps verifying offline at the harness clock and
    # refuses -32016 once an injected clock passes its expires_at.
    still_ok = verify_report(
        ctx.fetched_paths["team-v2"],
        ctx.store.trusted_keys_path,
        audience_ids=[AUDIENCE],
        now=ctx.now,
    )
    _require(still_ok["ok"] is True, "the bundle must keep verifying before expiry")
    beyond = ctx.now + 40 * DAY  # past the 30-day publish window
    expired_bundle = verify_report(
        ctx.fetched_paths["team-v2"],
        ctx.store.trusted_keys_path,
        audience_ids=[AUDIENCE],
        now=beyond,
    )
    _require(
        expired_bundle["ok"] is False and expired_bundle["code"] == BUNDLE_EXPIRED,
        "an injected clock past expires_at must refuse -32016 bundle_expired",
    )
    ctx.record_refusal(expired_bundle["message"], code=BUNDLE_EXPIRED)
    return (
        {
            "expired_assignment_status": "expired",
            "named_loudly": named,
            "active_bundle_kept_working": True,
            "live_assignment_wins": True,
            "injected_clock_refusal_code": BUNDLE_EXPIRED,
            "injected_clock_refusal_name": "bundle_expired",
        },
        ["ABT-04a", "ABT-06a"],
    )


def step_abuse_wrong_audience(ctx: DistributionContext) -> tuple[dict, list[str]]:
    misrouted = build_assignment(
        [WRONG_AUDIENCE],
        CHANNEL_NAME,
        ISSUER_KEY_ID,
        "pin",
        ctx.keys[ISSUER_KEY_ID],
        revision=1,
        issued_at=_utc(ctx.now - 600),
        expires_at=_utc(ctx.now + 60 * DAY),
        bundle_sha256=ctx.bundle_shas["other-team-v1"],
    )
    ctx.verify_routing(misrouted, "assignment")  # signed and well-formed...
    status, winner, _ = resolve_assignments(
        [("misrouted", misrouted)], list(MEMBER_AUDIENCES), now=ctx.now
    )
    _require(
        status == "none" and winner == "",
        "a misrouted assignment must be ignored (no audience intersection)",
    )
    # Forcing the other team's bundle anyway dies at the bundle's OWN
    # audience binding -- the unchanged E14 check (-32018).
    forced = verify_report(
        ctx.bundle_paths["other-team-v1"],
        ctx.store.trusted_keys_path,
        audience_ids=list(MEMBER_AUDIENCES),
        now=ctx.now,
    )
    _require(
        forced["ok"] is False and forced["code"] == BUNDLE_AUDIENCE_MISMATCH,
        "forcing the misrouted bundle must refuse -32018 bundle_audience_mismatch",
    )
    ctx.record_refusal(forced["message"], code=BUNDLE_AUDIENCE_MISMATCH)
    return (
        {
            "misrouted_assignment_ignored": True,
            "forced_refusal_code": BUNDLE_AUDIENCE_MISMATCH,
            "forced_refusal_name": "bundle_audience_mismatch",
        },
        ["ABT-09a"],
    )


def step_abuse_conflict_resolution(ctx: DistributionContext) -> tuple[dict, list[str]]:
    issuer = ctx.keys[ISSUER_KEY_ID]
    horizon = _utc(ctx.now + 60 * DAY)
    follow_team = build_assignment(
        [AUDIENCE], CHANNEL_NAME, ISSUER_KEY_ID, "follow", issuer,
        revision=3, issued_at=_utc(ctx.now - 40000), expires_at=horizon,
    )
    pin_team = build_assignment(
        [AUDIENCE], CHANNEL_NAME, ISSUER_KEY_ID, "pin", issuer,
        revision=1, issued_at=_utc(ctx.now - 80000), expires_at=horizon,
        bundle_sha256=ctx.bundle_shas["team-v1"],
    )
    follow_host = build_assignment(
        [HOST_AUDIENCE], CHANNEL_NAME, ISSUER_KEY_ID, "follow", issuer,
        revision=1, issued_at=_utc(ctx.now - 80000), expires_at=horizon,
    )
    pool = [
        ("follow-team-r3", follow_team),
        ("pin-team-r1", pin_team),
        ("follow-host-r1", follow_host),
    ]
    for _, document in pool:
        ctx.verify_routing(document, "assignment")
    # (a) host: beats team: -- identical across every input permutation.
    winners = set()
    for permutation in itertools.permutations(pool):
        status, winner, _ = resolve_assignments(
            list(permutation), list(MEMBER_AUDIENCES), now=ctx.now
        )
        _require(status == "ok", "permutation resolution must succeed")
        winners.add(winner)
    _require(winners == {"follow-host-r1"}, f"host specificity must win: {winners}")
    # (b) pin beats follow within the same specificity.
    status, winner, _ = resolve_assignments(
        [("follow-team-r3", follow_team), ("pin-team-r1", pin_team)],
        list(MEMBER_AUDIENCES),
        now=ctx.now,
    )
    _require(winner == "pin-team-r1", "pin must beat follow at equal specificity")
    # (c) highest revision, then latest issued_at.
    follow_team_r2 = build_assignment(
        [AUDIENCE], CHANNEL_NAME, ISSUER_KEY_ID, "follow", issuer,
        revision=2, issued_at=_utc(ctx.now - 30000), expires_at=horizon,
    )
    status, winner, _ = resolve_assignments(
        [("follow-team-r3", follow_team), ("follow-team-r2", follow_team_r2)],
        list(MEMBER_AUDIENCES),
        now=ctx.now,
    )
    _require(winner == "follow-team-r3", "the higher revision must win")
    later_issue = build_assignment(
        [AUDIENCE], CHANNEL_NAME, ISSUER_KEY_ID, "follow", issuer,
        revision=3, issued_at=_utc(ctx.now - 20000), expires_at=horizon,
    )
    status, winner, _ = resolve_assignments(
        [("follow-team-r3", follow_team), ("follow-team-r3-later", later_issue)],
        list(MEMBER_AUDIENCES),
        now=ctx.now,
    )
    _require(winner == "follow-team-r3-later", "the later issued_at must break the tie")
    # (d) a residual exact tie is refused LOUDLY: nothing new activates,
    # the last-activated bundle is kept, both files are named.
    twin = build_assignment(
        [AUDIENCE], CHANNEL_NAME, ISSUER_KEY_ID, "follow", issuer,
        revision=3, issued_at=_utc(ctx.now - 20000), expires_at=horizon,
    )
    state_before, _ = read_state(ctx.library)
    history_before = len(state_before["history"])
    status, winner, named = resolve_assignments(
        [("tie-a", later_issue), ("tie-b", twin)], list(MEMBER_AUDIENCES), now=ctx.now
    )
    _require(
        status == "tie" and winner == "" and named == ["tie-a", "tie-b"],
        "an exact tie must be refused with both files named",
    )
    ctx.record_refusal(
        "distribution: assignment conflict tie refused (tie-a, tie-b)", reason="assignment_tie"
    )
    state_after, _ = read_state(ctx.library)
    _require(
        len(state_after["history"]) == history_before
        and state_after["active_sha256"] == state_before["active_sha256"],
        "a refused tie must not change the library's active state",
    )
    gateway_state, _ = _resolve_gateway_profile_state(ctx.gateway_args())
    _require(
        isinstance(gateway_state, ActiveProfile),
        "the last-activated bundle must keep working after the tie refusal",
    )
    return (
        {
            "permutations_checked": 6,
            "specificity_winner": "follow-host-r1",
            "pin_beats_follow": True,
            "revision_then_issued_at": True,
            "tie_refused_loudly": named,
            "library_state_unchanged": True,
        },
        ["ABT-10a", "ABT-10b"],
    )


def step_abuse_poisoned_pointer(ctx: DistributionContext) -> tuple[dict, list[str]]:
    pointer = ctx.library.active_bundle_path
    original = pointer.read_bytes()
    document = json.loads(original.decode("utf-8"))
    document["audience"].append("org:everyone")  # post-signing tamper
    pointer.write_text(json.dumps(document), encoding="utf-8")
    state, _ = _resolve_gateway_profile_state(ctx.gateway_args())
    _require(
        isinstance(state, FailClosedProfile) and state.code == BUNDLE_SIGNATURE_INVALID,
        "a poisoned active pointer must fail closed with -32015 at gateway start",
    )
    ctx.record_refusal(state.message, code=BUNDLE_SIGNATURE_INVALID)
    # Recovery: re-activate through the library (re-verify + pointer copy).
    restored = activate_bundle(ctx.library, "team-v2", **ctx.verify_kwargs())
    _require(restored["activated"] is True, "re-activation must restore the pointer")
    state, _ = _resolve_gateway_profile_state(ctx.gateway_args())
    _require(isinstance(state, ActiveProfile), "the restored pointer must resolve again")
    return (
        {
            "poisoned_refusal_code": BUNDLE_SIGNATURE_INVALID,
            "poisoned_refusal_name": "bundle_signature_invalid",
            "tampered_content_never_governs": True,
            "restored_via_reactivation": True,
        },
        ["ABT-19a"],
    )


def step_abuse_revoked_rollback(ctx: DistributionContext) -> tuple[dict, list[str]]:
    revoked = revoke(
        ctx.store,
        bundle_sha256=ctx.bundle_shas["team-v2"],
        reason="distribution drill: routed bundle withdrawn",
        now=ctx.now,
    )
    _require(revoked["revoked"] is True, "trust revoke did not record the revocation")
    # The channel STILL marks the revoked sha active -- and that status is
    # demonstrably never a trust input: activation refuses -32017 anyway.
    _require(
        ctx.channel_revisions[2]["current"] == ctx.bundle_shas["team-v2"],
        "the lying channel must still point at the revoked sha",
    )
    refusal_code = 0
    refusal_message = ""
    try:
        activate_bundle(ctx.library, "team-v2", **ctx.verify_kwargs())
    except BundleLibraryError as exc:
        refusal_code = exc.code
        refusal_message = str(exc)
    _require(
        refusal_code == BUNDLE_REVOKED,
        f"activation must refuse -32017 bundle_revoked (got {refusal_code})",
    )
    state, _ = _resolve_gateway_profile_state(ctx.gateway_args())
    _require(
        isinstance(state, FailClosedProfile) and state.code == BUNDLE_REVOKED,
        "the stale active pointer must fail closed with bundle_revoked",
    )
    ctx.record_refusal(refusal_message or state.message, code=BUNDLE_REVOKED)
    # Recovery is ENTIRELY local: the carrier goes offline (the fixture
    # registry directory is renamed away) and the E20 rollback still walks
    # back to the last-good bundle from library state alone.
    registry_root = ctx.registry.root
    offline = registry_root.with_name(registry_root.name + "-offline")
    os.rename(registry_root, offline)
    try:
        rolled = rollback_bundle(ctx.library, **ctx.verify_kwargs())
        _require(rolled["rolled_back"] is True, "rollback did not re-activate a bundle")
        _require(
            rolled["sha256"] == ctx.bundle_shas["team-v1"],
            "rollback must walk back to the prior good bundle (team-v1)",
        )
        state, note = _resolve_gateway_profile_state(ctx.gateway_args())
        _require(
            isinstance(state, ActiveProfile)
            and state.provenance.bundle_sha256 == ctx.bundle_shas["team-v1"],
            f"gateway re-resolution after rollback failed: {note}",
        )
    finally:
        os.rename(offline, registry_root)
    ctx.audit.record(tool="tools_search", upstream="", ok=True, profile=state.name)
    return (
        {
            "revoked_sha_prefix": _prefix(ctx.bundle_shas["team-v2"]),
            "refusal_code": BUNDLE_REVOKED,
            "refusal_name": "bundle_revoked",
            "channel_status_never_trust_input": True,
            "gateway_fail_closed": True,
            "rolled_back_to_prefix": _prefix(ctx.bundle_shas["team-v1"]),
            "rollback_with_carrier_offline": True,
        },
        ["ABT-05a", "ABT-06b", "ABT-20b"],
    )


def step_audit_report(ctx: DistributionContext) -> tuple[dict, list[str]]:
    report = audit_inspector.build_report(ctx.audit.path, now=ctx.now)
    refusals = report["refusals"]
    observed = sorted(
        entry["code"] for entry in refusals["by_code"] if entry["code"] is not None
    )
    expected = sorted(
        {BUNDLE_SIGNATURE_INVALID, BUNDLE_EXPIRED, BUNDLE_REVOKED, BUNDLE_AUDIENCE_MISMATCH}
    )
    for code in expected:
        _require(code in observed, f"refusal code {code} is not visible to the inspector")
    _require(
        report["redaction"]["status"] == "PASS",
        "the audit redaction self-check did not pass",
    )
    return (
        {
            "rows_total": report["log"]["rows_total"],
            "refusal_rows": refusals["total"],
            "refusal_codes_observed": observed,
            "redaction_self_check": report["redaction"]["status"],
        },
        [],
    )


STEPS: tuple[tuple[str, object], ...] = (
    ("keygen", step_keygen),
    ("trust_import", step_trust_import),
    ("publish", step_publish),
    ("registry_seed", step_registry_seed),
    ("channel_publish", step_channel_publish),
    ("assignment_issue", step_assignment_issue),
    ("entitlement_gate", step_entitlement_gate),
    ("client_fetch", step_client_fetch),
    ("client_verify", step_client_verify),
    ("library_add", step_library_add),
    ("rollout_replay", step_rollout_replay),
    ("activate", step_activate),
    ("gateway_resolve", step_gateway_resolve),
    ("abuse_tampered_channel", step_abuse_tampered_channel),
    ("abuse_tampered_assignment", step_abuse_tampered_assignment),
    ("abuse_unsigned_downgrade", step_abuse_unsigned_downgrade),
    ("abuse_stale_replay", step_abuse_stale_replay),
    ("abuse_expired_assignment", step_abuse_expired_assignment),
    ("abuse_wrong_audience", step_abuse_wrong_audience),
    ("abuse_conflict_resolution", step_abuse_conflict_resolution),
    ("abuse_poisoned_pointer", step_abuse_poisoned_pointer),
    ("abuse_revoked_rollback", step_abuse_revoked_rollback),
    ("audit_report", step_audit_report),
)
STEP_NAMES = tuple(name for name, _ in STEPS)


# ---------------------------------------------------------------------------
# Runner.


def run_distribution_e2e(
    until: str = "all",
    base_dir: Path | None = None,
    before_step=None,
) -> dict:
    """Run the workflow up to and including step ``until`` ('all' = step 23).

    ``base_dir=None`` creates (and afterwards removes) a fresh temp
    directory; an explicit directory keeps every write inside it. The real
    library root, managed trust store, and default audit log are never
    touched. ``before_step(name, ctx)`` is a test-only injection hook called
    before each step. The workflow stops at the first failing step.
    """
    if not cryptography_available():
        raise RuntimeError(
            "the distribution fixture harness needs the optional 'cryptography' "
            "package for real Ed25519 (pip install cryptography); the E19 "
            "publisher has no fallback signature scheme"
        )
    if until != "all" and until not in STEP_NAMES:
        raise ValueError(f"unknown step {until!r}; known: {', '.join(STEP_NAMES)}")
    selected = STEPS if until == "all" else STEPS[: STEP_NAMES.index(until) + 1]

    own_temp = base_dir is None
    base = (
        Path(tempfile.mkdtemp(prefix="uls-mcp-distribution-e2e-"))
        if own_temp
        else Path(base_dir)
    )
    base.mkdir(parents=True, exist_ok=True)
    saved_env = {name: os.environ.pop(name, None) for name in _NEUTRALIZED_ENV}
    try:
        ctx = DistributionContext(base, time.time())
        entries: list[dict] = []
        coverage: set[str] = set()
        for index, (name, fn) in enumerate(selected, start=1):
            if before_step is not None:
                before_step(name, ctx)
            started = time.perf_counter()
            try:
                facts, abt = fn(ctx)
                ok = True
            except (
                StepError,
                DistributionRefusal,
                BundleLibraryError,
                PublisherError,
                TrustStoreError,
                FileNotFoundError,
                OSError,
                KeyError,
                ValueError,
            ) as exc:
                ok = False
                facts = {"error": scrub_paths(str(exc))[:MAX_ERROR_CHARS]}
                abt = []
            coverage.update(abt)
            entries.append(
                {
                    "step": index,
                    "name": name,
                    "ok": ok,
                    "facts": facts,
                    "abt": sorted(abt),
                    "duration_ms": round((time.perf_counter() - started) * 1000.0, 3),
                }
            )
            if not ok:
                break
        steps_ok = sum(1 for entry in entries if entry["ok"])
        all_ok = steps_ok == len(selected) and len(entries) == len(selected)
        return {
            "report_type": REPORT_TYPE,
            "schema_version": REPORT_SCHEMA_VERSION,
            "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "mode": "fixture",
            "ed25519": True,
            "clock": _utc(ctx.now),
            "steps": entries,
            "abt_coverage": sorted(coverage),
            "summary": {
                "steps_total": len(STEPS),
                "steps_selected": len(selected),
                "steps_ok": steps_ok,
                "abt_claimed": len(coverage),
                "all_ok": all_ok,
            },
            "exit_code": 0 if all_ok else 1,
        }
    finally:
        for name, value in saved_env.items():
            if value is not None:
                os.environ[name] = value
        if own_temp:
            shutil.rmtree(base, ignore_errors=True)


# ---------------------------------------------------------------------------
# Rendering and CLI.


def _fact_text(value: object) -> str:
    if isinstance(value, (list, tuple)):
        return "[" + ", ".join(_fact_text(item) for item in value) + "]"
    if isinstance(value, dict):
        # ``key: value`` (not ``key=value``): a joined ``a=b`` pair of long
        # reason names would look like one 40+ char base64-ish blob to the
        # audit writer's leak heuristics the tests reuse.
        return "{" + ", ".join(f"{key}: {_fact_text(val)}" for key, val in value.items()) + "}"
    return str(value)


def format_distribution_report(report: dict) -> str:
    lines = [
        "MCP registered/team distribution fixture E2E harness (fixture mode)",
        "fixture registry -> signed channel/assignment -> entitlement gate -> "
        "client fetch -> verify -> library -> rollout/replay -> activate -> "
        "gateway -> abuse battery -> incident rollback -> audit/report",
        f"clock: {report['clock']}",
        "",
    ]
    total = report["summary"]["steps_total"]
    for entry in report["steps"]:
        mark = "ok" if entry["ok"] else "FAILED"
        suffix = f" [{', '.join(entry['abt'])}]" if entry["abt"] else ""
        lines.append(
            f"[{entry['step']:>2}/{total}] {entry['name']}: {mark} "
            f"({entry['duration_ms']} ms){suffix}"
        )
        for key in sorted(entry["facts"]):
            lines.append(f"    {key} = {_fact_text(entry['facts'][key])}")
    summary = report["summary"]
    lines.append("")
    lines.append(
        f"ABT coverage ({summary['abt_claimed']}): "
        + ", ".join(report["abt_coverage"])
    )
    lines.append(
        f"summary: {summary['steps_ok']} of {summary['steps_selected']} selected "
        f"step(s) ok (workflow has {summary['steps_total']}) -- "
        + ("ALL OK" if summary["all_ok"] else "E2E FAILED")
    )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Fixture-only E2E harness for the planned registered/team MCP "
            "profile distribution flow: a local directory stands in for the "
            "registry (E24 access-check semantics modeled as fixture "
            "functions), the E23 channel/assignment files are real and "
            "signed, and the whole client side runs the REAL E14/E15/E16/"
            "E17/E20 machinery plus the gateway resolution. Offline: no "
            "hosted calls, no network, no production keys, no OAuth, no "
            "telemetry; ephemeral DEV keys inside a private temp directory."
        )
    )
    parser.add_argument(
        "--fixture-mode",
        action="store_true",
        help=(
            "Accepted for symmetry with the other runners: fixture mode is "
            "the ONLY mode this harness has (nothing hosted exists to call)."
        ),
    )
    parser.add_argument("--json", action="store_true", help="Print the JSON report.")
    parser.add_argument(
        "--out",
        default="",
        metavar="DIR",
        help="Directory to write distribution-e2e-report.json and .txt into.",
    )
    parser.add_argument(
        "--step",
        default="all",
        help=(
            "Run the workflow up to and including this step (earlier steps are "
            "prerequisites of the one shared flow and stay in the report), or "
            "'all' (default). Known: " + ", ".join(STEP_NAMES) + "."
        ),
    )
    args = parser.parse_args(argv)
    try:
        report = run_distribution_e2e(until=args.step)
    except (ValueError, RuntimeError) as exc:
        print(str(exc), file=sys.stderr)
        return 2
    serialized = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True)
    if args.out:
        out_dir = Path(args.out)
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "distribution-e2e-report.json").write_text(
            serialized + "\n", encoding="utf-8"
        )
        (out_dir / "distribution-e2e-report.txt").write_text(
            format_distribution_report(report) + "\n", encoding="utf-8"
        )
    print(serialized if args.json else format_distribution_report(report))
    return int(report["exit_code"])


if __name__ == "__main__":
    raise SystemExit(main())
