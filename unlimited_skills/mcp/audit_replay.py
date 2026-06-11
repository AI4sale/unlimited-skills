"""MCP audit replay and policy impact simulator (E17).

Takes the HISTORICAL redacted audit JSONL log (the E11 inspector's readers
are reused verbatim: active file plus rotated generations, malformed lines
counted and skipped) and a PROPOSED policy (raw E09/E10 profile file, E13/E14
signed bundle, E14/E15 trust artifacts, optional gateway upstream config) and
answers, before anything is applied:

- which historical tool calls would still pass under the proposed policy,
- which would be refused, and with exactly which would-be refusal code,
- which workflows (tools with real historical usage) would break,
- how the impact distributes by tool, upstream, profile, refusal code,
  time bucket, and call type,
- whether the rollout is ``safe`` / ``safe_with_warnings`` / ``blocked``.

The proposed policy is resolved with the REAL E10/E14/E15 machinery in
dry-run -- :func:`unlimited_skills.mcp.bundles.resolve_bundle_state` and
:func:`unlimited_skills.mcp.profiles.resolve_profile_state` run unchanged,
mirroring the gateway's own startup dispatch (and E16's simulator) -- never
a reimplementation. Refusal-code classification of historical rows reuses
:mod:`unlimited_skills.mcp.audit_inspector`.

Everything here is READ-ONLY and OFFLINE by construction: no tool is ever
executed, no upstream is ever spawned (no subprocess use at all), no profile
is activated, no audit row is written, no runtime state changes, no network,
no telemetry, and no private key material is read or printed.

Privacy: the report contains tool names, upstream names, profile names,
counts, refusal codes, timestamps/buckets, and documented non-sensitive
hashes (bundle/profile SHA-256) ONLY -- never argument values, results,
error text from audit rows, prompts, tokens, proofs, key material, or
local filesystem paths (inputs are reported as basenames).

Replay semantics (documented design decisions):

- **Replayable events** are ``tools_schema`` and ``tools_call`` rows that
  carry a fully qualified tool identity (the redacted ``args.tool`` field,
  written at audit level ``standard``). Rows lacking a tool identity (audit
  level ``minimal``) are COUNTED, never guessed. ``tools_search`` rows are
  not per-tool and ``skills_*`` rows are not profile-gated; both are counted
  by class only.
- **Per-call evaluation order** mirrors the gateway: fail-closed profile
  state first, then visibility (-32011, ``tools_schema`` and ``tools_call``),
  then callability (-32012, ``tools_call`` only), then -- when a gateway
  config is given -- the upstream trust gates (-32005 disabled, -32010
  future-remote-placeholder, plus ``upstream_not_configured`` for upstreams
  the config does not know).
- **The comparison axis is policy admission.** A historical call counts as
  historically allowed when it succeeded OR when it was refused for a
  non-policy runtime reason (timeouts, protocol errors: the call PASSED
  policy); it counts as historically denied only when its refusal code is
  in the policy family (-32011..-32019). Replay can predict policy, never
  runtime weather.
- **Recommendation thresholds**: ``blocked`` when the proposed policy
  itself fails closed (bundle verification failure, invalid profile file,
  signed-required refusal), when an input the gateway would refuse at
  startup is present, or when more than ``BLOCK_BREAKAGE_RATIO`` (20%) of
  the replayed historical calls become newly denied; ``safe_with_warnings``
  when anything became newly denied or any finding fired; ``safe``
  otherwise.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Sequence

from .audit import scrub_paths
from .audit_inspector import (
    PROFILE_EVENT_TOOL,
    load_audit_rows,
    refusal_code_of,
)
from .bundles import (
    BUNDLE_AUDIENCE_MISMATCH,
    BUNDLE_REVOKED,
    BundleFailClosed,
    BundleProvenance,
    _DEFAULT_BACKEND,
    require_signed_refusal,
    resolve_bundle_state,
)
from .gateway import (
    DEFAULT_TRUST_LEVEL,
    GatewayConfigError,
    TRUST_DISABLED,
    TRUST_FUTURE_REMOTE,
    TRUST_LEVEL_VIOLATION,
    UPSTREAM_DISABLED,
    load_gateway_config,
)
from .profile_rollout import (
    _FAILED_STEPS,
    _NAMESPACE_MARKER,
    REFUSAL_NAMES,
    SEVERITY_PROBLEM,
    SEVERITY_WARNING,
)
from .profiles import (
    TOOL_NOT_CALLABLE,
    TOOL_NOT_VISIBLE,
    ActiveProfile,
    FailClosedProfile,
    resolve_profile_state,
)
from .trust_store import managed_trusted_keys_path

REPORT_TYPE = "mcp-audit-replay-report"
REPORT_SCHEMA_VERSION = 1

# The policy refusal-code family: profile enforcement (-32011..-32014) plus
# bundle verification fail-closed states (-32015..-32019). A historical
# refusal with one of these codes was a POLICY denial; anything else was a
# runtime failure the call had already been admitted to attempt.
POLICY_REFUSAL_CODES = frozenset(range(-32019, -32010))

# Recommendation threshold (documented in docs/mcp-audit-replay.md): the
# rollout is blocked when more than this fraction of the replayed historical
# calls becomes newly denied under the proposed policy.
BLOCK_BREAKAGE_RATIO = 0.20

_MAX_FINDING_DETAILS = 5  # cap repeated per-tool findings of one class

CALL_TYPES = ("tools_search", "tools_schema", "tools_call", "skills", "other")
REPLAYABLE_CALL_TYPES = ("tools_schema", "tools_call")

# Would-be refusal names for the codes replay can predict. -32011..-32019
# reuse E16's table; -32005/-32010 are the config trust gates; 0 with the
# name 'upstream_not_configured' marks an upstream the proposed gateway
# config does not know (the gateway reports that as a tool error without a
# reserved JSON-RPC refusal code).
_WOULD_BE_NAMES: dict[int, str] = dict(REFUSAL_NAMES)
_WOULD_BE_NAMES[UPSTREAM_DISABLED] = "upstream_disabled"
_WOULD_BE_NAMES[TRUST_LEVEL_VIOLATION] = "trust_level_violation"
UPSTREAM_NOT_CONFIGURED_NAME = "upstream_not_configured"


def would_be_name(code: int) -> str:
    return _WOULD_BE_NAMES.get(code, "unknown")


def _format_ts(value: float) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(value))


def time_bucket_of(row: dict) -> str:
    """UTC hour bucket of one audit row ('YYYY-MM-DDTHH:00Z'), or 'unknown'."""
    ts = row.get("ts")
    if not isinstance(ts, (int, float)) or isinstance(ts, bool):
        return "unknown"
    parts = time.gmtime(float(ts))
    return f"{parts.tm_year:04d}-{parts.tm_mon:02d}-{parts.tm_mday:02d}T{parts.tm_hour:02d}:00Z"


# ---------------------------------------------------------------------------
# Event classification (criterion: never guess a missing tool identity).


def call_type_of(row: dict) -> str:
    """Classify one audit row's meta-tool into a call type.

    ``profile_loaded`` rows are lifecycle events, classified separately by
    the caller; this function only sees call rows.
    """
    tool = str(row.get("tool") or "")
    if tool in ("tools_search", "tools_schema", "tools_call"):
        return tool
    if tool.startswith("skills_"):
        return "skills"
    return "other"


def historical_outcome_of(row: dict) -> str:
    """``ok`` / ``profile_denied`` / ``upstream_refusal`` for one call row."""
    if row.get("ok") is True:
        return "ok"
    code = refusal_code_of(row)
    if code in POLICY_REFUSAL_CODES:
        return "profile_denied"
    return "upstream_refusal"


def tool_identity_of(row: dict) -> tuple[str, str] | None:
    """``(upstream, tool)`` from the redacted ``args.tool`` field, or None.

    Audit rows written at level ``minimal`` drop the args shape entirely, so
    the fully qualified tool name is unrecoverable; those rows are counted
    as missing identity, never guessed from the bare ``upstream`` field.
    """
    args = row.get("args")
    if not isinstance(args, dict):
        return None
    fq = args.get("tool")
    if not isinstance(fq, str):
        return None
    upstream, _, tool = fq.partition(".")
    if not upstream or not tool:
        return None
    return upstream, tool


# ---------------------------------------------------------------------------
# Proposed-policy resolution: the gateway's startup dispatch in dry-run
# (parity with commands.mcp._resolve_gateway_profile_state and E16).


class _ProposedPolicy:
    """The resolved proposed policy (plain attributes, no behavior)."""

    def __init__(self) -> None:
        self.state: ActiveProfile | FailClosedProfile | None = None
        self.source = "none"
        self.trust_levels: dict[str, str] | None = None  # None = no config given
        self.trusted_keys_path = ""
        self.trusted_keys_source = "none"
        self.input_errors: list[str] = []
        self.config_error = ""


def _effective_trust_level(spec: dict) -> str:
    """The gateway's UpstreamClient semantics: enabled:false forces disabled."""
    if spec.get("enabled", True) is False:
        return TRUST_DISABLED
    return str(spec.get("trust_level") or DEFAULT_TRUST_LEVEL)


