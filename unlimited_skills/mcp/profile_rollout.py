"""MCP profile bundle rollout simulator and policy doctor (E16).

A local DRY-RUN over the artifacts the gateway would load at startup -- the
raw E09/E10 profile file, the E13/E14 signed bundle, the E14/E15 trust
artifacts (explicit ``--trusted-keys`` or the managed store default), and
the gateway upstream config -- answering "what WOULD happen if I started
the gateway with these flags?" before anything is applied:

- ``rollout-plan`` builds a plan: visible/hidden/callable tool counts and
  lists, which upstreams would never spawn, the profile inheritance chain
  and its narrowing, what E14 verification WOULD say (the REAL
  :func:`unlimited_skills.mcp.bundles.resolve_bundle_state` runs in
  dry-run -- never a reimplementation), and what the ``profile_loaded``
  audit row would record.
- ``doctor`` turns the same dry-run into distinct findings (severity
  ``problem`` exits 1, ``warning`` exits 0), reusing the E15 trust-store
  doctor and the E14/E10 loaders rather than duplicating their logic.

Everything here is READ-ONLY and OFFLINE by construction: no upstream is
ever spawned (no subprocess use at all), no audit row is written, no
runtime state changes, no network, no telemetry, and no private key
material is read or printed. The tool list comes from the gateway config's
pre-declared ``tools`` entries by default, or from an explicit
``--tools-fixture`` file (a JSON list of ``{upstream, name, description}``
objects) for what-if planning.

The profile-state dispatch below deliberately MIRRORS
``unlimited_skills.commands.mcp._resolve_gateway_profile_state`` (bundle >
raw file > none, the signed-required policy, the E15 managed-store
default) on top of the same primitives, adding only the ``now``/``backend``
injection points a simulator needs; a drift between the two is a bug.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Sequence

from .bundles import (
    BUNDLE_AUDIENCE_MISMATCH,
    BUNDLE_EXPIRED,
    BUNDLE_KEY_MISSING,
    BUNDLE_REVOKED,
    BUNDLE_SIGNATURE_INVALID,
    CLOCK_SKEW_SECONDS,
    BundleFailClosed,
    BundleProvenance,
    _DEFAULT_BACKEND,
    _parse_timestamp,
    local_audience_ids,
    require_signed_refusal,
    resolve_bundle_state,
)
from .gateway import (
    AUDIT_LEVELS,
    DEFAULT_TRUST_LEVEL,
    GatewayConfigError,
    TRUST_DISABLED,
    TRUST_LOCAL_RESTRICTED,
    TRUST_LOCAL_TRUSTED,
    load_gateway_config,
)
from .profiles import (
    MAX_EXTENDS_DEPTH,
    PROFILE_INVALID,
    PROFILE_NOT_FOUND,
    TOOL_NOT_CALLABLE,
    TOOL_NOT_VISIBLE,
    ActiveProfile,
    FailClosedProfile,
    ProfileState,
    _compile_rules,
    _rule_covered,
    resolve_profile_state,
)
from .trust_store import (
    TIMESTAMP_RE,
    TrustStore,
    _read_crl_raw,
    _read_trusted_keys_raw,
    default_store_dir,
    doctor_report as trust_store_doctor_report,
    managed_trusted_keys_path,
)

PLAN_SCHEMA_VERSION = 1

REFUSAL_NAMES = {
    TOOL_NOT_VISIBLE: "tool_not_visible",
    TOOL_NOT_CALLABLE: "tool_not_callable",
    PROFILE_NOT_FOUND: "profile_not_found",
    PROFILE_INVALID: "profile_invalid",
    BUNDLE_SIGNATURE_INVALID: "bundle_signature_invalid",
    BUNDLE_EXPIRED: "bundle_expired",
    BUNDLE_REVOKED: "bundle_revoked",
    BUNDLE_AUDIENCE_MISMATCH: "bundle_audience_mismatch",
    BUNDLE_KEY_MISSING: "bundle_key_missing",
}

# Verification step labels for the plan's trust summary, derived from the
# refusal code (plus the namespace-ceiling message disambiguation -- E14
# reuses -32018 for both audience and ceiling failures).
_FAILED_STEPS = {
    PROFILE_INVALID: "shape_or_static_checks",
    PROFILE_NOT_FOUND: "selection",
    BUNDLE_SIGNATURE_INVALID: "signature",
    BUNDLE_EXPIRED: "validity_window",
    BUNDLE_REVOKED: "revocation",
    BUNDLE_AUDIENCE_MISMATCH: "audience",
    BUNDLE_KEY_MISSING: "key_lookup",
}

_NAMESPACE_MARKER = "allowed_upstream_namespaces"
_MAX_FINDING_DETAILS = 5  # cap repeated per-item findings of one class

SEVERITY_PROBLEM = "problem"
SEVERITY_WARNING = "warning"


def refusal_name(code: int) -> str:
    return REFUSAL_NAMES.get(code, "unknown")


# ---------------------------------------------------------------------------
# Tolerant reads (a simulator must DESCRIBE broken inputs, not crash).


def _read_json_tolerant(path: Path) -> tuple[dict | None, str]:
    try:
        raw = Path(path).read_bytes()
    except OSError:
        return None, f"{Path(path).name} is missing or unreadable"
    try:
        document = json.loads(raw.decode("utf-8-sig", errors="replace"))
    except json.JSONDecodeError:
        return None, f"{Path(path).name} is not valid JSON"
    if not isinstance(document, dict):
        return None, f"{Path(path).name} must be a JSON object"
    return document, ""


def read_tools_fixture(path: Path) -> tuple[list[dict], list[str]]:
    """Read a what-if tool fixture: a JSON list of {upstream, name, description}."""
    try:
        raw = Path(path).read_text(encoding="utf-8-sig", errors="replace")
    except OSError:
        return [], [f"tools fixture {Path(path).name} is missing or unreadable"]
    try:
        document = json.loads(raw)
    except json.JSONDecodeError:
        return [], [f"tools fixture {Path(path).name} is not valid JSON"]
    if not isinstance(document, list):
        return [], ["tools fixture must be a JSON list of {upstream, name, description} objects"]
    tools: list[dict] = []
    errors: list[str] = []
    for index, entry in enumerate(document):
        if (
            not isinstance(entry, dict)
            or not isinstance(entry.get("upstream"), str)
            or not entry["upstream"]
            or not isinstance(entry.get("name"), str)
            or not entry["name"]
        ):
            errors.append(
                f"tools fixture entry [{index}] needs string 'upstream' and 'name' fields"
            )
            continue
        tools.append(
            {
                "upstream": entry["upstream"],
                "name": entry["name"],
                "description": str(entry.get("description") or ""),
            }
        )
    return tools, errors


# ---------------------------------------------------------------------------
# Context: everything both the plan and the doctor need, prepared once.


class _RolloutContext:
    """All resolved inputs of one dry-run (plain attributes, no behavior)."""

    def __init__(self) -> None:
        self.inputs: dict = {}
        self.config: dict | None = None
        self.tools: list[dict] = []
        self.tools_source = "none"
        self.state: ProfileState = None
        self.source = "none"
        self.warnings: list[str] = []
        self.blockers: list[str] = []
        self.bundle_document: dict | None = None
        self.profiles_document: dict | None = None
        self.trusted_keys_path = ""
        self.trusted_keys_source = "none"
        self.store_dir = ""
        self.local_ids: list[str] = []
        self.now = 0.0
        self.bundle_path = ""
        self.profiles_path = ""
        self.require_signed = False
        self.audience_ids: list[str] = []
        self.profile_name = ""


def _effective_trust_level(spec: dict) -> str:
    """The gateway's UpstreamClient semantics: enabled:false forces disabled."""
    if spec.get("enabled", True) is False:
        return TRUST_DISABLED
    return str(spec.get("trust_level") or DEFAULT_TRUST_LEVEL)


