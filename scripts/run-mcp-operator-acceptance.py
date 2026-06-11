"""E21: MCP profile stack end-to-end operator acceptance suite (fixture mode).

ONE operational workflow, executed with the REAL modules end-to-end (no
mocks, no reimplementations) inside a private temp directory:

     1. keygen           E19 ``generate_keypair`` (DEV Ed25519 keypair)
     2. trust_import     E15 ``import_key`` (the PUBLIC half only)
     3. publish          E19 ``publish_bundle`` ceremony (incl. self-verify)
     4. verify           E19 ``verify_report`` over the REAL E14 path
     5. library_add      E20 ``add_bundle`` (verify-before-store)
     6. rollout_plan     E16 ``plan_rollout`` dry-run over fixture tools
     7. replay_audit     E17 ``replay_audit`` over a synthetic history log
     8. activate         E20 ``activate_bundle`` (re-verify + pointer copy)
     9. gateway_resolve  the REAL gateway startup resolution
                         (``commands.mcp._resolve_gateway_profile_state``)
                         under ``--require-signed-profiles``
    10. incident_drill   E15 ``revoke`` -> activation re-verify refuses with
                         ``-32017 bundle_revoked``; the stale active pointer
                         fails closed at the next gateway start
    11. rollback         E20 ``rollback_bundle`` walks back to the prior
                         good bundle; the gateway resolves it again
    12. audit_report     E11 ``audit_inspector.build_report`` over the run's
                         own redacted audit log (refusals visible, redaction
                         self-check PASS)

Exit code 0 only when every selected step passes. ``--step NAME`` runs the
workflow up to and including NAME (earlier steps are prerequisites of the
one shared flow and stay in the report). The ``--json`` report validates
against ``schemas/mcp-operator-acceptance-report.schema.json`` and carries
key facts only: names, SHA-256 PREFIXES, counts, refusal codes, statuses --
never key material, full hashes, or local paths (basenames at most).

Hard safety, by construction: fixture mode only. Ephemeral DEV keys are
generated per run inside the temp directory and never leave it; there are
no production keys, no hosted calls, no registry sync, no OAuth, no MCP
resources or prompts, no network, no telemetry. The real library root,
managed trust store, and default audit log are never touched. Requires the
optional ``cryptography`` package (the E19 publisher has no fallback
signature scheme -- without it the suite refuses to run, exit 2).
"""

from __future__ import annotations

import argparse
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
    cryptography_available,
    generate_keypair,
    publish_bundle,
    verify_report,
)
from unlimited_skills.mcp.bundles import BUNDLE_REVOKED  # noqa: E402
from unlimited_skills.mcp.profile_rollout import plan_rollout  # noqa: E402
from unlimited_skills.mcp.profiles import ActiveProfile, FailClosedProfile  # noqa: E402
from unlimited_skills.mcp.trust_store import (  # noqa: E402
    TrustStore,
    TrustStoreError,
    import_key,
    load_key_file,
    revoke,
)

REPORT_TYPE = "mcp-operator-acceptance-report"
REPORT_SCHEMA_VERSION = 1

