from __future__ import annotations

from pathlib import Path
from typing import Any

from .policy import load_policy, policy_summary
from .policy_sync import managed_policy_status


def redacted_enterprise_policy_summary(*, home: Path | None = None) -> dict[str, Any]:
    """Return policy state for diagnostics without policy bodies or local paths."""
    try:
        local_policy = policy_summary(load_policy(home))
    except Exception:
        local_policy = {"schema_version": 1, "installed": False, "locked": False, "mode": "unknown"}
    try:
        managed = managed_policy_status(home=home)
    except Exception:
        managed = {"schema_version": 1, "managed_state": {"managed": False}, "installed_policy": local_policy}
    return {
        "schema_version": 1,
        "mode": str(local_policy.get("mode") or "disabled"),
        "installed": bool(local_policy.get("installed")),
        "locked": bool(local_policy.get("locked")),
        "managed": bool(managed.get("managed_state", {}).get("managed")),
        "governance_summary_available": bool(local_policy.get("installed") or managed.get("managed_state", {}).get("managed")),
        "policy_ids_included": False,
        "policy_bodies_included": False,
        "local_paths_included": False,
    }