def _prepare(
    root: Path | None,
    config_path: str,
    profiles_path: str,
    bundle_path: str,
    trusted_keys_path: str,
    audience_ids: Sequence[str],
    profile_name: str,
    tools_fixture_path: str,
    require_signed: bool,
    now: float | None,
    backend: object,
    env_name: str | None,
) -> _RolloutContext:
    import time as _time

    ctx = _RolloutContext()
    ctx.now = _time.time() if now is None else float(now)
    ctx.bundle_path = bundle_path
    ctx.profiles_path = profiles_path
    ctx.require_signed = bool(require_signed)
    ctx.audience_ids = [item for item in (audience_ids or []) if item]
    ctx.profile_name = profile_name or ""

    # Gateway upstream config (the real strict loader -- a config the
    # gateway would refuse to start with is a blocker here too).
    if config_path:
        try:
            ctx.config = load_gateway_config(Path(config_path).expanduser())
        except GatewayConfigError as exc:
            ctx.blockers.append(f"gateway config: {exc}")

    # Tool list: explicit fixture for what-if planning, else the config's
    # pre-declared tools entries of spawnable upstreams (matching what the
    # gateway's index can ever contain without spawning anything).
    if tools_fixture_path:
        ctx.tools_source = "fixture"
        ctx.tools, fixture_errors = read_tools_fixture(Path(tools_fixture_path).expanduser())
        ctx.blockers.extend(fixture_errors)
        if ctx.config is not None:
            configured = {str(spec.get("name")) for spec in ctx.config.get("upstreams", [])}
            for upstream in sorted({tool["upstream"] for tool in ctx.tools} - configured):
                ctx.warnings.append(
                    f"tools fixture names upstream '{upstream}' that is not in the "
                    "gateway config; the gateway would refuse it as unknown"
                )
    elif ctx.config is not None:
        ctx.tools_source = "config"
        for spec in ctx.config.get("upstreams", []):
            trust = _effective_trust_level(spec)
            declared = [tool for tool in spec.get("tools") or [] if isinstance(tool, dict)]
            if trust not in (TRUST_LOCAL_RESTRICTED, TRUST_LOCAL_TRUSTED):
                if declared:
                    ctx.warnings.append(
                        f"upstream '{spec.get('name')}' pre-declares {len(declared)} tool(s) "
                        f"but its trust level '{trust}' means it is never spawned and "
                        "never indexed; those tools are excluded from the plan"
                    )
                continue
            for tool in declared:
                ctx.tools.append(
                    {
                        "upstream": str(spec.get("name")),
                        "name": str(tool.get("name")),
                        "description": str(tool.get("description") or ""),
                    }
                )
    else:
        ctx.warnings.append(
            "no tool list: pass --config (pre-declared tools entries) or "
            "--tools-fixture; tool counts below are over an empty set"
        )

    # Trusted-keys resolution: explicit flag > E15 managed store default
    # (only consulted when a bundle is configured, exactly like the gateway).
    if root is not None:
        ctx.store_dir = str(default_store_dir(Path(root)))
    if trusted_keys_path:
        ctx.trusted_keys_path = str(Path(trusted_keys_path).expanduser())
        ctx.trusted_keys_source = "explicit"
    elif bundle_path and root is not None:
        managed = managed_trusted_keys_path(Path(root))
        if managed.is_file():
            ctx.trusted_keys_path = str(managed)
            ctx.trusted_keys_source = "managed"

    # Flag-combination rules the gateway enforces at startup (parity with
    # commands.mcp._resolve_gateway_profile_state): violating them means the
    # gateway would refuse to START, so they are blockers, not warnings.
    if not bundle_path and trusted_keys_path:
        ctx.blockers.append(
            "--trusted-keys requires --bundle (the signed bundle path); "
            "the gateway would refuse to start"
        )
    if not bundle_path and ctx.audience_ids:
        ctx.blockers.append(
            "--audience-id requires --bundle (the signed bundle path); "
            "the gateway would refuse to start"
        )
    if profile_name and not bundle_path and not profiles_path and not require_signed:
        ctx.blockers.append(
            "--profile requires --profiles or --bundle (a profile source); "
            "the gateway would refuse to start"
        )

    # Profile-state dispatch, mirroring the gateway (see module docstring).
    # The REAL E14 verification and E10 loading run here, in dry-run.
    if bundle_path:
        ctx.state = resolve_bundle_state(
            Path(bundle_path).expanduser(),
            trusted_keys_path=Path(ctx.trusted_keys_path) if ctx.trusted_keys_path else None,
            cli_name=profile_name,
            env_name=env_name,
            audience_ids=ctx.audience_ids or None,
            local_profiles_path=Path(profiles_path).expanduser() if profiles_path else None,
            now=ctx.now,
            backend=backend,
        )
        if profiles_path and isinstance(ctx.state, ActiveProfile):
            ctx.source = "signed_bundle_narrowed"
        else:
            ctx.source = "signed_bundle"
    elif profiles_path:
        if require_signed:
            ctx.state = require_signed_refusal(
                "--require-signed-profiles is set but --profiles names an "
                "unsigned profile file and no --profile-bundle is configured",
                requested=profile_name,
            )
            ctx.source = "policy_refusal"
        else:
            ctx.state = resolve_profile_state(
                Path(profiles_path).expanduser(), cli_name=profile_name, env_name=env_name
            )
            ctx.source = "raw_file"
    elif require_signed:
        ctx.state = require_signed_refusal(
            "--require-signed-profiles is set but no --profile-bundle is configured",
            requested=profile_name,
        )
        ctx.source = "policy_refusal"

    # Tolerant document reads for the inheritance chain and doctor checks
    # (the strict loaders above already decided trust; these never do).
    if bundle_path:
        ctx.bundle_document, _ = _read_json_tolerant(Path(bundle_path).expanduser())
    if profiles_path:
        ctx.profiles_document, _ = _read_json_tolerant(Path(profiles_path).expanduser())

    ctx.local_ids = local_audience_ids(ctx.audience_ids or None)

    ctx.inputs = {
        "config_path": str(config_path or ""),
        "profiles_path": str(profiles_path or ""),
        "bundle_path": str(bundle_path or ""),
        "trusted_keys_path": ctx.trusted_keys_path,
        "trusted_keys_source": ctx.trusted_keys_source,
        "profile": ctx.profile_name,
        "audience_ids": list(ctx.local_ids),
        "tools_source": ctx.tools_source,
        "require_signed_profiles": bool(require_signed),
    }
    return ctx


