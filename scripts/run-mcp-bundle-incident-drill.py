"""E18: MCP signed-profile-bundle incident drill (fixture mode only).

A self-contained operational drill for every documented signed-bundle
incident class (docs/mcp-incident-runbook.md). For each scenario it

1. builds a known-good fixture state in a private temp directory -- an
   ephemeral keypair, a signed bundle, and an E15 managed trust store
   (the REAL ``trust_store`` functions write it);
2. injects the incident (tampering, key loss/expiry, revocation, CRL
   outage, audience mismatch, store corruption);
3. runs the REAL E14 verification (``resolve_bundle_state`` -- never a
   reimplementation) and asserts the expected fail-closed refusal code;
4. executes the documented RECOVERY steps with the same operator-facing
   machinery the runbook names (``trust_store.import_key`` / ``revoke`` /
   ``doctor_report``, bundle re-issue with a rotated key, CRL restore,
   audience fix, rollback to the raw ``--profiles`` path or open mode)
   and proves verification returns to a working state.

Refusals are recorded through the REAL redacted audit writer
(:class:`unlimited_skills.mcp.audit.AuditLog`) and the E11 inspector
(:func:`unlimited_skills.mcp.audit_inspector.build_report`) is run over the
drill's own log to prove the refusal codes are visible to audit reporting
and the redaction self-check passes.

Fixture-only by construction: everything lives in one temp directory (or an
explicit ``base_dir``); ephemeral keys are generated per run and never
persisted outside it; there is no network, no telemetry, no subprocess, and
the real library root / managed trust store / audit log are never touched.
Signing uses the optional ``cryptography`` package (real Ed25519) when
present; otherwise a clearly-marked TEST-ONLY deterministic HMAC backend
(the same stance as ``tests/test_mcp_bundle_verification.py``) keeps the
drill runnable -- it is NOT a signature scheme and exists only so the
verification ORDER and refusal paths stay exercised.

Exit code 0 only when EVERY selected scenario both refuses with the
expected code AND recovers, and the audit report shows the refusals with a
passing redaction self-check. The ``--json`` report validates against
``schemas/mcp-incident-drill-report.schema.json``.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import hmac
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

from unlimited_skills.mcp import audit_inspector  # noqa: E402
from unlimited_skills.mcp.audit import AuditLog  # noqa: E402
from unlimited_skills.mcp.bundles import (  # noqa: E402
    BUNDLE_AUDIENCE_MISMATCH,
    BUNDLE_EXPIRED,
    BUNDLE_KEY_MISSING,
    BUNDLE_REVOKED,
    BUNDLE_SIGNATURE_INVALID,
    BundleFailClosed,
    SignatureBackend,
    canonical_bundle_bytes,
    resolve_bundle_state,
    _parse_timestamp,
)
from unlimited_skills.mcp.profiles import ActiveProfile, resolve_profile_state  # noqa: E402
from unlimited_skills.mcp.trust_store import (  # noqa: E402
    TrustStore,
    doctor_report,
    import_key,
    revoke,
)

REPORT_TYPE = "mcp-incident-drill-report"
REPORT_SCHEMA_VERSION = 1

# The drill's injected clock (epoch seconds): every verification call pins
# ``now`` so the drill is deterministic and independent of the host clock.
DRILL_CLOCK_TEXT = "2026-07-01T00:00:00Z"
DRILL_CLOCK = _parse_timestamp(DRILL_CLOCK_TEXT)

KEY_ID = "drill-issuer-2026"
ROTATED_KEY_ID = "drill-issuer-2026-rotated"
AUDIENCE_OK = "team:drill"
AUDIENCE_WRONG = "team:somewhere-else"

CODE_NAMES = {
    BUNDLE_SIGNATURE_INVALID: "bundle_signature_invalid",
    BUNDLE_EXPIRED: "bundle_expired",
    BUNDLE_REVOKED: "bundle_revoked",
    BUNDLE_AUDIENCE_MISMATCH: "bundle_audience_mismatch",
    BUNDLE_KEY_MISSING: "bundle_key_missing",
}


# ---------------------------------------------------------------------------
# Fixture issuers: ephemeral real Ed25519 when available, else a TEST-ONLY
# deterministic fake (mirrors tests/test_mcp_bundle_verification.py).


class _FakeHmacBackend(SignatureBackend):
    """TEST-ONLY: HMAC-SHA256 keyed by the 'public key'. NOT a signature
    scheme (anyone holding the verification key can forge). Used only when
    the optional ``cryptography`` package is absent, so the drill's refusal
    and recovery paths stay runnable everywhere."""

    name = "test-only-hmac"

    def verify(self, public_key: bytes, message: bytes, signature: bytes) -> bool:
        return hmac.compare_digest(hmac.new(public_key, message, "sha256").digest(), signature)


class DrillIssuer:
    """Ephemeral fixture issuer: keypairs and detached signatures.

    Keys are generated per run inside the drill and never written anywhere
    except the fixture trust store under the drill's temp directory.
    """

    def __init__(self) -> None:
        try:
            from cryptography.hazmat.primitives.asymmetric.ed25519 import (  # noqa: F401
                Ed25519PrivateKey,
            )

            from unlimited_skills.mcp.bundles import CryptographyEd25519Backend

            self.backend: SignatureBackend = CryptographyEd25519Backend()
            self.real_ed25519 = True
        except ImportError:  # pragma: no cover - host without cryptography
            self.backend = _FakeHmacBackend()
            self.real_ed25519 = False

    def new_key(self) -> tuple[object, bytes]:
        """(private handle, raw 32-byte public key)."""
        if self.real_ed25519:
            from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
            from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

            private = Ed25519PrivateKey.generate()
            return private, private.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
        public = os.urandom(32)
        return public, public  # the MAC key doubles as the "public" key

    def sign(self, document: dict, private: object, key_id: str) -> dict:
        message = canonical_bundle_bytes(document)
        if self.real_ed25519:
            signature = private.sign(message)  # type: ignore[attr-defined]
        else:
            signature = hmac.new(private, message, "sha256").digest()  # type: ignore[arg-type]
        document["signature"] = {
            "algorithm": "ed25519",
            "key_id": key_id,
            "value": base64.b64encode(signature).decode("ascii"),
        }
        return document


# ---------------------------------------------------------------------------
# Fixture builders.


def base_bundle(key_id: str = KEY_ID) -> dict:
    return {
        "bundle_version": 1,
        "issuer": {"key_id": key_id, "display": "Drill platform team"},
        "audience": [AUDIENCE_OK, "host:drill-ci"],
        "issued_at": "2026-06-01T00:00:00Z",
        "expires_at": "2026-09-01T00:00:00Z",
        "allowed_upstream_namespaces": ["fake.*"],
        "default_profile": "dev",
        "profiles": {
            "dev": {"visible": ["fake.*"], "callable": ["fake.*"]},
            "reviewer": {"extends": "dev", "visible": ["fake.echo"], "callable": ["fake.echo"]},
        },
    }


def write_json(path: Path, document: dict) -> Path:
    path.write_text(json.dumps(document), encoding="utf-8")
    return path


EMPTY_CRL = {"schema_version": 1, "revoked_bundles": [], "revoked_key_ids": []}


class ScenarioContext:
    """One scenario's private fixture directory plus the shared issuer."""

    def __init__(self, issuer: DrillIssuer, directory: Path) -> None:
        self.issuer = issuer
        self.dir = directory
        self.store = TrustStore(directory / "trust-store")

    def import_public(self, key_id: str, public: bytes, not_after: str = "") -> None:
        import_key(
            self.store,
            key_id=key_id,
            public_key_b64=base64.b64encode(public).decode("ascii"),
            display="Drill issuer key",
            not_after=not_after,
            now=DRILL_CLOCK,
        )

    def issue(self, mutate=None, key_id: str = KEY_ID, private=None, name: str = "bundle.json") -> Path:
        document = base_bundle(key_id)
        if mutate is not None:
            mutate(document)
        self.issuer.sign(document, private, key_id)
        return write_json(self.dir / name, document)

    def verify(self, bundle_path: Path, audience: str = AUDIENCE_OK, now: float = DRILL_CLOCK):
        return resolve_bundle_state(
            bundle_path,
            trusted_keys_path=self.store.trusted_keys_path,
            cli_name="",
            env_name="",
            audience_ids=[audience],
            now=now,
            backend=self.issuer.backend,
        )