def _resolve_policy(
    root: Path | None,
    config_path: str,
    profiles_path: str,
    bundle_path: str,
    trusted_keys_path: str,
    trust_store_dir: str,
    audience_ids: Sequence[str],
    profile_name: str,
    require_signed: bool,
    now: float,
    backend: object,
    env_name: str | None,
) -> _ProposedPolicy:
    policy = _ProposedPolicy()
    audience = [item for item in (audience_ids or []) if item]

    if config_path:
        try:
            config = load_gateway_config(Path(config_path).expanduser())
            policy.trust_levels = {
                str(spec.get("name")): _effective_trust_level(spec)
                for spec in config.get("upstreams", [])
            }
        except GatewayConfigError as exc:
            policy.config_error = scrub_paths(str(exc))

    # Trusted-keys resolution precedence: explicit file > --trust-store
    # directory > the E15 managed store under the library root (only ever
    # consulted when a bundle is configured, exactly like the gateway).
    if trusted_keys_path:
        policy.trusted_keys_path = str(Path(trusted_keys_path).expanduser())
        policy.trusted_keys_source = "explicit"
    elif trust_store_dir and bundle_path:
        policy.trusted_keys_path = str(
            Path(trust_store_dir).expanduser() / "trusted-keys.json"
        )
        policy.trusted_keys_source = "store_dir"
    elif bundle_path and root is not None:
        managed = managed_trusted_keys_path(Path(root))
        if managed.is_file():
            policy.trusted_keys_path = str(managed)
            policy.trusted_keys_source = "managed"

    # Flag-combination rules the gateway enforces at startup: violating
    # them means the gateway would refuse to START.
    if not bundle_path and (trusted_keys_path or trust_store_dir):
        policy.input_errors.append(
            "--trusted-keys/--trust-store requires --bundle (the signed bundle "
            "path); the gateway would refuse to start"
        )
    if not bundle_path and audience:
        policy.input_errors.append(
            "--audience-id requires --bundle (the signed bundle path); "
            "the gateway would refuse to start"
        )
    if profile_name and not bundle_path and not profiles_path and not require_signed:
        policy.input_errors.append(
            "--profile requires --profiles or --bundle (a profile source); "
            "the gateway would refuse to start"
        )

    if bundle_path:
        policy.state = resolve_bundle_state(
            Path(bundle_path).expanduser(),
            trusted_keys_path=(
                Path(policy.trusted_keys_path) if policy.trusted_keys_path else None
            ),
            cli_name=profile_name,
            env_name=env_name,
            audience_ids=audience or None,
            local_profiles_path=(
                Path(profiles_path).expanduser() if profiles_path else None
            ),
            now=now,
            backend=backend,
        )
        if profiles_path and isinstance(policy.state, ActiveProfile):
            policy.source = "signed_bundle_narrowed"
        else:
            policy.source = "signed_bundle"
    elif profiles_path:
        if require_signed:
            policy.state = require_signed_refusal(
                "--require-signed-profiles is set but --profiles names an "
                "unsigned profile file and no bundle is configured",
                requested=profile_name,
            )
            policy.source = "policy_refusal"
        else:
            policy.state = resolve_profile_state(
                Path(profiles_path).expanduser(), cli_name=profile_name, env_name=env_name
            )
            policy.source = "raw_file"
    elif require_signed:
        policy.state = require_signed_refusal(
            "--require-signed-profiles is set but no bundle is configured",
            requested=profile_name,
        )
        policy.source = "policy_refusal"
    return policy