# ---------------------------------------------------------------------------
# Plan sections (pure functions over the context).


def _mode(ctx: _RolloutContext) -> str:
    if ctx.blockers:
        return "blocked"
    if ctx.state is None:
        return "open"
    if isinstance(ctx.state, ActiveProfile):
        return "enforced"
    return "fail_closed"


def _tool_visibility(ctx: _RolloutContext) -> dict:
    visible: list[str] = []
    hidden: list[str] = []
    callable_tools: list[str] = []
    for tool in ctx.tools:
        fq = f"{tool['upstream']}.{tool['name']}"
        if ctx.state is None:
            visible.append(fq)
            callable_tools.append(fq)
        elif isinstance(ctx.state, ActiveProfile):
            if ctx.state.is_visible(tool["upstream"], tool["name"]):
                visible.append(fq)
                if ctx.state.is_callable(tool["upstream"], tool["name"]):
                    callable_tools.append(fq)
            else:
                hidden.append(fq)
        else:  # fail-closed refuse-all: nothing visible, nothing callable
            hidden.append(fq)
    visible.sort()
    hidden.sort()
    total = len(ctx.tools)
    return {
        "total": total,
        "visible": len(visible),
        "hidden": len(hidden),
        "callable": len(callable_tools),
        "view_only": len(visible) - len(callable_tools),
        # Every call the gateway would refuse on policy grounds: hidden
        # (-32011), view-only (-32012), or everything in a fail-closed state.
        "refused_by_policy": total - len(callable_tools),
        "visible_tools": visible,
        "hidden_tools": hidden,
    }


def _upstream_rows(ctx: _RolloutContext) -> list[dict]:
    rows: list[dict] = []
    profile = ctx.state if isinstance(ctx.state, ActiveProfile) else None
    fail_closed = isinstance(ctx.state, FailClosedProfile)
    by_upstream: dict[str, list[dict]] = {}
    for tool in ctx.tools:
        by_upstream.setdefault(tool["upstream"], []).append(tool)
    configured: list[tuple[str, dict]] = []
    if ctx.config is not None:
        configured = [
            (str(spec.get("name")), spec) for spec in ctx.config.get("upstreams", [])
        ]
    configured_names = {name for name, _ in configured}
    extras = sorted(set(by_upstream) - configured_names)
    for name, spec in configured + [(name, None) for name in extras]:
        if spec is None:
            trust = "unknown"
            spawnable = False
            note = "not in the gateway config (fixture-only what-if upstream)"
        else:
            trust = _effective_trust_level(spec)
            spawnable = trust in (TRUST_LOCAL_RESTRICTED, TRUST_LOCAL_TRUSTED)
            note = "" if spawnable else f"never spawned (trust level '{trust}')"
        tools_here = by_upstream.get(name, [])
        if profile is not None:
            visible_count = sum(
                1 for tool in tools_here if profile.is_visible(name, tool["name"])
            )
            has_visible = profile.upstream_has_visible_tools(name)
        elif fail_closed:
            visible_count = 0
            has_visible = False
        else:
            visible_count = len(tools_here)
            has_visible = True
        loses_all = spawnable and not has_visible and (profile is not None or fail_closed)
        would_spawn = spawnable and has_visible
        if loses_all and not note:
            note = "no tool of this upstream can ever be visible; the gateway would never spawn it"
        rows.append(
            {
                "name": name,
                "trust_level": trust,
                "spawnable": spawnable,
                "configured": spec is not None,
                "declared_tools": len(tools_here),
                "visible_tools": visible_count,
                "would_spawn": would_spawn,
                "loses_all_visibility": loses_all,
                "note": note,
            }
        )
    return rows