def _refused(state: object, code: int) -> bool:
    return isinstance(state, BundleFailClosed) and state.code == code


def _observed_code(state: object) -> int:
    return state.code if isinstance(state, BundleFailClosed) else 0


# ---------------------------------------------------------------------------
# Scenarios. Each returns the per-scenario report entry plus the fail-closed
# state for the audit log. The baseline (valid bundle + trust store) is
# always proven BEFORE the incident is injected.


def scenario_bad_signature(ctx: ScenarioContext) -> tuple[dict, BundleFailClosed]:
    private, public = ctx.issuer.new_key()
    ctx.import_public(KEY_ID, public)
    bundle_path = ctx.issue(private=private)
    assert isinstance(ctx.verify(bundle_path), ActiveProfile), "baseline must verify"
    # Incident: post-signing tampering (an attacker widens the audience).
    document = json.loads(bundle_path.read_text(encoding="utf-8"))
    document["audience"].append("org:everyone")
    write_json(bundle_path, document)
    failure = ctx.verify(bundle_path)
    refusal_ok = _refused(failure, BUNDLE_SIGNATURE_INVALID)
    # Recovery: discard the tampered artifact and re-issue -- re-sign the
    # intended document with the still-trusted key, then re-verify.
    reissued = ctx.issue(private=private, name="bundle-reissued.json")
    recovered = isinstance(ctx.verify(reissued), ActiveProfile)
    return _entry(
        "bad_signature",
        "bundle file modified after signing (audience widened by an attacker)",
        BUNDLE_SIGNATURE_INVALID,
        failure,
        refusal_ok,
        [
            "quarantine the tampered bundle file (keep it for forensics)",
            "re-issue: re-sign the intended bundle document with the trusted signing key",
            "re-verify: restart the gateway against the re-issued bundle",
        ],
        recovered,
    )


