from __future__ import annotations

from pathlib import Path
from typing import Any

from .private_pack_diagnostics import private_pack_setup_summary
from .registration import load_registration
from .service_diagnostics import configured_service_url, local_status


def build_setup_report(
    root: Path,
    *,
    registered: bool = False,
    hub: bool = False,
    private_packs: bool = False,
) -> dict[str, Any]:
    state = load_registration()
    service_url = configured_service_url(state)
    sections: dict[str, Any] = {
        "local_core": {
            "status": "ok",
            "registration_required": False,
            "root_present": root.exists(),
        }
    }
    if registered:
        status = local_status(refresh=False)
        sections["registered_service"] = {
            "status": "ok" if status["registration"]["registered"] else "warn",
            "registered": status["registration"]["registered"],
            "hosted_credential": status["registration"]["hosted_credential"],
            "service_config": status["service_config"],
        }
    if hub:
        sections["local_skill_hub"] = {
            "status": "info",
            "hosted_query_forwarding": False,
            "registration_required_for_hosted_sync": True,
        }
    if private_packs:
        sections["private_packs"] = private_pack_setup_summary(root, state=state, service_url=service_url)
    recommendations = []
    for section in sections.values():
        recommendations.extend(section.get("recommendations") or [])
    return {
        "schema_version": 1,
        "setup": {
            "registered": registered,
            "hub": hub,
            "private_packs": private_packs,
        },
        "sections": sections,
        "recommendations": recommendations,
        "privacy": {
            "uploads_local_data": False,
            "skill_bodies_included": False,
            "skill_names_included": False,
            "local_paths_included": False,
            "tokens_included": False,
        },
    }
