"""Runtime model binding for the Money Saved meter (O064-R2-00).

Owner directives (2026-06-17), binding:
- The live model is normally ALWAYS known in chat. If a *supported* agent yields no
  binding at all, that is an INTEGRATION BUG (not user misconfiguration): callers
  surface a diagnostic error, never a normal "model_required" money dead-end.
- If the runtime HIDES the live model, fall back to the agent's basic-assumption
  profile (``agent_model_profiles.json``) and mark the report as assumed — the
  calculation still runs.

Detection cascade (highest priority first):

1. explicit    — ``--model provider:model``         -> source=explicit_cli, confidence=exact
2. runtime     — agent self-report (env channel the hook/inject populates from the
                 transcript: ``UNLIMITED_SKILLS_RUNTIME_MODEL``)
                                                     -> source=detected_runtime, confidence=exact
3. env         — ANTHROPIC_MODEL / CLAUDE_MODEL / OPENAI_MODEL / GOOGLE_MODEL /
                 DEEPSEEK_MODEL / UNLIMITED_SKILLS_MODEL
                                                     -> source=env_metadata, confidence=inferred
4. assumption  — the agent's default profile         -> source=basic_assumption_due_hidden_runtime,
                                                       confidence=assumed
5. unknown     — only for an unknown/unsupported agent -> source=unknown, confidence=unknown
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .money_pricing import ModelPrice, resolve_model

SUPPORTED_AGENTS = ("claude-code", "codex", "openclaw", "hermes")

# Ordered env channels for step 3 (provider hint comes from the var name).
_ENV_MODEL_VARS = (
    ("UNLIMITED_SKILLS_MODEL", ""),
    ("ANTHROPIC_MODEL", "anthropic"),
    ("CLAUDE_MODEL", "anthropic"),
    ("OPENAI_MODEL", "openai"),
    ("GOOGLE_MODEL", "google"),
    ("DEEPSEEK_MODEL", "deepseek"),
)

_RUNTIME_MODEL_VAR = "UNLIMITED_SKILLS_RUNTIME_MODEL"


@dataclass(frozen=True)
class ModelBinding:
    provider: str
    model: str
    source: str  # explicit_cli | detected_runtime | env_metadata | basic_assumption_due_hidden_runtime | fixture | unknown
    confidence: str  # exact | inferred | assumed | unknown
    agent: str
    price: ModelPrice | None = None
    note: str = ""
    assumption_profile: str = ""

    @property
    def available(self) -> bool:
        return self.price is not None

    def as_dict(self) -> dict[str, Any]:
        block: dict[str, Any] = {
            "provider": self.provider,
            "model": self.model,
            "source": self.source,
            "confidence": self.confidence,
            "agent": self.agent,
        }
        if self.note:
            block["note"] = self.note
        if self.assumption_profile:
            block["assumption_profile"] = self.assumption_profile
        return block


def agent_profiles_path() -> Path:
    return Path(__file__).with_name("agent_model_profiles.json")


def load_agent_profiles(path: Path | None = None) -> dict[str, Any]:
    try:
        data = json.loads((path or agent_profiles_path()).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def detect_agent(explicit: str | None = None) -> str:
    """Best-effort agent identity. Explicit wins; else env markers; else claude-code."""
    if explicit:
        return explicit
    env_agent = os.environ.get("UNLIMITED_SKILLS_AGENT", "").strip().lower()
    if env_agent in SUPPORTED_AGENTS:
        return env_agent
    if os.environ.get("CODEX_HOME"):
        return "codex"
    if os.environ.get("OPENCLAW_HOME") or os.environ.get("OPENCLAW_WORKSPACE"):
        return "openclaw"
    if os.environ.get("HERMES_HOME"):
        return "hermes"
    # Claude Code is the default supported host for this package.
    return "claude-code"


def _assumption_spec(agent: str, profiles: dict[str, Any]) -> str | None:
    entry = (profiles.get("profiles") or {}).get(agent)
    if isinstance(entry, dict) and entry.get("provider") and entry.get("model"):
        return f"{entry['provider']}:{entry['model']}"
    return None


def bind_model(
    explicit: str | None = None,
    *,
    agent: str | None = None,
    db: dict[str, Any] | None = None,
    profiles: dict[str, Any] | None = None,
    allow_assumption: bool = True,
) -> ModelBinding:
    """Resolve the model for a money calculation through the binding cascade."""
    resolved_agent = detect_agent(agent)
    profiles = profiles if profiles is not None else load_agent_profiles()

    # 1. explicit CLI
    if explicit:
        price = resolve_model(explicit, db)
        if price is None:
            return ModelBinding(
                provider=explicit.split(":", 1)[0] if ":" in explicit else "",
                model=explicit.split(":", 1)[-1],
                source="explicit_cli", confidence="unknown", agent=resolved_agent, price=None,
                note="explicit --model could not be resolved in the price DB",
            )
        return ModelBinding(price.provider, price.model, "explicit_cli", "exact", resolved_agent, price)

    # 2. runtime self-report (hook/inject populates this from the transcript)
    runtime = os.environ.get(_RUNTIME_MODEL_VAR, "").strip()
    if runtime:
        price = resolve_model(runtime, db)
        if price is not None:
            return ModelBinding(price.provider, price.model, "detected_runtime", "exact", resolved_agent, price)

    # 3. env metadata
    for var, provider_hint in _ENV_MODEL_VARS:
        value = os.environ.get(var, "").strip()
        if not value:
            continue
        spec = value if (":" in value or not provider_hint) else f"{provider_hint}:{value}"
        price = resolve_model(spec, db)
        if price is not None:
            return ModelBinding(price.provider, price.model, "env_metadata", "inferred", resolved_agent, price)

    # 4. agent basic-assumption profile (runtime hid the model)
    if allow_assumption:
        spec = _assumption_spec(resolved_agent, profiles)
        if spec:
            price = resolve_model(spec, db)
            if price is not None:
                return ModelBinding(
                    price.provider, price.model,
                    "basic_assumption_due_hidden_runtime", "assumed", resolved_agent, price,
                    note=f"Runtime model was hidden by the host; used the default {resolved_agent} baseline profile.",
                    assumption_profile=resolved_agent,
                )

    # 5. unknown / unsupported
    return ModelBinding("", "", "unknown", "unknown", resolved_agent, None,
                        note="no model binding could be resolved")


def binding_error(binding: ModelBinding) -> dict[str, Any]:
    """The integration-bug diagnostic for a SUPPORTED agent with no binding.

    Per the owner: for a supported agent, a missing binding is not a user-config
    dead-end — it is an integration bug to be repaired (refresh inject/launcher/
    SessionStart binding). For an unsupported agent it is simply unsupported.
    """
    supported = binding.agent in SUPPORTED_AGENTS
    return {
        "ok": False,
        "error": "model_binding_missing",
        "classification": "integration_bug" if supported else "unsupported_agent",
        "agent": binding.agent,
        "fix": (
            "refresh the runtime inject / launcher / SessionStart model binding"
            if supported
            else "unsupported agent: pass --model provider:model explicitly"
        ),
    }


def model_detect_report(binding: ModelBinding) -> dict[str, Any]:
    """The ``money-saved model-detect`` command payload."""
    report: dict[str, Any] = {
        "schema_version": "money-saved-model-detect-v1",
        "agent": binding.agent,
        "available": binding.available,
        "model_binding": binding.as_dict(),
    }
    if binding.available and binding.price is not None:
        report["pricing_available"] = True
        report["status_in_price_db"] = binding.price.status
    else:
        report["pricing_available"] = False
        report["diagnostic"] = binding_error(binding)
    return report