def _extends_chain(profiles_map: dict, name: str) -> list[str]:
    """Leaf-to-root chain, cycle/depth guarded (works on tolerant documents)."""
    chain = [name]
    current = profiles_map.get(name)
    while isinstance(current, dict) and "extends" in current:
        parent = current.get("extends")
        if not isinstance(parent, str) or parent in chain or len(chain) > MAX_EXTENDS_DEPTH:
            break
        chain.append(parent)
        current = profiles_map.get(parent)
    return chain


def _inheritance(ctx: _RolloutContext) -> dict:
    empty = {
        "available": False,
        "chain": [],
        "depth": 0,
        "narrowed_by_local_file": False,
        "steps": [],
    }
    if not isinstance(ctx.state, ActiveProfile):
        return empty
    document = ctx.bundle_document if ctx.bundle_path else ctx.profiles_document
    profiles_map = (document or {}).get("profiles")
    if not isinstance(profiles_map, dict) or ctx.state.name not in profiles_map:
        return empty
    chain = _extends_chain(profiles_map, ctx.state.name)
    narrowed = isinstance(ctx.state.provenance, BundleProvenance) and bool(
        ctx.state.provenance.local_profile_sha256
    )
    steps: list[dict] = []
    visible_sets: list = []
    callable_sets: list = []
    # Root to leaf: each step shows the conjunction so far -- visible/callable
    # tool counts can only ever shrink along the chain (restriction-only).
    for name in reversed(chain):
        spec = profiles_map.get(name)
        spec = spec if isinstance(spec, dict) else {}
        declared_visible = spec.get("visible") if isinstance(spec.get("visible"), list) else None
        declared_callable = spec.get("callable") if isinstance(spec.get("callable"), list) else None
        if declared_visible is not None:
            visible_sets.append(_compile_rules([str(rule) for rule in declared_visible]))
        if declared_callable is not None:
            callable_sets.append(_compile_rules([str(rule) for rule in declared_callable]))
        visible_count = 0
        callable_count = 0
        for tool in ctx.tools:
            upstream, tool_name = tool["upstream"], tool["name"]
            is_visible = bool(visible_sets) and all(
                rules.matches(upstream, tool_name) for rules in visible_sets
            )
            if is_visible:
                visible_count += 1
                if callable_sets and all(
                    rules.matches(upstream, tool_name) for rules in callable_sets
                ):
                    callable_count += 1
        steps.append(
            {
                "profile": name,
                "declared_visible_rules": len(declared_visible or []),
                "declared_callable_rules": len(declared_callable or []),
                "visible_tools_after_step": visible_count,
                "callable_tools_after_step": callable_count,
            }
        )
    return {
        "available": True,
        "chain": chain,
        "depth": len(chain),
        "narrowed_by_local_file": narrowed,
        "steps": steps,
    }


def _verification(ctx: _RolloutContext) -> dict:
    section = {
        "attempted": False,
        "ok": False,
        "refusal_code": 0,
        "refusal_name": "",
        "failed_step": "",
        "detail": "",
        "bundle_sha256": "",
        "issuer_key_id": "",
        "issuer_display": "",
        "audience": [],
        "expires_at": "",
    }
    if ctx.source == "policy_refusal" and isinstance(ctx.state, BundleFailClosed):
        section.update(
            {
                "refusal_code": ctx.state.code,
                "refusal_name": refusal_name(ctx.state.code),
                "failed_step": "policy",
                "detail": ctx.state.message,
            }
        )
        return section
    if not ctx.bundle_path:
        section["detail"] = (
            "no signed bundle configured; E14 verification would not run "
            "(raw-file or open mode)"
        )
        return section
    section["attempted"] = True
    state = ctx.state
    if isinstance(state, ActiveProfile) and isinstance(state.provenance, BundleProvenance):
        provenance = state.provenance
        section.update(
            {
                "ok": True,
                "detail": "the bundle verifies: signature, validity window, "
                "revocation, audience, namespace ceiling, and static checks all pass",
                "bundle_sha256": provenance.bundle_sha256,
                "issuer_key_id": provenance.issuer_key_id,
                "issuer_display": provenance.issuer_display,
                "audience": list(provenance.audience),
                "expires_at": provenance.expires_at,
            }
        )
        return section
    if isinstance(state, BundleFailClosed):
        step = _FAILED_STEPS.get(state.code, "")
        if state.code == BUNDLE_AUDIENCE_MISMATCH and _NAMESPACE_MARKER in state.message:
            step = "namespace_ceiling"
        section.update(
            {
                "refusal_code": state.code,
                "refusal_name": refusal_name(state.code),
                "failed_step": step,
                "detail": state.message,
                "bundle_sha256": state.bundle_sha256,
            }
        )
    return section