def evaluate_call(
    policy: _ProposedPolicy, call_type: str, upstream: str, tool: str
) -> tuple[bool, int, str]:
    """Would the proposed policy admit one historical call? -> (allow, code, name).

    Mirrors the gateway's per-request order: fail-closed profile state,
    visibility (existence-neutral -32011), callability (-32012,
    ``tools_call`` only), then the config trust gates. The evaluator only
    ever sees the fully qualified tool name -- never call arguments.
    """
    state = policy.state
    if isinstance(state, FailClosedProfile):
        return False, state.code, would_be_name(state.code)
    if isinstance(state, ActiveProfile):
        if not state.is_visible(upstream, tool):
            return False, TOOL_NOT_VISIBLE, would_be_name(TOOL_NOT_VISIBLE)
        if call_type == "tools_call" and not state.is_callable(upstream, tool):
            return False, TOOL_NOT_CALLABLE, would_be_name(TOOL_NOT_CALLABLE)
    if policy.trust_levels is not None:
        trust = policy.trust_levels.get(upstream)
        if trust is None:
            return False, 0, UPSTREAM_NOT_CONFIGURED_NAME
        if trust == TRUST_DISABLED:
            return False, UPSTREAM_DISABLED, would_be_name(UPSTREAM_DISABLED)
        if trust == TRUST_FUTURE_REMOTE:
            return False, TRUST_LEVEL_VIOLATION, would_be_name(TRUST_LEVEL_VIOLATION)
    return True, 0, ""


