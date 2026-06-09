from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from . import __version__
from .private_pack_diagnostics import assert_private_pack_diagnostics_safe, private_pack_local_summary, private_pack_setup_summary
from .registration import load_registration
from .service_diagnostics import configured_service_url


def build_support_bundle_manifest(root: Path, *, include_private_pack_refs: bool = False) -> dict[str, Any]:
    state = load_registration()
    service_url = configured_service_url(state)
    private_packs = private_pack_local_summary(root, include_pack_ids=include_private_pack_refs)
    setup = private_pack_setup_summary(root, state=state, service_url=service_url)
    payload = {
        "schema_version": 1,
        "client": {"name": "unlimited-skills", "version": __version__},
        "registration": {
            "registered": state.registered,
            "plan": state.plan or ("registered-community" if state.registered else "community-core"),
            "hosted_credential": "present" if state.license_token else "missing",
            "device_key": "present" if state.device_private_key else "missing",
        },
        "private_packs": private_packs,
        "private_pack_setup": {
            "status": setup["status"],
            "checks": setup["checks"],
            "recommendation_count": len(setup["recommendations"]),
        },
        "privacy": {
            "uploaded": False,
            "skill_bodies_included": False,
            "skill_names_included": False,
            "private_pack_names_included": include_private_pack_refs,
            "archive_urls_included": False,
            "local_paths_included": False,
            "tokens_included": False,
            "proofs_included": False,
            "private_keys_included": False,
        },
    }
    assert_support_bundle_safe(payload)
    return payload


def assert_support_bundle_safe(payload: dict[str, Any]) -> None:
    assert_private_pack_diagnostics_safe(payload)
    serialized = json.dumps(payload, ensure_ascii=False).lower()
    forbidden = ["skill.md", "when to use", "authorization", "bearer ", "license_token", "device_private_key", "x-uls-proof", '"archive_url":', "c:\\", "/users/"]
    for marker in forbidden:
        if marker in serialized:
            raise RuntimeError(f"Support bundle contains forbidden marker: {marker}")