def _audit_impact(ctx: _RolloutContext) -> dict:
    levels = {"standard": 0, "minimal": 0}
    if ctx.config is not None:
        for spec in ctx.config.get("upstreams", []):
            level = str(spec.get("audit_level") or "standard")
            levels[level if level in AUDIT_LEVELS else "standard"] += 1
    row: dict = {}
    recorded = False
    note = ""
    state = ctx.state
    if isinstance(state, ActiveProfile):
        recorded = True
        row = {
            "tool": "profile_loaded",
            "ok": True,
            "profile": state.name,
            "profile_sha256": state.file_sha256,
            "visible_rules": state.visible_rule_count,
            "callable_rules": state.callable_rule_count,
        }
        if isinstance(state.provenance, BundleProvenance):
            row.update(state.provenance.audit_fields())
        else:
            row["profile_source"] = "raw_file"
        note = (
            "one profile_loaded startup row pins this profile version; every "
            "per-call row carries the profile name at both audit levels"
        )
    elif isinstance(state, BundleFailClosed):
        recorded = True
        row = {
            "tool": "profile_loaded",
            "ok": False,
            "profile": state.requested,
            "error": state.message,
            "profile_source": state.source,
        }
        if state.bundle_sha256:
            row["bundle_sha256"] = state.bundle_sha256
        note = (
            "the failed verification is as observable as a successful load: one "
            "profile_loaded row names the failing step's code; every refused "
            "call is audited as usual"
        )
    elif isinstance(state, FailClosedProfile):
        note = (
            "a raw-file fail-closed state records no profile_loaded startup row; "
            "every refused call is still audited with the requested profile name"
        )
    else:
        note = (
            "open no-profiles mode: no profile_loaded row; per-call audit rows "
            "omit the profile field entirely (the marker of open mode)"
        )
    return {
        "profile_loaded_row_recorded": recorded,
        "profile_loaded_row": row,
        "note": note,
        "audit_levels": levels,
        "per_call_rows_carry_profile": ctx.state is not None,
    }


def _profile_state_section(ctx: _RolloutContext) -> dict:
    state = ctx.state
    if state is None:
        profile = ""
        code = 0
        message = "no tool profiles: every configured tool is visible and callable (open mode)"
    elif isinstance(state, ActiveProfile):
        profile = state.name
        code = 0
        message = f"profile '{state.name}' would be enforced (default deny outside its rules)"
    else:
        profile = state.requested
        code = state.code
        message = state.message
    return {
        "mode": _mode(ctx),
        "profile": profile,
        "source": ctx.source,
        "refusal_code": code,
        "refusal_name": refusal_name(code) if code else "",
        "message": message,
    }


def plan_rollout(
    root: Path | str | None = None,
    config_path: str = "",
    profiles_path: str = "",
    bundle_path: str = "",
    trusted_keys_path: str = "",
    audience_ids: Sequence[str] = (),
    profile_name: str = "",
    tools_fixture_path: str = "",
    require_signed: bool = False,
    now: float | None = None,
    backend: object = _DEFAULT_BACKEND,
    env_name: str | None = None,
) -> dict:
    """Build the dry-run rollout plan (schemas/mcp-profile-rollout-plan.schema.json).

    Read-only: never spawns an upstream, never writes an audit row, never
    touches the trust store, no network, no telemetry. ``now``/``backend``
    are test injection points threaded into the REAL E14 verification.
    """
    ctx = _prepare(
        Path(root) if root is not None else None,
        config_path,
        profiles_path,
        bundle_path,
        trusted_keys_path,
        audience_ids,
        profile_name,
        tools_fixture_path,
        require_signed,
        now,
        backend,
        env_name,
    )
    blockers = list(ctx.blockers)
    if isinstance(ctx.state, FailClosedProfile):
        code = ctx.state.code
        blockers.append(
            f"the rollout would FAIL CLOSED ({refusal_name(code)}, {code}): "
            "the gateway would serve the meta-tools but refuse every call"
        )
    return {
        "schema_version": PLAN_SCHEMA_VERSION,
        "inputs": ctx.inputs,
        "profile_state": _profile_state_section(ctx),
        "tools": _tool_visibility(ctx),
        "upstreams": _upstream_rows(ctx),
        "inheritance": _inheritance(ctx),
        "verification": _verification(ctx),
        "audit_impact": _audit_impact(ctx),
        "warnings": list(ctx.warnings),
        "blockers": blockers,
    }


# ---------------------------------------------------------------------------
# Policy doctor: the same dry-run, expressed as distinct findings.


def _finding(finding: str, severity: str, detail: str) -> dict:
    return {"finding": finding, "severity": severity, "detail": detail}