KEY_ID = "acceptance-issuer-2026"
AUDIENCE = "team:acceptance"
SHA_PREFIX = 12
MAX_ERROR_CHARS = 512

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
    """One acceptance step's assertion failed (the workflow stops)."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise StepError(message)


def _prefix(sha256: str) -> str:
    return sha256[:SHA_PREFIX]


class AcceptanceContext:
    """Shared state of the one operator workflow (plain attributes)."""

    def __init__(self, base: Path, now: float) -> None:
        self.base = base
        self.now = now
        self.store = TrustStore(base / "trust-store")
        self.library = BundleLibrary(base / "bundle-library")
        self.profiles_path = base / "team-profiles.json"
        self.tools_fixture_path = base / "tools-fixture.json"
        self.incoming = base / "incoming"
        self.audit = AuditLog(base / "audit" / "mcp-audit.jsonl")
        self.history_audit_path = base / "history" / "mcp-audit.jsonl"
        self.keygen: dict = {}
        self.bundle_paths: dict[str, Path] = {}
        self.bundle_shas: dict[str, str] = {}

    def verify_kwargs(self) -> dict:
        return {
            "trusted_keys_path": self.store.trusted_keys_path,
            "audience_ids": [AUDIENCE],
            "now": self.now,
        }

    def gateway_args(self) -> SimpleNamespace:
        """The gateway startup flags, exactly as ``mcp gateway`` parses them:
        the active pointer file + the managed trusted keys, audience-bound,
        under the signed-required policy."""
        return SimpleNamespace(
            profiles="",
            profile="",
            profile_bundle=str(self.library.active_bundle_path),
            trusted_keys=str(self.store.trusted_keys_path),
            audience_id=[AUDIENCE],
            require_signed_profiles=True,
            root="",
        )


# ---------------------------------------------------------------------------
# The 12 steps. Each runs REAL machinery, asserts the operator-visible
# outcome, and returns key facts (prefixes/counts/codes -- never key
# material, full hashes, or local paths).


def step_keygen(ctx: AcceptanceContext) -> dict:
    result = generate_keypair(
        ctx.base / "keys",
        key_id=KEY_ID,
        display="Acceptance issuer (DEV)",
        now=ctx.now,
    )
    ctx.keygen = result
    _require(result["generated"] is True, "keygen did not generate a keypair")
    _require(result["dev_only"] is True, "keygen must be DEV-only")
    _require(Path(result["private_key_path"]).is_file(), "private key file missing")
    _require(Path(result["public_key_path"]).is_file(), "public key file missing")
    return {
        "key_id": result["key_id"],
        "algorithm": result["algorithm"],
        "fingerprint": result["fingerprint"],
        "dev_only": True,
        "private_key_file": Path(result["private_key_path"]).name,
        "public_key_file": Path(result["public_key_path"]).name,
    }


def step_trust_import(ctx: AcceptanceContext) -> dict:
    public_doc = load_key_file(Path(ctx.keygen["public_key_path"]))
    result = import_key(
        ctx.store,
        key_id=KEY_ID,
        public_key_b64=str(public_doc["public_key"]),
        display="Acceptance issuer (DEV)",
        now=ctx.now,
    )
    _require(result["imported"] is True, "trust import did not import the key")
    _require(
        result["fingerprint"] == ctx.keygen["fingerprint"],
        "imported fingerprint does not match the generated keypair",
    )
    # An empty managed CRL: the published bundles declare it, so a later
    # `trust revoke` takes effect through the real revocation check.
    ctx.store.crl_path.parent.mkdir(parents=True, exist_ok=True)
    ctx.store.crl_path.write_text(json.dumps(EMPTY_CRL), encoding="utf-8")
    return {
        "key_id": result["key_id"],
        "fingerprint": result["fingerprint"],
        "public_keys_only": True,
        "trusted_keys_file": ctx.store.trusted_keys_path.name,
        "crl_file": ctx.store.crl_path.name,
    }


def step_publish(ctx: AcceptanceContext) -> dict:
    ctx.profiles_path.write_text(json.dumps(PROFILE_DOC), encoding="utf-8")
    results = {}
    for offset, name, previous in (
        (0.0, "team-v1", ""),
        (10.0, "team-v2", "previous"),
    ):
        result = publish_bundle(
            ctx.profiles_path,
            Path(ctx.keygen["private_key_path"]),
            audience=[AUDIENCE],
            expires_days=30,
            out_dir=ctx.incoming,
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
        ctx.bundle_paths[name] = ctx.incoming / f"{name}.bundle.json"
        ctx.bundle_shas[name] = result["bundle_sha256"]
        results[name] = result
    _require(
        ctx.bundle_shas["team-v1"] != ctx.bundle_shas["team-v2"],
        "the two published bundles must have distinct SHA-256s",
    )
    _require(
        results["team-v2"]["previous_bundle_sha256"] == ctx.bundle_shas["team-v1"],
        "team-v2 must record team-v1 as its rollback predecessor",
    )
    return {
        "bundles": ["team-v1", "team-v2"],
        "v1_sha_prefix": _prefix(ctx.bundle_shas["team-v1"]),
        "v2_sha_prefix": _prefix(ctx.bundle_shas["team-v2"]),
        "issuer_key_id": results["team-v1"]["issuer_key_id"],
        "audience": list(results["team-v1"]["audience"]),
        "profile_count": results["team-v1"]["profile_count"],
        "self_check": results["team-v1"]["verification"]["verified_via"],
        "ceremony_checks_passed": len(results["team-v1"]["checks"]),
    }


def step_verify(ctx: AcceptanceContext) -> dict:
    report = verify_report(
        ctx.bundle_paths["team-v1"],
        ctx.store.trusted_keys_path,
        audience_ids=[AUDIENCE],
        now=ctx.now,
    )
    _require(report["ok"] is True, f"standalone verify refused: {report['refusal']}")
    _require(report["profile"] == "dev", "verify must select the bundle's default profile")
    _require(report["issuer_key_id"] == KEY_ID, "verify reported an unexpected issuer")
    return {
        "ok": True,
        "profile": report["profile"],
        "issuer_key_id": report["issuer_key_id"],
        "audience": list(report["audience"]),
        "verified_via": report["verified_via"],
    }


def step_library_add(ctx: AcceptanceContext) -> dict:
    added = []
    for name in ("team-v1", "team-v2"):
        result = add_bundle(ctx.library, ctx.bundle_paths[name], **ctx.verify_kwargs())
        _require(result["added"] is True, f"{name}: library add refused")
        _require(
            result["verification"] == "verified",
            f"{name}: add must verify BEFORE storing",
        )
        _require(result["sha256"] == ctx.bundle_shas[name], f"{name}: stored sha mismatch")
        added.append({"name": result["name"], "sha_prefix": _prefix(result["sha256"])})
    return {
        "added": len(added),
        "entries": added,
        "verified_before_store": True,
        "content_addressed": True,
    }


def step_rollout_plan(ctx: AcceptanceContext) -> dict:
    ctx.tools_fixture_path.write_text(json.dumps(TOOLS_FIXTURE), encoding="utf-8")
    plan = plan_rollout(
        root=ctx.base,
        bundle_path=str(ctx.bundle_paths["team-v2"]),
        trusted_keys_path=str(ctx.store.trusted_keys_path),
        audience_ids=[AUDIENCE],
        tools_fixture_path=str(ctx.tools_fixture_path),
        now=ctx.now,
        env_name="",
    )
    tools = plan["tools"]
    _require(plan["blockers"] == [], f"rollout plan has blockers: {plan['blockers'][:2]}")
    _require(
        plan["profile_state"]["mode"] == "enforced",
        f"rollout plan mode is {plan['profile_state']['mode']!r}, expected 'enforced'",
    )
    _require(plan["verification"]["ok"] is True, "rollout plan verification failed")
    _require(tools["total"] == len(TOOLS_FIXTURE), "rollout plan lost fixture tools")
    _require(
        tools["visible"] == 2 and tools["callable"] == 2 and tools["hidden"] == 1,
        f"rollout plan counts are not sensible: visible {tools['visible']}, "
        f"callable {tools['callable']}, hidden {tools['hidden']}",
    )
    return {
        "mode": plan["profile_state"]["mode"],
        "profile": plan["profile_state"]["profile"],
        "tools_total": tools["total"],
        "visible": tools["visible"],
        "callable": tools["callable"],
        "hidden": tools["hidden"],
        "refused_by_policy": tools["refused_by_policy"],
        "blockers": 0,
        "dry_run": True,
    }


def step_replay_audit(ctx: AcceptanceContext) -> dict:
    # A synthetic HISTORICAL audit log (separate from the run's own log):
    # real gateway traffic shapes written through the REAL redacted writer.
    history = AuditLog(ctx.history_audit_path)
    history.record(tool="profile_loaded", ok=True, profile="dev")
    for _ in range(4):
        history.record(
            tool="tools_call",
            upstream="fake",
            duration_ms=12.5,
            ok=True,
            arguments={"tool": "fake.echo"},
            profile="dev",
        )
    history.record(
        tool="tools_schema",
        upstream="fake",
        duration_ms=3.0,
        ok=True,
        arguments={"tool": "fake.add"},
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
    report = replay_audit(
        ctx.history_audit_path,
        root=ctx.base,
        bundle_path=str(ctx.bundle_paths["team-v2"]),
        trusted_keys_path=str(ctx.store.trusted_keys_path),
        audience_ids=[AUDIENCE],
        now=ctx.now,
        env_name="",
    )
    recommendation = report.get("recommendation")
    _require(
        isinstance(recommendation, dict) and "status" in recommendation,
        "replay report carries no recommendation field",
    )
    _require(
        recommendation["status"] in ("safe", "safe_with_warnings"),
        f"replay recommendation is {recommendation['status']!r} (the rollout is blocked)",
    )
    impact = report["impact"]
    _require(impact["replayed"] == 6, f"expected 6 replayed calls, got {impact['replayed']}")
    _require(
        impact["newly_denied"] == 1,
        "exactly the legacy.export call must become newly denied",
    )
    return {
        "recommendation": recommendation["status"],
        "recommendation_present": True,
        "replayed": impact["replayed"],
        "newly_denied": impact["newly_denied"],
        "would_allow": impact["would_allow"],
        "history_rows": report["log"]["rows_total"],
    }


def step_activate(ctx: AcceptanceContext) -> dict:
    # v1 first (the earlier known-good rollout), then v2 (the current one):
    # the append-only history this builds is what powers step 11's rollback.
    first = activate_bundle(ctx.library, "team-v1", **ctx.verify_kwargs())
    _require(first["activated"] is True, "activating team-v1 failed")
    second = activate_bundle(ctx.library, "team-v2", **ctx.verify_kwargs())
    _require(second["activated"] is True, "activating team-v2 failed")
    _require(
        second["previous_active_sha256"] == ctx.bundle_shas["team-v1"],
        "team-v1 must be recorded as the previously active bundle",
    )
    _require(ctx.library.active_bundle_path.is_file(), "active pointer file missing")
    state, _ = read_state(ctx.library)
    actions = [record["action"] for record in state["history"]]
    _require(actions == ["activate", "activate"], f"unexpected history actions: {actions}")
    return {
        "active": second["name"],
        "active_sha_prefix": _prefix(second["sha256"]),
        "previous_sha_prefix": _prefix(second["previous_active_sha256"]),
        "pointer_file": ACTIVE_BUNDLE_FILENAME,
        "history_actions": actions,
        "reverified_at_activation": True,
    }


def step_gateway_resolve(ctx: AcceptanceContext) -> dict:
    state, note = _resolve_gateway_profile_state(ctx.gateway_args())
    _require(
        isinstance(state, ActiveProfile),
        f"gateway resolution did not produce an ActiveProfile: {note}",
    )
    _require(state.name == "dev", f"gateway resolved profile {state.name!r}, expected 'dev'")
    _require(state.is_callable("fake", "echo"), "fake.echo must be callable")
    _require(not state.is_visible("legacy", "export"), "legacy.export must stay hidden")
    provenance = state.provenance
    _require(
        provenance is not None and provenance.bundle_sha256 == ctx.bundle_shas["team-v2"],
        "the gateway must resolve the ACTIVE bundle (team-v2)",
    )
    ctx.audit.record(tool="tools_search", upstream="", ok=True, profile=state.name)
    return {
        "profile": state.name,
        "require_signed_profiles": True,
        "note": note,
        "bundle_sha_prefix": _prefix(provenance.bundle_sha256),
        "issuer_key_id": provenance.issuer_key_id,
        "fake_echo_callable": True,
        "legacy_export_hidden": True,
    }


def step_incident_drill(ctx: AcceptanceContext) -> dict:
    # Incident: the ACTIVE bundle (team-v2) is withdrawn through the managed
    # trust store's append-only local CRL.
    revoked = revoke(
        ctx.store,
        bundle_sha256=ctx.bundle_shas["team-v2"],
        reason="acceptance drill: active bundle withdrawn",
        now=ctx.now,
    )
    _require(revoked["revoked"] is True, "trust revoke did not record the revocation")
    # The library's activation re-verify refuses the revoked bundle.
    refusal_code = 0
    refusal_message = ""
    try:
        activate_bundle(ctx.library, "team-v2", **ctx.verify_kwargs())
    except BundleLibraryError as exc:
        refusal_code = exc.code
        refusal_message = str(exc)
    _require(
        refusal_code == BUNDLE_REVOKED,
        f"activation re-verify must refuse with {BUNDLE_REVOKED} bundle_revoked "
        f"(got {refusal_code})",
    )
    # The stale active pointer fails closed at the next gateway start: the
    # gateway re-runs the FULL E14 verification itself.
    state, _ = _resolve_gateway_profile_state(ctx.gateway_args())
    _require(
        isinstance(state, FailClosedProfile) and state.code == BUNDLE_REVOKED,
        "the stale active pointer must fail closed with bundle_revoked",
    )
    # The refusal lands in the run's own audit log through the REAL writer.
    ctx.audit.record(
        tool="tools_call",
        upstream="fake",
        ok=False,
        error=refusal_message or state.message,
        profile="",
        extra={"code": BUNDLE_REVOKED},
    )
    return {
        "revoked_sha_prefix": _prefix(ctx.bundle_shas["team-v2"]),
        "refusal_code": BUNDLE_REVOKED,
        "refusal_name": "bundle_revoked",
        "activation_refused": True,
        "gateway_fail_closed": True,
        "crl_append_only": True,
    }


def step_rollback(ctx: AcceptanceContext) -> dict:
    rolled = rollback_bundle(ctx.library, **ctx.verify_kwargs())
    _require(rolled["rolled_back"] is True, "rollback did not re-activate a bundle")
    _require(
        rolled["sha256"] == ctx.bundle_shas["team-v1"],
        "rollback must walk back to the prior good bundle (team-v1)",
    )
    _require(rolled["action"] == "rollback", "the history must record a rollback action")
    _require(rolled["skipped"] == [], f"unexpected skipped candidates: {rolled['skipped']}")
    # The gateway resolves the restored pointer again -- the workflow is
    # operational once more, still under the signed-required policy.
    state, note = _resolve_gateway_profile_state(ctx.gateway_args())
    _require(
        isinstance(state, ActiveProfile) and state.name == "dev",
        f"gateway re-resolution after rollback failed: {note}",
    )
    provenance = state.provenance
    _require(
        provenance is not None and provenance.bundle_sha256 == ctx.bundle_shas["team-v1"],
        "the gateway must resolve the rolled-back bundle (team-v1)",
    )
    ctx.audit.record(tool="tools_search", upstream="", ok=True, profile=state.name)
    return {
        "rolled_back_to": rolled["name"],
        "rolled_back_sha_prefix": _prefix(rolled["sha256"]),
        "skipped_candidates": 0,
        "re_resolve_ok": True,
        "active_profile": state.name,
        "reverified_at_rollback": True,
    }


def step_audit_report(ctx: AcceptanceContext) -> dict:
    report = audit_inspector.build_report(ctx.audit.path, now=ctx.now)
    refusals = report["refusals"]
    observed = sorted(
        entry["code"] for entry in refusals["by_code"] if entry["code"] is not None
    )
    _require(refusals["total"] >= 1, "the run's audit log shows no refusal rows")
    _require(
        BUNDLE_REVOKED in observed,
        f"the incident's {BUNDLE_REVOKED} refusal is not visible to the inspector",
    )
    _require(
        report["redaction"]["status"] == "PASS",
        "the audit redaction self-check did not pass",
    )
    return {
        "rows_total": report["log"]["rows_total"],
        "refusal_rows": refusals["total"],
        "refusal_codes_observed": observed,
        "redaction_self_check": report["redaction"]["status"],
        "strings_scanned": report["redaction"]["strings_scanned"],
    }


STEPS: tuple[tuple[str, object], ...] = (
    ("keygen", step_keygen),
    ("trust_import", step_trust_import),
    ("publish", step_publish),
    ("verify", step_verify),
    ("library_add", step_library_add),
    ("rollout_plan", step_rollout_plan),
    ("replay_audit", step_replay_audit),
    ("activate", step_activate),
    ("gateway_resolve", step_gateway_resolve),
    ("incident_drill", step_incident_drill),
    ("rollback", step_rollback),
    ("audit_report", step_audit_report),
)
STEP_NAMES = tuple(name for name, _ in STEPS)


# ---------------------------------------------------------------------------
# Runner.


def run_acceptance(
    until: str = "all",
    base_dir: Path | None = None,
    before_step=None,
) -> dict:
    """Run the workflow up to and including step ``until`` ('all' = step 12).

    ``base_dir=None`` creates (and afterwards removes) a fresh temp
    directory; an explicit directory keeps every write inside it. The real
    library root, managed trust store, and default audit log are never
    touched. ``before_step(name, ctx)`` is a test-only injection hook called
    before each step. The workflow stops at the first failing step.
    """
    if not cryptography_available():
        raise RuntimeError(
            "the operator acceptance suite needs the optional 'cryptography' "
            "package for real Ed25519 (pip install cryptography); the E19 "
            "publisher has no fallback signature scheme"
        )
    if until != "all" and until not in STEP_NAMES:
        raise ValueError(f"unknown step {until!r}; known: {', '.join(STEP_NAMES)}")
    selected = STEPS if until == "all" else STEPS[: STEP_NAMES.index(until) + 1]

    own_temp = base_dir is None
    base = (
        Path(tempfile.mkdtemp(prefix="uls-mcp-operator-acceptance-"))
        if own_temp
        else Path(base_dir)
    )
    base.mkdir(parents=True, exist_ok=True)
    saved_env = {name: os.environ.pop(name, None) for name in _NEUTRALIZED_ENV}
    try:
        ctx = AcceptanceContext(base, time.time())
        entries: list[dict] = []
        for index, (name, fn) in enumerate(selected, start=1):
            if before_step is not None:
                before_step(name, ctx)
            started = time.perf_counter()
            try:
                facts = fn(ctx)
                ok = True
            except (
                StepError,
                BundleLibraryError,
                PublisherError,
                TrustStoreError,
                FileNotFoundError,
                OSError,
                ValueError,
            ) as exc:
                ok = False
                facts = {"error": scrub_paths(str(exc))[:MAX_ERROR_CHARS]}
            entries.append(
                {
                    "step": index,
                    "name": name,
                    "ok": ok,
                    "facts": facts,
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
            "steps": entries,
            "summary": {
                "steps_total": len(STEPS),
                "steps_selected": len(selected),
                "steps_ok": steps_ok,
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
        return "{" + ", ".join(f"{key}={_fact_text(val)}" for key, val in value.items()) + "}"
    return str(value)


def format_acceptance_report(report: dict) -> str:
    lines = [
        "MCP profile stack operator acceptance (fixture mode)",
        "publish -> import key -> verify -> add -> rollout-plan -> replay-audit "
        "-> activate -> gateway resolve -> incident drill -> rollback -> audit/report",
        "",
    ]
    for entry in report["steps"]:
        mark = "ok" if entry["ok"] else "FAILED"
        lines.append(
            f"[{entry['step']:>2}/12] {entry['name']}: {mark} ({entry['duration_ms']} ms)"
        )
        for key in sorted(entry["facts"]):
            lines.append(f"    {key} = {_fact_text(entry['facts'][key])}")
    summary = report["summary"]
    lines.append("")
    lines.append(
        f"summary: {summary['steps_ok']} of {summary['steps_selected']} selected "
        f"step(s) ok (workflow has {summary['steps_total']}) -- "
        + ("ALL OK" if summary["all_ok"] else "ACCEPTANCE FAILED")
    )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Fixture-mode operator acceptance suite for the whole MCP profile "
            "stack: one 12-step workflow (publish -> import key -> verify -> add "
            "-> rollout-plan -> replay-audit -> activate -> gateway resolve -> "
            "incident drill -> rollback -> audit/report) over the REAL modules, "
            "ephemeral DEV keys, everything inside a private temp directory. "
            "Offline: no production keys, no hosted calls, no registry sync, no "
            "OAuth, no resources or prompts."
        )
    )
    parser.add_argument("--json", action="store_true", help="Print the JSON acceptance report.")
    parser.add_argument(
        "--out",
        default="",
        help="Directory to write operator-acceptance-report.json and .txt into.",
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
        report = run_acceptance(until=args.step)
    except (ValueError, RuntimeError) as exc:
        print(str(exc), file=sys.stderr)
        return 2
    serialized = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True)
    if args.out:
        out_dir = Path(args.out)
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "operator-acceptance-report.json").write_text(
            serialized + "\n", encoding="utf-8"
        )
        (out_dir / "operator-acceptance-report.txt").write_text(
            format_acceptance_report(report) + "\n", encoding="utf-8"
        )
    print(serialized if args.json else format_acceptance_report(report))
    return int(report["exit_code"])


if __name__ == "__main__":
    raise SystemExit(main())