def _entry(
    name: str,
    incident: str,
    expected_code: int,
    failure: object,
    refusal_ok: bool,
    recovery_steps: list[str],
    recovered: bool,
) -> tuple[dict, BundleFailClosed | None]:
    entry = {
        "scenario": name,
        "incident": incident,
        "expected_code": expected_code,
        "expected_name": CODE_NAMES[expected_code],
        "observed_code": _observed_code(failure),
        "refusal_ok": bool(refusal_ok),
        "fail_closed": isinstance(failure, BundleFailClosed),
        "recovery_steps": recovery_steps,
        "recovered_ok": bool(recovered),
    }
    return entry, failure if isinstance(failure, BundleFailClosed) else None


def scenario_unknown_key(ctx: ScenarioContext) -> tuple[dict, BundleFailClosed | None]:
    private_a, public_a = ctx.issuer.new_key()
    ctx.import_public(KEY_ID, public_a)
    baseline = ctx.issue(private=private_a)
    assert isinstance(ctx.verify(baseline), ActiveProfile), "baseline must verify"
    # Incident: a bundle arrives signed by a NEW key that was never imported.
    private_b, public_b = ctx.issuer.new_key()
    new_bundle = ctx.issue(key_id=ROTATED_KEY_ID, private=private_b, name="bundle-new-key.json")
    failure = ctx.verify(new_bundle)
    refusal_ok = _refused(failure, BUNDLE_KEY_MISSING)
    # Recovery: import the new key's PUBLIC half through the managed store.
    ctx.import_public(ROTATED_KEY_ID, public_b)
    recovered = isinstance(ctx.verify(new_bundle), ActiveProfile)
    return _entry(
        "unknown_key",
        "bundle signed by a key_id that is not in the local trusted-keys file",
        BUNDLE_KEY_MISSING,
        failure,
        refusal_ok,
        [
            "confirm with the issuer that the new key_id is legitimate (out of band)",
            "import the PUBLIC key: unlimited-skills mcp trust import --key-id <id> "
            "--public-key <base64 public key>",
            "re-verify: restart the gateway against the same bundle",
        ],
        recovered,
    )