def _doctor_trust_findings(ctx: _RolloutContext, findings: list[dict]) -> None:
    """Trust-store findings: missing/corrupt store, expired/revoked keys,
    unknown signing key. REUSES the E15 tolerant readers and store doctor."""
    signing_key_id = ""
    if isinstance(ctx.bundle_document, dict):
        signature = ctx.bundle_document.get("signature")
        if isinstance(signature, dict) and isinstance(signature.get("key_id"), str):
            signing_key_id = signature["key_id"]

    if ctx.bundle_path and ctx.trusted_keys_source == "none":
        findings.append(
            _finding(
                "trust_store_missing",
                SEVERITY_PROBLEM,
                "a signed bundle is configured but there is no --trusted-keys file "
                "and no managed trust store; verification would refuse with "
                "bundle_key_missing (-32019)",
            )
        )
        return

    if not ctx.trusted_keys_path:
        return
    keys_path = Path(ctx.trusted_keys_path)
    if not keys_path.is_file():
        findings.append(
            _finding(
                "trust_store_missing",
                SEVERITY_PROBLEM,
                f"trusted-keys file {keys_path.name} does not exist; verification "
                "would refuse with bundle_key_missing (-32019)",
            )
        )
        return
    entries, file_problems = _read_trusted_keys_raw(keys_path)
    entry_problems = [problem for entry in entries for problem in entry.problems]
    if file_problems or entry_problems:
        findings.append(
            _finding(
                "trust_store_corrupt",
                SEVERITY_PROBLEM,
                "the trusted-keys file has problems ("
                + "; ".join((file_problems + entry_problems)[:_MAX_FINDING_DETAILS])
                + "); verification would refuse with bundle_key_missing (-32019)",
            )
        )

    # Revoked key ids come from the CRL(s) the rollout would consult: the
    # bundle's declared crl_path (what E14 verification reads) plus the
    # managed store's crl.json when the managed store is in play.
    revoked_ids: set[str] = set()
    crl_paths: list[Path] = []
    if isinstance(ctx.bundle_document, dict):
        revocation = ctx.bundle_document.get("revocation")
        if isinstance(revocation, dict) and isinstance(revocation.get("crl_path"), str):
            import os as _os

            crl_paths.append(Path(_os.path.expanduser(revocation["crl_path"])))
    if ctx.trusted_keys_source == "managed" and ctx.store_dir:
        crl_paths.append(TrustStore(Path(ctx.store_dir)).crl_path)
    for crl_path in crl_paths:
        if not crl_path.is_file():
            continue
        crl, _ = _read_crl_raw(crl_path)
        revoked_ids.update(str(item) for item in crl.get("revoked_key_ids", []))

    for entry in entries:
        if not entry.key_id:
            continue
        is_signing_key = entry.key_id == signing_key_id
        if entry.not_after is not None and ctx.now >= entry.not_after:
            severity = SEVERITY_PROBLEM if is_signing_key else SEVERITY_WARNING
            detail = f"trusted key '{entry.key_id}' is past its not_after ({entry.not_after_text})"
            if is_signing_key:
                detail += (
                    "; it signs the configured bundle, so verification would "
                    "refuse with bundle_key_missing (-32019)"
                )
            findings.append(_finding("key_expired", severity, detail))
        if entry.key_id in revoked_ids:
            severity = SEVERITY_PROBLEM if is_signing_key else SEVERITY_WARNING
            detail = f"trusted key '{entry.key_id}' is listed in the local CRL"
            if is_signing_key:
                detail += (
                    "; it signs the configured bundle, so verification would "
                    "refuse with bundle_revoked (-32017)"
                )
            findings.append(_finding("key_revoked", severity, detail))

    if ctx.bundle_path and signing_key_id and not (file_problems or entry_problems):
        known = {entry.key_id for entry in entries if entry.key_id}
        if signing_key_id not in known:
            findings.append(
                _finding(
                    "unknown_key_id",
                    SEVERITY_PROBLEM,
                    f"the bundle is signed by key '{signing_key_id}' which is absent "
                    "from the trusted-keys file; verification would refuse with "
                    "bundle_key_missing (-32019)",
                )
            )

    # The E15 store doctor's own checks (rotation, metadata, permissions,
    # strict-loader agreement) pass through when the managed store is used.
    if ctx.trusted_keys_source == "managed" and ctx.store_dir:
        report = trust_store_doctor_report(TrustStore(Path(ctx.store_dir)), now=ctx.now)
        for problem in report["problems"]:
            findings.append(_finding("trust_store_doctor", SEVERITY_PROBLEM, problem))
        for warning in report["warnings"]:
            findings.append(_finding("trust_store_doctor", SEVERITY_WARNING, warning))


def _doctor_bundle_findings(ctx: _RolloutContext, findings: list[dict]) -> None:
    """Bundle-artifact findings independent of the first-failing-step order
    of verification: audience, issuer namespace ceiling, validity window."""
    document = ctx.bundle_document
    if not ctx.bundle_path:
        return
    if not isinstance(document, dict):
        findings.append(
            _finding(
                "bundle_unreadable",
                SEVERITY_PROBLEM,
                "the bundle file cannot be read as a JSON object; verification "
                "would refuse with profile_invalid (-32014)",
            )
        )
        return

    audience = document.get("audience")
    if isinstance(audience, list) and audience:
        bundle_ids = {str(item) for item in audience}
        if not set(ctx.local_ids) & bundle_ids:
            findings.append(
                _finding(
                    "audience_mismatch",
                    SEVERITY_PROBLEM,
                    f"bundle audience [{', '.join(sorted(bundle_ids))}] does not "
                    f"intersect local identifiers [{', '.join(ctx.local_ids) or '<none>'}]; "
                    "verification would refuse with bundle_audience_mismatch (-32018)",
                )
            )

    ceiling = document.get("allowed_upstream_namespaces")
    profiles_map = document.get("profiles")
    if isinstance(ceiling, list) and isinstance(profiles_map, dict):
        ceiling_rules = [str(rule) for rule in ceiling]
        shown = 0
        for profile_name, spec in profiles_map.items():
            if not isinstance(spec, dict):
                continue
            for field in ("visible", "callable"):
                rules = spec.get(field) if isinstance(spec.get(field), list) else []
                for rule in rules:
                    if isinstance(rule, str) and not _rule_covered(rule, ceiling_rules):
                        if shown < _MAX_FINDING_DETAILS:
                            findings.append(
                                _finding(
                                    "issuer_scope_violation",
                                    SEVERITY_PROBLEM,
                                    f"profile '{profile_name}' {field} rule '{rule}' is outside "
                                    "the issuer's allowed_upstream_namespaces ceiling; "
                                    "verification would refuse with bundle_audience_mismatch "
                                    "(-32018)",
                                )
                            )
                        shown += 1

    issued_at = document.get("issued_at")
    expires_at = document.get("expires_at")
    if (
        isinstance(issued_at, str)
        and isinstance(expires_at, str)
        and TIMESTAMP_RE.match(issued_at)
        and TIMESTAMP_RE.match(expires_at)
    ):
        start = _parse_timestamp(issued_at)
        end = _parse_timestamp(expires_at)
        if not (start - CLOCK_SKEW_SECONDS <= ctx.now < end + CLOCK_SKEW_SECONDS):
            findings.append(
                _finding(
                    "bundle_expired",
                    SEVERITY_PROBLEM,
                    f"the current time is outside the bundle's signed validity window "
                    f"({issued_at} .. {expires_at}); verification would refuse with "
                    "bundle_expired (-32016)",
                )
            )


