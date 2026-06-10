from __future__ import annotations

from pathlib import Path
from typing import Any

from .private_packs import private_pack_ref, read_private_pack_metadata
from .registration import RegistrationState, load_registration
from .signatures import key_record_allows, trusted_manifest_key_records


PRIVATE_PACK_ERROR_CODES = {
    "failed_signature",
    "sha_mismatch",
    "registry_access_denied",
    "service_unreachable",
    "trust_key_missing",
    "revoked",
    "stale_version",
    "unauthorized",
    "no_entitlement",
    "not_team_member",
    "wrong_agent",
    "wrong_channel",
    "policy_denied",
    "service_unavailable",
}


def private_pack_trust_status(service_url: str) -> dict[str, Any]:
    records = trusted_manifest_key_records()
    compatible = [
        str(record.get("key_id") or "")
        for record in records
        if key_record_allows(record, scope="private-team-pack", registry_url=service_url)
    ]
    return {
        "required_scope": "private-team-pack",
        "trusted_key_count": len(records),
        "compatible_key_count": len([item for item in compatible if item]),
        "compatible_key_ids": [item for item in compatible if item],
        "status": "ok" if compatible else "missing",
    }


def private_pack_local_summary(root: Path, *, include_pack_ids: bool = False) -> dict[str, Any]:
    metadata = read_private_pack_metadata(root)
    rows = metadata.get("items") if isinstance(metadata.get("items"), dict) else {}
    installed_count = 0
    missing_target_count = 0
    revoked_count = 0
    stale_count = 0
    failed_signature_count = 0
    sha_mismatch_count = 0
    access_denied_count = 0
    error_codes: set[str] = set()
    pack_refs: list[str] = []
    for pack_id, row in sorted(rows.items()):
        if not isinstance(row, dict):
            continue
        installed_count += 1
        target = str(row.get("target") or "")
        if not target or not (root / target).exists():
            missing_target_count += 1
        if row.get("revoked") is True:
            revoked_count += 1
            error_codes.add("revoked")
        if row.get("stale") is True or (row.get("latest_version") and row.get("latest_version") != row.get("version")):
            stale_count += 1
            error_codes.add("stale_version")
        last_error = str(row.get("last_error_code") or "")
        if last_error:
            error_codes.add(last_error if last_error in PRIVATE_PACK_ERROR_CODES else "unknown")
        if last_error == "failed_signature":
            failed_signature_count += 1
        if last_error == "sha_mismatch":
            sha_mismatch_count += 1
        if last_error in {"registry_access_denied", "unauthorized", "no_entitlement", "not_team_member", "wrong_agent", "wrong_channel", "policy_denied"}:
            access_denied_count += 1
        if include_pack_ids:
            pack_refs.append(_pack_ref(str(pack_id)))
    return {
        "schema_version": 1,
        "status": "ok" if not error_codes and not missing_target_count else "warn",
        "installed_count": installed_count,
        "authorized_count": "not_refreshed",
        "revoked_count": revoked_count,
        "stale_count": stale_count,
        "missing_target_count": missing_target_count,
        "failed_signature_count": failed_signature_count,
        "sha_mismatch_count": sha_mismatch_count,
        "access_denied_count": access_denied_count,
        "last_error_codes": sorted(error_codes),
        "pack_refs": pack_refs if include_pack_ids else [],
        "pack_names_included": False,
        "skill_names_included": False,
        "skill_bodies_included": False,
        "archive_urls_included": False,
        "local_paths_included": False,
    }


def private_pack_setup_summary(root: Path, *, state: RegistrationState | None = None, service_url: str = "") -> dict[str, Any]:
    state = state or load_registration()
    service_url = service_url or state.server_url
    local = private_pack_local_summary(root)
    trust = private_pack_trust_status(service_url) if service_url else {"status": "missing", "compatible_key_count": 0, "compatible_key_ids": []}
    checks = {
        "registered": bool(state.registered),
        "hosted_credential": "present" if state.license_token else "missing",
        "trust_key": trust["status"],
        "installed_count": local["installed_count"],
        "revoked_count": local["revoked_count"],
        "stale_count": local["stale_count"],
        "last_error_codes": local["last_error_codes"],
    }
    recommendations = []
    if not state.registered:
        recommendations.append("Register this installation before using hosted private team packs.")
    if trust["status"] != "ok":
        recommendations.append("Import or update a trusted manifest key with private-team-pack scope.")
    if local["revoked_count"]:
        recommendations.append("Remove or refresh revoked private team packs.")
    if local["stale_count"]:
        recommendations.append("Run private-packs sync after confirming registry access.")
    return {
        "schema_version": 1,
        "status": "ok" if state.registered and trust["status"] == "ok" and local["status"] == "ok" else "warn",
        "checks": checks,
        "local": local,
        "trust": trust,
        "recommendations": recommendations,
    }


def private_pack_doctor(root: Path, *, state: RegistrationState | None = None, service_url: str = "") -> dict[str, Any]:
    state = state or load_registration()
    setup = private_pack_setup_summary(root, state=state, service_url=service_url or state.server_url)
    payload = {
        "schema_version": 1,
        "status": setup["status"],
        "registered": state.registered,
        "plan": state.plan or ("registered-community" if state.registered else "community-core"),
        "setup": {
            "checks": setup["checks"],
            "trust": {
                "required_scope": setup["trust"].get("required_scope", "private-team-pack"),
                "status": setup["trust"].get("status", "missing"),
                "compatible_key_count": setup["trust"].get("compatible_key_count", 0),
            },
            "local": setup["local"],
        },
        "recommendations": setup["recommendations"],
        "network_calls": False,
        "privacy": {
            "skill_names_included": False,
            "skill_bodies_included": False,
            "private_pack_names_included": False,
            "archive_urls_included": False,
            "local_paths_included": False,
            "tokens_included": False,
            "proofs_included": False,
            "private_keys_included": False,
        },
    }
    assert_private_pack_diagnostics_safe(payload)
    return payload


def assert_private_pack_diagnostics_safe(payload: dict[str, Any]) -> None:
    serialized = str(payload).lower()
    forbidden = ["skill.md", "when to use", "authorization", "bearer ", "license_token", "device_private_key", "x-uls-proof", '"archive_url":']
    for marker in forbidden:
        if marker in serialized:
            raise RuntimeError(f"Private pack diagnostic output contains forbidden marker: {marker}")


def _pack_ref(pack_id: str) -> str:
    return private_pack_ref(pack_id)