def scenario_expired_key(ctx: ScenarioContext) -> tuple[dict, BundleFailClosed | None]:
    private, public = ctx.issuer.new_key()
    ctx.import_public(KEY_ID, public, not_after="2026-06-15T00:00:00Z")
    bundle_path = ctx.issue(private=private)
    before_deadline = _parse_timestamp("2026-06-10T00:00:00Z")
    assert isinstance(
        ctx.verify(bundle_path, now=before_deadline), ActiveProfile
    ), "baseline must verify before the key's not_after"
    # Incident: time passes the key's local not_after trust deadline (the
    # E14 mapping: an expired key is a missing key, -32019).
    failure = ctx.verify(bundle_path)  # DRILL_CLOCK is past 2026-06-15
    refusal_ok = _refused(failure, BUNDLE_KEY_MISSING)
    # Recovery: rotate -- import the NEW key under a new key_id and re-issue
    # the bundle signed by it (the E14 rotation design: key_id selects).
    new_private, new_public = ctx.issuer.new_key()
    ctx.import_public(ROTATED_KEY_ID, new_public, not_after="2027-01-01T00:00:00Z")
    rotated = ctx.issue(key_id=ROTATED_KEY_ID, private=new_private, name="bundle-rotated.json")
    recovered = isinstance(ctx.verify(rotated), ActiveProfile)
    return _entry(
        "expired_key",
        "signing key past its local not_after trust deadline (expired, not rotated)",
        BUNDLE_KEY_MISSING,
        failure,
        refusal_ok,
        [
            "rotate: import the NEW public key under a new key_id "
            "(unlimited-skills mcp trust import --key-id <new id> --public-key "
            "<base64 public key> --not-after <deadline>)",
            "have the issuer re-sign the bundle with the new key",
            "re-verify, then remove the expired key entry after the overlap window",
        ],
        recovered,
    )


def scenario_expired_bundle(ctx: ScenarioContext) -> tuple[dict, BundleFailClosed | None]:
    private, public = ctx.issuer.new_key()
    ctx.import_public(KEY_ID, public)
    bundle_path = ctx.issue(private=private)
    assert isinstance(ctx.verify(bundle_path), ActiveProfile), "baseline must verify"
    # Incident: the clock moves past expires_at (+300 s skew).
    after_expiry = _parse_timestamp("2026-10-01T00:00:00Z")
    failure = ctx.verify(bundle_path, now=after_expiry)
    refusal_ok = _refused(failure, BUNDLE_EXPIRED)

    # Recovery: the issuer re-issues with a fresh signed validity window.
    def fresh_window(document: dict) -> None:
        document["issued_at"] = "2026-09-15T00:00:00Z"
        document["expires_at"] = "2026-12-15T00:00:00Z"

    reissued = ctx.issue(mutate=fresh_window, private=private, name="bundle-fresh-window.json")
    recovered = isinstance(ctx.verify(reissued, now=after_expiry), ActiveProfile)
    return _entry(
        "expired_bundle",
        "current time outside the bundle's signed validity window",
        BUNDLE_EXPIRED,
        failure,
        refusal_ok,
        [
            "request a re-issued bundle with a fresh issued_at/expires_at window",
            "verify the host clock is correct before assuming the bundle is stale",
            "re-verify: restart the gateway against the re-issued bundle",
        ],
        recovered,
    )


def _crl_bundle(ctx: ScenarioContext, private) -> Path:
    write_json(ctx.store.crl_path, dict(EMPTY_CRL))

    def declare_crl(document: dict) -> None:
        document["revocation"] = {"crl_path": str(ctx.store.crl_path)}

    return ctx.issue(mutate=declare_crl, private=private, name="bundle-with-crl.json")