def _doctor_profile_findings(ctx: _RolloutContext, findings: list[dict]) -> None:
    """Profile-policy findings: hides-all, inert callable rules, deep
    chains, shadowed tool names."""
    # Chain depth, measured tolerantly on whichever documents are present
    # (an over-deep chain makes the strict loaders fail with -32014, so the
    # distinct finding must not depend on a successful load).
    deep_profiles: set[str] = set()
    for document in (ctx.profiles_document, ctx.bundle_document):
        profiles_map = (document or {}).get("profiles")
        if not isinstance(profiles_map, dict):
            continue
        for name in profiles_map:
            if str(name) in deep_profiles:
                continue
            if len(_extends_chain(profiles_map, str(name))) > MAX_EXTENDS_DEPTH:
                deep_profiles.add(str(name))
                findings.append(
                    _finding(
                        "profile_chain_too_deep",
                        SEVERITY_PROBLEM,
                        f"profile '{name}' has an extends chain deeper than "
                        f"{MAX_EXTENDS_DEPTH}; loading would fail with profile_invalid "
                        "(-32014)",
                    )
                )

    state = ctx.state
    if isinstance(state, ActiveProfile):
        if ctx.tools and not any(
            state.is_visible(tool["upstream"], tool["name"]) for tool in ctx.tools
        ):
            findings.append(
                _finding(
                    "profile_hides_all_tools",
                    SEVERITY_PROBLEM,
                    f"profile '{state.name}' hides every one of the {len(ctx.tools)} "
                    "known tool(s): the visible set is empty, tools_search would "
                    "return nothing, and no upstream would ever spawn",
                )
            )
        document = ctx.bundle_document if ctx.bundle_path else ctx.profiles_document
        profiles_map = (document or {}).get("profiles")
        if isinstance(profiles_map, dict) and state.name in profiles_map:
            chain = _extends_chain(profiles_map, state.name)
            callable_rules: list[tuple[str, str]] = []  # (profile, rule)
            for name in chain:
                spec = profiles_map.get(name)
                if isinstance(spec, dict) and isinstance(spec.get("callable"), list):
                    callable_rules.extend((name, str(rule)) for rule in spec["callable"])
            shown = 0
            for profile_name, rule in callable_rules:
                # A callable rule is INERT when no tool it matches could ever
                # be visible under the resolved chain (callable always
                # requires visible). A parent's broad rule narrowed by a
                # child is normal restriction-only inheritance, not inert.
                upstream, _, tool_name = rule.partition(".")
                if tool_name == "*":
                    covered = state.upstream_has_visible_tools(upstream)
                else:
                    covered = state.is_visible(upstream, tool_name)
                if not covered and shown < _MAX_FINDING_DETAILS:
                    findings.append(
                        _finding(
                            "callable_not_covered",
                            SEVERITY_WARNING,
                            f"callable rule '{rule}' (declared in profile "
                            f"'{profile_name}') matches nothing the resolved visible "
                            "set could ever contain; it can never fire (callable "
                            "always requires visible) and is dead weight",
                        )
                    )
                    shown += 1

    # Shadowed tool names: the same tool name on multiple upstreams is a
    # confused-deputy heads-up (an agent addressing by bare name may be
    # routed to the wrong upstream by a stale or hostile description).
    by_name: dict[str, set[str]] = {}
    for tool in ctx.tools:
        by_name.setdefault(tool["name"], set()).add(tool["upstream"])
    shown = 0
    for name in sorted(by_name):
        upstreams = by_name[name]
        if len(upstreams) > 1 and shown < _MAX_FINDING_DETAILS:
            findings.append(
                _finding(
                    "shadowed_tool_name",
                    SEVERITY_WARNING,
                    f"tool name '{name}' exists on multiple upstreams "
                    f"({', '.join(sorted(upstreams))}); fully qualified addressing "
                    "prevents confusion, but review which one each profile rule "
                    "intends (confused-deputy heads-up)",
                )
            )
            shown += 1


def _doctor_policy_findings(ctx: _RolloutContext, findings: list[dict]) -> None:
    if ctx.require_signed and ctx.profiles_path and not ctx.bundle_path:
        findings.append(
            _finding(
                "unsigned_under_signed_policy",
                SEVERITY_PROBLEM,
                "--require-signed-profiles is set but the only profile source is an "
                "unsigned --profiles file; the gateway would refuse fail-closed with "
                "bundle_signature_invalid (-32015)",
            )
        )
    if ctx.require_signed and ctx.profiles_path and ctx.bundle_path:
        findings.append(
            _finding(
                "unsigned_local_narrowing",
                SEVERITY_WARNING,
                "an unsigned local --profiles file participates under the "
                "signed-required policy; it is allowed because it can only NARROW "
                "the verified bundle (never widen), but it is an unsigned artifact "
                "in a signed rollout -- make sure that is intended",
            )
        )