# ---------------------------------------------------------------------------
# Report sections.


def _policy_section(policy: _ProposedPolicy) -> dict:
    state = policy.state
    if state is None:
        mode, profile, code, message = (
            "open",
            "",
            0,
            "no proposed tool profiles: every historical call passes the policy "
            "axis (open mode)",
        )
    elif isinstance(state, ActiveProfile):
        mode, profile, code = "enforced", state.name, 0
        message = (
            f"profile '{state.name}' would be enforced (default deny outside its rules)"
        )
    else:
        mode, profile, code = "fail_closed", state.requested, state.code
        message = scrub_paths(state.message)
    if policy.input_errors:
        mode = "blocked"
    return {
        "mode": mode,
        "profile": profile,
        "source": policy.source,
        "refusal_code": code,
        "refusal_name": would_be_name(code) if code else "",
        "message": message,
    }


def _verification_section(policy: _ProposedPolicy, bundle_path: str) -> dict:
    section = {
        "attempted": False,
        "ok": False,
        "refusal_code": 0,
        "refusal_name": "",
        "failed_step": "",
        "bundle_sha256": "",
        "issuer_key_id": "",
        "audience": [],
        "expires_at": "",
    }
    state = policy.state
    if policy.source == "policy_refusal" and isinstance(state, BundleFailClosed):
        section.update(
            {
                "refusal_code": state.code,
                "refusal_name": would_be_name(state.code),
                "failed_step": "policy",
            }
        )
        return section
    if not bundle_path:
        return section
    section["attempted"] = True
    if isinstance(state, ActiveProfile) and isinstance(state.provenance, BundleProvenance):
        provenance = state.provenance
        section.update(
            {
                "ok": True,
                "bundle_sha256": provenance.bundle_sha256,
                "issuer_key_id": provenance.issuer_key_id,
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
                "refusal_name": would_be_name(state.code),
                "failed_step": step,
                "bundle_sha256": state.bundle_sha256,
            }
        )
    return section