def scenario_revoked_bundle(ctx: ScenarioContext) -> tuple[dict, BundleFailClosed | None]:
    private, public = ctx.issuer.new_key()
    ctx.import_public(KEY_ID, public)
    bundle_path = _crl_bundle(ctx, private)
    assert isinstance(ctx.verify(bundle_path), ActiveProfile), "baseline must verify"
    # Incident: the operator revokes the compromised bundle by SHA-256
    # through the managed store (append-only local CRL).
    sha256 = hashlib.sha256(bundle_path.read_bytes()).hexdigest()
    revoke(ctx.store, bundle_sha256=sha256, reason="drill: bundle withdrawn", now=DRILL_CLOCK)
    failure = ctx.verify(bundle_path)
    refusal_ok = _refused(failure, BUNDLE_REVOKED)

    # Recovery: issue a CORRECTED bundle (different bytes, different
    # SHA-256); the CRL entry stays forever (history is never deleted) and
    # keeps refusing the withdrawn artifact.
    def corrected(document: dict) -> None:
        document["comment"] = "re-issued after revocation (drill)"
        document["revocation"] = {"crl_path": str(ctx.store.crl_path)}

    reissued = ctx.issue(mutate=corrected, private=private, name="bundle-corrected.json")
    recovered = isinstance(ctx.verify(reissued), ActiveProfile) and _refused(
        ctx.verify(bundle_path), BUNDLE_REVOKED
    )
    return _entry(
        "revoked_bundle",
        "bundle SHA-256 listed in the local CRL (operator revocation)",
        BUNDLE_REVOKED,
        failure,
        refusal_ok,
        [
            "revoke the withdrawn artifact: unlimited-skills mcp trust revoke "
            "--bundle-sha256 <hash> --reason <why>",
            "issue a corrected bundle (new bytes = new SHA-256); never edit the CRL history",
            "re-verify the corrected bundle; confirm the revoked one still refuses",
        ],
        recovered,
    )


def scenario_crl_outage(ctx: ScenarioContext) -> tuple[dict, BundleFailClosed | None]:
    private, public = ctx.issuer.new_key()
    ctx.import_public(KEY_ID, public)
    bundle_path = _crl_bundle(ctx, private)
    assert isinstance(ctx.verify(bundle_path), ActiveProfile), "baseline must verify"
    # Incident: the declared CRL becomes unreadable -- "cannot prove
    # not-revoked" is fail-closed bundle_revoked, never "trusted".
    ctx.store.crl_path.write_text("{not json", encoding="utf-8")
    failure = ctx.verify(bundle_path)
    refusal_ok = _refused(failure, BUNDLE_REVOKED)
    detected = doctor_report(ctx.store, now=DRILL_CLOCK)["exit_code"] == 1
    # Recovery: restore the CRL file from the managed store's known-good
    # state (here: the empty CRL the fixture started from), doctor-check it,
    # and re-verify.
    write_json(ctx.store.crl_path, dict(EMPTY_CRL))
    doctor_ok = doctor_report(ctx.store, now=DRILL_CLOCK)["exit_code"] == 0
    recovered = detected and doctor_ok and isinstance(ctx.verify(bundle_path), ActiveProfile)
    return _entry(
        "crl_outage",
        "declared CRL file unreadable (revocation status unprovable, fail-closed)",
        BUNDLE_REVOKED,
        failure,
        refusal_ok,
        [
            "detect: unlimited-skills mcp trust doctor (flags the unreadable CRL, exit 1)",
            "restore the CRL file from backup or re-create it from the revocation history "
            "in the store metadata (never silently drop revocations)",
            "re-check: unlimited-skills mcp trust doctor (exit 0), then re-verify",
        ],
        recovered,
    )


def scenario_wrong_audience(ctx: ScenarioContext) -> tuple[dict, BundleFailClosed | None]:
    private, public = ctx.issuer.new_key()
    ctx.import_public(KEY_ID, public)
    bundle_path = ctx.issue(private=private)
    assert isinstance(ctx.verify(bundle_path), ActiveProfile), "baseline must verify"
    # Incident: this consumer presents an identifier outside the bundle's
    # signed audience (mis-deployment of another team's bundle).
    failure = ctx.verify(bundle_path, audience=AUDIENCE_WRONG)
    refusal_ok = _refused(failure, BUNDLE_AUDIENCE_MISMATCH)
    # Recovery: fix the consumer's own identifier (--audience-id or the
    # UNLIMITED_SKILLS_MCP_AUDIENCE env var) -- or obtain the bundle issued
    # for THIS audience; the refusal message names both sides.
    recovered = isinstance(ctx.verify(bundle_path, audience=AUDIENCE_OK), ActiveProfile)
    return _entry(
        "wrong_audience",
        "local audience identifiers do not intersect the bundle's signed audience",
        BUNDLE_AUDIENCE_MISMATCH,
        failure,
        refusal_ok,
        [
            "compare both sides in the refusal message (it names the bundle audience and "
            "the local identifiers)",
            "fix the consumer identifier (--audience-id / UNLIMITED_SKILLS_MCP_AUDIENCE) "
            "or obtain the bundle issued for this audience",
            "re-verify: restart the gateway with the corrected identifier",
        ],
        recovered,
    )