def doctor_rollout(
    root: Path | str | None = None,
    config_path: str = "",
    profiles_path: str = "",
    bundle_path: str = "",
    trusted_keys_path: str = "",
    audience_ids: Sequence[str] = (),
    profile_name: str = "",
    tools_fixture_path: str = "",
    require_signed: bool = False,
    now: float | None = None,
    backend: object = _DEFAULT_BACKEND,
    env_name: str | None = None,
) -> dict:
    """Run the policy doctor over the same dry-run inputs as the plan.

    Each detectable condition is a distinct finding with a severity:
    ``problem`` (exit 1) or ``warning`` (exit 0). Unlike verification --
    which stops at the first failing step -- the doctor reports every
    independent condition it can see, reusing the E15 trust-store doctor
    and the E14 building blocks instead of reimplementing them.
    """
    ctx = _prepare(
        Path(root) if root is not None else None,
        config_path,
        profiles_path,
        bundle_path,
        trusted_keys_path,
        audience_ids,
        profile_name,
        tools_fixture_path,
        require_signed,
        now,
        backend,
        env_name,
    )
    findings: list[dict] = []
    for blocker in ctx.blockers:
        findings.append(_finding("input_error", SEVERITY_PROBLEM, blocker))
    _doctor_trust_findings(ctx, findings)
    _doctor_bundle_findings(ctx, findings)
    _doctor_profile_findings(ctx, findings)
    _doctor_policy_findings(ctx, findings)

    # The authoritative dry-run outcome: the REAL resolution's first failing
    # step, with its exact refusal code (never reimplemented).
    if isinstance(ctx.state, FailClosedProfile):
        findings.append(
            _finding(
                "rollout_fail_closed",
                SEVERITY_PROBLEM,
                f"the rollout would fail closed with {refusal_name(ctx.state.code)} "
                f"({ctx.state.code}): {ctx.state.message}",
            )
        )
    if not ctx.tools:
        findings.append(
            _finding(
                "no_tools",
                SEVERITY_WARNING,
                "no tool list available (no pre-declared config tools and no "
                "--tools-fixture); visibility findings are over an empty set",
            )
        )
    problems = sum(1 for item in findings if item["severity"] == SEVERITY_PROBLEM)
    warnings = sum(1 for item in findings if item["severity"] == SEVERITY_WARNING)
    return {
        "inputs": ctx.inputs,
        "status": "problems" if problems else "ok",
        "findings": findings,
        "summary": {"problems": problems, "warnings": warnings},
        "exit_code": 1 if problems else 0,
    }


# ---------------------------------------------------------------------------
# Human renderers (text mode; --json prints the dicts verbatim).


def format_rollout_plan(plan: dict) -> str:
    state = plan["profile_state"]
    tools = plan["tools"]
    verification = plan["verification"]
    lines = [
        f"MCP profile rollout plan (dry-run; nothing spawned, nothing changed)",
        f"mode: {state['mode']} -- source: {state['source']}"
        + (f" -- profile: {state['profile']}" if state["profile"] else ""),
        f"  {state['message']}",
        (
            f"tools: {tools['total']} total -- {tools['visible']} visible, "
            f"{tools['hidden']} hidden, {tools['callable']} callable, "
            f"{tools['view_only']} view-only, {tools['refused_by_policy']} refused by policy"
        ),
    ]
    for fq in tools["visible_tools"]:
        lines.append(f"  visible: {fq}")
    for row in plan["upstreams"]:
        spawn = "would spawn on demand" if row["would_spawn"] else "would NEVER spawn"
        note = f" ({row['note']})" if row["note"] else ""
        lines.append(
            f"upstream {row['name']}: trust={row['trust_level']} "
            f"declared={row['declared_tools']} visible={row['visible_tools']} -- {spawn}{note}"
        )
    inheritance = plan["inheritance"]
    if inheritance["available"]:
        lines.append(
            "inheritance: " + " -> ".join(reversed(inheritance["chain"]))
            + (" (narrowed further by the local file)" if inheritance["narrowed_by_local_file"] else "")
        )
        for step in inheritance["steps"]:
            lines.append(
                f"  {step['profile']}: declares {step['declared_visible_rules']} visible / "
                f"{step['declared_callable_rules']} callable rule(s) -> "
                f"{step['visible_tools_after_step']} visible, "
                f"{step['callable_tools_after_step']} callable tool(s) so far"
            )
    if verification["attempted"]:
        if verification["ok"]:
            lines.append(
                f"verification: OK -- bundle {verification['bundle_sha256'][:16]} by "
                f"'{verification['issuer_key_id']}' for "
                f"[{', '.join(verification['audience'])}], expires {verification['expires_at']}"
            )
        else:
            lines.append(
                f"verification: REFUSED at step '{verification['failed_step']}' with "
                f"{verification['refusal_name']} ({verification['refusal_code']})"
            )
    else:
        lines.append(f"verification: not attempted -- {verification['detail']}")
    audit = plan["audit_impact"]
    lines.append(
        "audit: profile_loaded row "
        + ("WOULD be recorded" if audit["profile_loaded_row_recorded"] else "would NOT be recorded")
        + f"; upstream audit levels: {audit['audit_levels']['standard']} standard, "
        + f"{audit['audit_levels']['minimal']} minimal"
    )
    for warning in plan["warnings"]:
        lines.append(f"warning: {warning}")
    for blocker in plan["blockers"]:
        lines.append(f"BLOCKER: {blocker}")
    if not plan["blockers"]:
        lines.append("blockers: none")
    return "\n".join(lines)


def format_rollout_doctor(report: dict) -> str:
    summary = report["summary"]
    lines = [
        f"MCP profile rollout doctor: {report['status']} -- "
        f"{summary['problems']} problem(s), {summary['warnings']} warning(s)"
    ]
    for item in report["findings"]:
        mark = "PROBLEM" if item["severity"] == SEVERITY_PROBLEM else "warning"
        lines.append(f"  [{mark}] {item['finding']}: {item['detail']}")
    if not report["findings"]:
        lines.append("  no findings")
    return "\n".join(lines)