def _finding(finding: str, severity: str, detail: str) -> dict:
    return {"finding": finding, "severity": severity, "detail": detail}


class _Tally:
    """One breakdown bucket: replay counters for a single key."""

    __slots__ = ("replayed", "would_allow", "would_deny", "newly_denied", "newly_allowed")

    def __init__(self) -> None:
        self.replayed = 0
        self.would_allow = 0
        self.would_deny = 0
        self.newly_denied = 0
        self.newly_allowed = 0

    def as_dict(self) -> dict:
        return {
            "replayed": self.replayed,
            "would_allow": self.would_allow,
            "would_deny": self.would_deny,
            "newly_denied": self.newly_denied,
            "newly_allowed": self.newly_allowed,
        }


def replay_audit(
    audit_path: Path,
    root: Path | str | None = None,
    config_path: str = "",
    profiles_path: str = "",
    bundle_path: str = "",
    trusted_keys_path: str = "",
    trust_store_dir: str = "",
    audience_ids: Sequence[str] = (),
    profile_name: str = "",
    require_signed: bool = False,
    now: float | None = None,
    backend: object = _DEFAULT_BACKEND,
    env_name: str | None = None,
) -> dict:
    """Replay one audit log against the proposed policy; build the report.

    Pure with respect to the filesystem (reads only); deterministic for the
    same inputs and ``now`` (``generated_at`` is the only wall-clock field,
    derived from ``now``). Raises :class:`FileNotFoundError` when no audit
    file exists at ``audit_path``. The document validates against
    ``schemas/mcp-audit-replay-report.schema.json``.
    """
    current = time.time() if now is None else float(now)
    rows, malformed, file_names = load_audit_rows(Path(audit_path))
    policy = _resolve_policy(
        Path(root) if root is not None else None,
        config_path,
        profiles_path,
        bundle_path,
        trusted_keys_path,
        trust_store_dir,
        audience_ids,
        profile_name,
        require_signed,
        current,
        backend,
        env_name,
    )

    # -- Event classification ------------------------------------------------
    by_call_type = {name: 0 for name in CALL_TYPES}
    profile_loaded_events = 0
    missing_tool_identity = 0
    replayable: list[tuple[dict, str, str, str]] = []  # (row, call_type, upstream, tool)
    for _, _, row in rows:
        if str(row.get("tool") or "") == PROFILE_EVENT_TOOL:
            profile_loaded_events += 1
            continue
        call_type = call_type_of(row)
        by_call_type[call_type] += 1
        if call_type in REPLAYABLE_CALL_TYPES:
            identity = tool_identity_of(row)
            if identity is None:
                missing_tool_identity += 1
            else:
                replayable.append((row, call_type, identity[0], identity[1]))

    # -- Impact computation and breakdowns ------------------------------------
    impact = {
        "replayed": 0,
        "would_allow": 0,
        "would_deny": 0,
        "newly_denied": 0,
        "newly_allowed": 0,
        "unchanged_allowed": 0,
        "unchanged_denied": 0,
    }
    breakdowns: dict[str, dict[str, _Tally]] = {
        "by_tool": {},
        "by_upstream": {},
        "by_profile": {},
        "by_refusal_code": {},
        "by_time_bucket": {},
        "by_call_type": {},
    }
    # Aggregated per-tool transition lists (tool names and codes only).
    newly_denied_tools: dict[tuple[str, int, str], int] = {}
    newly_allowed_tools: dict[str, int] = {}
    # Historical usage for the detections: tools that actually succeeded.
    used_ok: dict[str, set[str]] = {}  # fq tool -> set of call types with ok rows

    for row, call_type, upstream, tool in replayable:
        fq = f"{upstream}.{tool}"
        outcome = historical_outcome_of(row)
        if outcome == "ok":
            used_ok.setdefault(fq, set()).add(call_type)
        allowed, code, name = evaluate_call(policy, call_type, upstream, tool)
        hist_denied = outcome == "profile_denied"
        impact["replayed"] += 1
        impact["would_allow" if allowed else "would_deny"] += 1
        if allowed and hist_denied:
            impact["newly_allowed"] += 1
            newly_allowed_tools[fq] = newly_allowed_tools.get(fq, 0) + 1
        elif allowed:
            impact["unchanged_allowed"] += 1
        elif hist_denied:
            impact["unchanged_denied"] += 1
        else:
            impact["newly_denied"] += 1
            key = (fq, code, name)
            newly_denied_tools[key] = newly_denied_tools.get(key, 0) + 1
        for section, bucket_key in (
            ("by_tool", fq),
            ("by_upstream", upstream),
            ("by_profile", str(row.get("profile") or "")),
            ("by_refusal_code", name if not allowed else "allowed"),
            ("by_time_bucket", time_bucket_of(row)),
            ("by_call_type", call_type),
        ):
            tally = breakdowns[section].setdefault(bucket_key, _Tally())
            tally.replayed += 1
            if allowed:
                tally.would_allow += 1
                if hist_denied:
                    tally.newly_allowed += 1
            else:
                tally.would_deny += 1
                if not hist_denied:
                    tally.newly_denied += 1

    impact["newly_denied_tools"] = [
        {
            "tool": fq,
            "calls": count,
            "would_be_code": code,
            "would_be_name": name,
        }
        for (fq, code, name), count in sorted(newly_denied_tools.items())
    ]
    impact["newly_allowed_tools"] = [
        {"tool": fq, "calls": count} for fq, count in sorted(newly_allowed_tools.items())
    ]

    # -- Detections ------------------------------------------------------------
    findings: list[dict] = []
    for error in policy.input_errors:
        findings.append(_finding("input_error", SEVERITY_PROBLEM, error))
    if policy.config_error:
        findings.append(
            _finding(
                "gateway_config_invalid",
                SEVERITY_PROBLEM,
                f"the proposed gateway config is invalid ({policy.config_error}); "
                "the gateway would refuse to start",
            )
        )

    state = policy.state
    if isinstance(state, BundleFailClosed) and bundle_path:
        verification = _verification_section(policy, bundle_path)
        step = verification["failed_step"]
        code = state.code
        if code == BUNDLE_REVOKED:
            finding_name = "revoked_issuer"
            what = "the bundle's signing key or the bundle itself is revoked"
        elif code == BUNDLE_AUDIENCE_MISMATCH and step == "namespace_ceiling":
            finding_name = "namespace_mismatch"
            what = "a profile rule is outside the issuer's allowed_upstream_namespaces ceiling"
        else:
            finding_name = "bundle_verification_failure"
            what = "the proposed bundle fails E14 verification"
        findings.append(
            _finding(
                finding_name,
                SEVERITY_PROBLEM,
                f"{what}: verification would refuse at step '{step}' with "
                f"{would_be_name(code)} ({code}); every historical call would be denied",
            )
        )
    if isinstance(state, FailClosedProfile):
        findings.append(
            _finding(
                "policy_fail_closed",
                SEVERITY_PROBLEM,
                f"the proposed policy fails closed with {would_be_name(state.code)} "
                f"({state.code}): the gateway would refuse every call",
            )
        )

    if isinstance(state, ActiveProfile):
        hidden_used = sorted(
            fq
            for fq in used_ok
            if not state.is_visible(*fq.partition(".")[::2])
        )
        shown = 0
        for fq in hidden_used:
            if shown < _MAX_FINDING_DETAILS:
                findings.append(
                    _finding(
                        "policy_hides_used_tool",
                        SEVERITY_PROBLEM,
                        f"tool '{fq}' has successful historical calls but the proposed "
                        "policy hides it; every future call would be refused with "
                        f"tool_not_visible ({TOOL_NOT_VISIBLE})",
                    )
                )
            shown += 1
        if shown > _MAX_FINDING_DETAILS:
            findings.append(
                _finding(
                    "policy_hides_used_tool",
                    SEVERITY_PROBLEM,
                    f"...and {shown - _MAX_FINDING_DETAILS} more actively used tool(s) "
                    "the proposed policy hides",
                )
            )
        shown = 0
        for fq in sorted(used_ok):
            upstream, _, tool = fq.partition(".")
            if "tools_call" not in used_ok[fq]:
                continue
            if state.is_visible(upstream, tool) and not state.is_callable(upstream, tool):
                if shown < _MAX_FINDING_DETAILS:
                    findings.append(
                        _finding(
                            "tool_view_only_but_called",
                            SEVERITY_PROBLEM,
                            f"tool '{fq}' has successful historical tools_call rows but "
                            "would be visible-only under the proposed policy; calls "
                            f"would be refused with tool_not_callable ({TOOL_NOT_CALLABLE})",
                        )
                    )
                shown += 1

    if missing_tool_identity:
        findings.append(
            _finding(
                "missing_tool_identity",
                SEVERITY_WARNING,
                f"{missing_tool_identity} historical call row(s) carry no fully "
                "qualified tool identity (audit level 'minimal' drops the args "
                "shape); they are counted, never guessed, and excluded from replay",
            )
        )
    if malformed:
        findings.append(
            _finding(
                "malformed_rows",
                SEVERITY_WARNING,
                f"{malformed} malformed audit line(s) were skipped (counted, never parsed)",
            )
        )
    if not replayable:
        findings.append(
            _finding(
                "nothing_to_replay",
                SEVERITY_WARNING,
                "no replayable tools_schema/tools_call rows with a tool identity in "
                "this audit log; the impact and recommendation are over an empty set",
            )
        )

    # -- Recommendation ----------------------------------------------------------
    blocked_reasons: list[str] = []
    if isinstance(state, FailClosedProfile):
        blocked_reasons.append(
            f"the proposed policy fails closed ({would_be_name(state.code)}, "
            f"{state.code}): every historical call would be refused"
        )
    if policy.input_errors:
        blocked_reasons.append(
            "input flags the gateway would refuse at startup are present"
        )
    if policy.config_error:
        blocked_reasons.append("the proposed gateway config is invalid")
    breakage = (
        impact["newly_denied"] / impact["replayed"] if impact["replayed"] else 0.0
    )
    if impact["replayed"] and breakage > BLOCK_BREAKAGE_RATIO:
        blocked_reasons.append(
            f"{impact['newly_denied']} of {impact['replayed']} replayed historical "
            f"call(s) ({breakage * 100:.1f}%) become newly denied, over the "
            f"{BLOCK_BREAKAGE_RATIO * 100:.0f}% block threshold"
        )
    if blocked_reasons:
        status = "blocked"
        reasons = blocked_reasons
    elif impact["newly_denied"] or findings:
        status = "safe_with_warnings"
        reasons = []
        if impact["newly_denied"]:
            reasons.append(
                f"{impact['newly_denied']} of {impact['replayed']} replayed call(s) "
                f"({breakage * 100:.1f}%) become newly denied, under the "
                f"{BLOCK_BREAKAGE_RATIO * 100:.0f}% block threshold"
            )
        problems = sum(1 for item in findings if item["severity"] == SEVERITY_PROBLEM)
        warnings_count = len(findings) - problems
        if findings:
            reasons.append(
                f"{problems} problem finding(s) and {warnings_count} warning(s) -- review them"
            )
    else:
        status = "safe"
        reasons = [
            "no replayed historical call changes outcome under the proposed policy"
        ]

    return {
        "report_type": REPORT_TYPE,
        "schema_version": REPORT_SCHEMA_VERSION,
        "generated_at": _format_ts(current),
        "inputs": {
            # Basenames only: the report must never carry local paths.
            "audit_log": Path(audit_path).name,
            "config": Path(config_path).name if config_path else "",
            "profiles": Path(profiles_path).name if profiles_path else "",
            "bundle": Path(bundle_path).name if bundle_path else "",
            "trusted_keys": (
                Path(policy.trusted_keys_path).name if policy.trusted_keys_path else ""
            ),
            "trusted_keys_source": policy.trusted_keys_source,
            "profile": profile_name or "",
            "audience_ids": [item for item in (audience_ids or []) if item],
            "require_signed_profiles": bool(require_signed),
        },
        "log": {
            "files_read": file_names,
            "rotated_files_read": sum(
                1 for name in file_names if name.rsplit(".", 1)[-1].isdigit()
            ),
            "rows_total": len(rows),
            "malformed_lines": malformed,
        },
        "policy": _policy_section(policy),
        "verification": _verification_section(policy, bundle_path),
        "events": {
            "calls_total": sum(by_call_type.values()),
            "by_call_type": by_call_type,
            "profile_loaded_events": profile_loaded_events,
            "missing_tool_identity": missing_tool_identity,
            "replayed": impact["replayed"],
        },
        "impact": impact,
        "breakdowns": {
            section: {
                key: tally.as_dict() for key, tally in sorted(entries.items())
            }
            for section, entries in breakdowns.items()
        },
        "findings": findings,
        "recommendation": {
            "status": status,
            "reasons": reasons,
            "thresholds": {"block_breakage_ratio": BLOCK_BREAKAGE_RATIO},
        },
    }