def scenario_operator_rollback(ctx: ScenarioContext) -> tuple[dict, BundleFailClosed | None]:
    from unlimited_skills.commands.mcp import _resolve_gateway_profile_state

    private, public = ctx.issuer.new_key()
    ctx.import_public(KEY_ID, public)
    bundle_path = ctx.issue(private=private)
    assert isinstance(ctx.verify(bundle_path), ActiveProfile), "baseline must verify"
    # Incident: the bundle breaks (tampered here) while a fix is prepared;
    # the gateway is fail-closed refuse-all in the meantime.
    document = json.loads(bundle_path.read_text(encoding="utf-8"))
    document["expires_at"] = "2027-09-01T00:00:00Z"  # post-signing edit
    write_json(bundle_path, document)
    failure = ctx.verify(bundle_path)
    refusal_ok = _refused(failure, BUNDLE_SIGNATURE_INVALID)
    # Recovery (containment): the operator rolls back to a raw local
    # --profiles file -- enforcement continues, but signed provenance, the
    # audience binding, and the namespace ceiling are LOST until the bundle
    # is fixed. Open mode (no profile flags) is the last resort and loses
    # enforcement entirely.
    local_path = write_json(
        ctx.dir / "local-profiles.json",
        {
            "schema_version": 1,
            "default_profile": "dev",
            "profiles": {"dev": {"visible": ["fake.echo"], "callable": ["fake.echo"]}},
        },
    )
    raw_state = resolve_profile_state(local_path, cli_name="", env_name="")
    raw_ok = (
        isinstance(raw_state, ActiveProfile)
        and raw_state.name == "dev"
        and raw_state.is_callable("fake", "echo")
        and not raw_state.is_visible("fake", "add")
        and raw_state.provenance is None  # the raw path carries no bundle provenance
    )
    open_state, open_note = _resolve_gateway_profile_state(
        SimpleNamespace(
            profiles="",
            profile="",
            profile_bundle="",
            trusted_keys="",
            audience_id=None,
            require_signed_profiles=False,
        )
    )
    open_ok = open_state is None and "open mode" in open_note
    return _entry(
        "operator_rollback",
        "bundle fail-closed; operator rolls back to the raw --profiles path "
        "(or open mode) while the bundle is re-issued",
        BUNDLE_SIGNATURE_INVALID,
        failure,
        refusal_ok,
        [
            "rollback: restart the gateway with --profiles <local file> and WITHOUT "
            "--profile-bundle (raw E10 enforcement keeps working)",
            "accept what is lost during rollback: signed provenance, the audience "
            "binding, the namespace ceiling, and the --require-signed-profiles policy",
            "last resort: open no-profiles mode (no flags) loses ALL profile "
            "enforcement -- record the decision and restore the bundle quickly",
        ],
        raw_ok and open_ok,
    )


def scenario_trust_store_recovery(ctx: ScenarioContext) -> tuple[dict, BundleFailClosed | None]:
    private, public = ctx.issuer.new_key()
    ctx.import_public(KEY_ID, public)
    bundle_path = ctx.issue(private=private)
    assert isinstance(ctx.verify(bundle_path), ActiveProfile), "baseline must verify"
    # Incident: the managed trusted-keys file is corrupted on disk.
    ctx.store.trusted_keys_path.write_text("{not json", encoding="utf-8")
    failure = ctx.verify(bundle_path)
    refusal_ok = _refused(failure, BUNDLE_KEY_MISSING)
    detected = doctor_report(ctx.store, now=DRILL_CLOCK)["exit_code"] == 1
    # Recovery: remove the corrupt file and rebuild the store by re-importing
    # the known public keys through the real import path (atomic write +
    # strict round-trip), then doctor-check and re-verify.
    ctx.store.trusted_keys_path.unlink()
    ctx.import_public(KEY_ID, public)
    doctor_ok = doctor_report(ctx.store, now=DRILL_CLOCK)["exit_code"] == 0
    recovered = detected and doctor_ok and isinstance(ctx.verify(bundle_path), ActiveProfile)
    return _entry(
        "trust_store_recovery",
        "managed trusted-keys file corrupted (verification cannot load any key)",
        BUNDLE_KEY_MISSING,
        failure,
        refusal_ok,
        [
            "detect: unlimited-skills mcp trust doctor (flags the malformed file, exit 1)",
            "remove the corrupt trusted-keys file and rebuild by re-importing every "
            "known PUBLIC key: unlimited-skills mcp trust import ...",
            "re-check: unlimited-skills mcp trust doctor (exit 0), then re-verify",
        ],
        recovered,
    )


SCENARIOS = {
    "bad_signature": scenario_bad_signature,
    "unknown_key": scenario_unknown_key,
    "expired_key": scenario_expired_key,
    "expired_bundle": scenario_expired_bundle,
    "revoked_bundle": scenario_revoked_bundle,
    "crl_outage": scenario_crl_outage,
    "wrong_audience": scenario_wrong_audience,
    "operator_rollback": scenario_operator_rollback,
    "trust_store_recovery": scenario_trust_store_recovery,
}


# ---------------------------------------------------------------------------
# Drill runner.


def run_drill(scenario_names: list[str] | None = None, base_dir: Path | None = None) -> dict:
    """Run the selected scenarios in a private directory and build the report.

    ``base_dir=None`` creates (and afterwards removes) a fresh temp
    directory; passing an explicit directory keeps every write inside it.
    The drill never reads or writes the real library root, managed trust
    store, or audit log.
    """
    names = list(scenario_names or SCENARIOS)
    for name in names:
        if name not in SCENARIOS:
            raise ValueError(f"unknown scenario {name!r}; known: {', '.join(SCENARIOS)}")
    issuer = DrillIssuer()
    own_temp = base_dir is None
    base = Path(tempfile.mkdtemp(prefix="uls-mcp-incident-drill-")) if own_temp else Path(base_dir)
    base.mkdir(parents=True, exist_ok=True)
    try:
        audit_path = base / "audit" / "mcp-audit.jsonl"
        audit = AuditLog(audit_path)
        audit.record(tool="tools_search", upstream="", ok=True, profile="dev")
        entries: list[dict] = []
        for name in names:
            scenario_dir = base / name
            scenario_dir.mkdir(parents=True, exist_ok=True)
            started = time.perf_counter()
            entry, failure = SCENARIOS[name](ScenarioContext(issuer, scenario_dir))
            entry["duration_ms"] = round((time.perf_counter() - started) * 1000.0, 3)
            entries.append(entry)
            if failure is not None:
                # The REAL redacted writer records the refusal exactly as
                # operations would see it: the fail-closed message (path
                # scrubbed, capped) plus the explicit refusal code.
                audit.record(
                    tool="tools_call",
                    upstream="fake",
                    ok=False,
                    error=failure.message,
                    profile=failure.requested or "",
                    extra={"code": failure.code, "scenario": entry["scenario"]},
                )
        # E11 tie-in: the inspector over the drill's own audit log must show
        # every expected refusal code, with a passing redaction self-check.
        inspector_report = audit_inspector.build_report(audit_path, now=DRILL_CLOCK)
        observed_codes = sorted(
            entry["code"]
            for entry in inspector_report["refusals"]["by_code"]
            if entry["code"] is not None
        )
        expected_codes = sorted({entry["expected_code"] for entry in entries})
        audit_section = {
            "rows_total": inspector_report["log"]["rows_total"],
            "refusal_rows": inspector_report["refusals"]["total"],
            "refusal_codes_observed": observed_codes,
            "expected_codes_present": all(code in observed_codes for code in expected_codes),
            "redaction_self_check": inspector_report["redaction"]["status"],
        }
        refusals_ok = sum(1 for entry in entries if entry["refusal_ok"])
        recoveries_ok = sum(1 for entry in entries if entry["recovered_ok"])
        all_ok = (
            refusals_ok == len(entries)
            and recoveries_ok == len(entries)
            and audit_section["expected_codes_present"]
            and audit_section["redaction_self_check"] == "PASS"
        )
        return {
            "report_type": REPORT_TYPE,
            "schema_version": REPORT_SCHEMA_VERSION,
            "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "mode": "fixture",
            "backend": {
                "name": issuer.backend.name,
                "real_ed25519": issuer.real_ed25519,
                "note": (
                    "ephemeral Ed25519 keys generated for this run only"
                    if issuer.real_ed25519
                    else "TEST-ONLY deterministic HMAC backend (cryptography not installed); "
                    "NOT a signature scheme"
                ),
            },
            "drill_clock": DRILL_CLOCK_TEXT,
            "scenarios": entries,
            "audit": audit_section,
            "summary": {
                "scenarios_total": len(entries),
                "refusals_ok": refusals_ok,
                "recoveries_ok": recoveries_ok,
                "all_ok": all_ok,
            },
            "exit_code": 0 if all_ok else 1,
        }
    finally:
        if own_temp:
            shutil.rmtree(base, ignore_errors=True)