# ---------------------------------------------------------------------------
# Human renderer (text mode; --json prints the dict verbatim).


def format_replay_report(report: dict) -> str:
    policy = report["policy"]
    events = report["events"]
    impact = report["impact"]
    recommendation = report["recommendation"]
    lines = [
        "MCP audit replay (read-only; no tool executed, no upstream spawned, "
        "no profile activated)",
        f"log: {report['log']['rows_total']} row(s) from "
        f"{len(report['log']['files_read'])} file(s), "
        f"{report['log']['malformed_lines']} malformed line(s) skipped",
        f"proposed policy: {policy['mode']} -- source: {policy['source']}"
        + (f" -- profile: {policy['profile']}" if policy["profile"] else ""),
        f"  {policy['message']}",
    ]
    verification = report["verification"]
    if verification["attempted"]:
        if verification["ok"]:
            lines.append(
                f"verification: OK -- bundle {verification['bundle_sha256'][:16]} by "
                f"'{verification['issuer_key_id']}', expires {verification['expires_at']}"
            )
        else:
            lines.append(
                f"verification: REFUSED at step '{verification['failed_step']}' with "
                f"{verification['refusal_name']} ({verification['refusal_code']})"
            )
    lines.append(
        "events: "
        + ", ".join(
            f"{events['by_call_type'][name]} {name}" for name in CALL_TYPES
        )
        + f"; {events['profile_loaded_events']} profile_loaded; "
        f"{events['missing_tool_identity']} without tool identity (counted, not guessed)"
    )
    lines.append(
        f"impact: {impact['replayed']} replayed -- {impact['would_allow']} would pass, "
        f"{impact['would_deny']} would be refused "
        f"({impact['newly_denied']} newly denied, {impact['newly_allowed']} newly allowed, "
        f"{impact['unchanged_allowed']} unchanged-allowed, "
        f"{impact['unchanged_denied']} unchanged-denied)"
    )
    for entry in impact["newly_denied_tools"]:
        lines.append(
            f"  newly denied: {entry['tool']} ({entry['calls']} call(s)) -> "
            f"{entry['would_be_name']} ({entry['would_be_code']})"
        )
    for entry in impact["newly_allowed_tools"]:
        lines.append(f"  newly allowed: {entry['tool']} ({entry['calls']} call(s))")
    for item in report["findings"]:
        mark = "PROBLEM" if item["severity"] == SEVERITY_PROBLEM else "warning"
        lines.append(f"  [{mark}] {item['finding']}: {item['detail']}")
    lines.append(f"recommendation: {recommendation['status'].upper()}")
    for reason in recommendation["reasons"]:
        lines.append(f"  reason: {reason}")
    return "\n".join(lines)