# ---------------------------------------------------------------------------
# Rendering and CLI.


def format_drill_report(report: dict) -> str:
    backend = report["backend"]
    lines = [
        "MCP signed-bundle incident drill (fixture mode)",
        f"backend: {backend['name']} -- {backend['note']}",
        f"drill clock: {report['drill_clock']}",
        "",
    ]
    for entry in report["scenarios"]:
        refusal = "ok" if entry["refusal_ok"] else "FAILED"
        recovery = "ok" if entry["recovered_ok"] else "FAILED"
        lines.append(
            f"[{entry['scenario']}] expected {entry['expected_code']} "
            f"({entry['expected_name']}), observed {entry['observed_code']}: "
            f"refusal {refusal}, recovery {recovery} ({entry['duration_ms']} ms)"
        )
        lines.append(f"  incident: {entry['incident']}")
        for step in entry["recovery_steps"]:
            lines.append(f"  - {step}")
    audit = report["audit"]
    lines.extend(
        [
            "",
            (
                f"audit: {audit['rows_total']} row(s), {audit['refusal_rows']} refusal(s); "
                f"codes {', '.join(str(code) for code in audit['refusal_codes_observed'])}; "
                f"expected codes present: {audit['expected_codes_present']}; "
                f"redaction self-check: {audit['redaction_self_check']}"
            ),
        ]
    )
    summary = report["summary"]
    lines.append(
        f"summary: {summary['scenarios_total']} scenario(s), "
        f"{summary['refusals_ok']} refused correctly, "
        f"{summary['recoveries_ok']} recovered -- "
        + ("ALL OK" if summary["all_ok"] else "DRILL FAILED")
    )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Fixture-mode incident drill for signed MCP profile bundles: inject each "
            "documented incident, assert the fail-closed refusal code, run the "
            "documented recovery, and prove verification works again. Offline; "
            "everything stays inside a private temp directory."
        )
    )
    parser.add_argument("--json", action="store_true", help="Print the JSON drill report.")
    parser.add_argument(
        "--out",
        default="",
        help="Directory to write incident-drill-report.json and .txt into.",
    )
    parser.add_argument(
        "--scenario",
        default="all",
        help="One scenario name, or 'all' (default). Known: " + ", ".join(SCENARIOS) + ".",
    )
    args = parser.parse_args(argv)
    names = list(SCENARIOS) if args.scenario == "all" else [args.scenario]
    try:
        report = run_drill(names)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    serialized = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True)
    if args.out:
        out_dir = Path(args.out)
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "incident-drill-report.json").write_text(serialized + "\n", encoding="utf-8")
        (out_dir / "incident-drill-report.txt").write_text(
            format_drill_report(report) + "\n", encoding="utf-8"
        )
    print(serialized if args.json else format_drill_report(report))
    return int(report["exit_code"])


if __name__ == "__main__":
    raise SystemExit(main())
