"""Money Saved tier surfaces (O064-MSM tier ladder, v0.6.4).

Privacy-safe, local-only paid-tier surfaces built ON TOP of the Registered Money
Saved export (``money_saved_meter.build_registered_export``, schema
``registered-export-v1``). The Registered export already carries ONLY safe
aggregates — exact gateway-call counts, measured bytes (when local artifacts
expose sizes), and token *estimates* with the estimation method preserved — and
never raw prompts/queries, skill bodies, filesystem paths, secrets, or
machine/install/account ids. These tier surfaces aggregate those safe aggregates
and add nothing the Registered export did not already contain.

Tier ladder (each stacks on the previous):

- Team (O064-MSM-TEAM-IMPL): local rollup over multiple Registered exports.

Dollars are disabled by default at every tier: the underlying meter never
configures a local price, so no tier may emit a dollar value. Every artifact is
run through the fail-closed ``assert_money_saved_safe`` gate before it is
returned or serialized, and incompatible/unsafe inputs are rejected rather than
silently aggregated.
"""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any

from . import __version__
from .money_saved_meter import (
    REGISTERED_EXPORT_SCHEMA_VERSION,
    assert_money_saved_meter_safe,
)


def now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def assert_money_saved_safe(value: Any) -> None:
    """Fail-closed privacy gate (same recursive contract as feedback reports)."""
    assert_money_saved_meter_safe(value)


class IncompatibleExportError(ValueError):
    """Raised when a tier input is not a compatible Money Saved export."""


def _content_hash(data: dict[str, Any]) -> str:
    payload = json.dumps(data, ensure_ascii=False, sort_keys=True).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _privacy() -> dict[str, bool]:
    return {
        "local_only": True,
        "upload": False,
        "hosted_telemetry": False,
        "raw_prompts_included": False,
        "raw_task_text_included": False,
        "skill_bodies_included": False,
        "local_absolute_paths_included": False,
        "tokens_keys_secrets_included": False,
        "customer_names_included": False,
        "private_repo_paths_included": False,
        "raw_mcp_payloads_included": False,
        "machine_id_included": False,
        "install_id_included": False,
        "account_id_included": False,
        "telemetry": False,
        "analytics": False,
    }


def _dollars_disabled() -> dict[str, Any]:
    return {
        "enabled": False,
        "configured_locally": False,
        "reason": "disabled_by_default_no_local_price_config",
        "claim": "dollars are disabled by default; tokens are estimates and never billing math",
    }


# --- Team tier (O064-MSM-TEAM-IMPL): local rollup of Registered exports ---------

MSM_TEAM_ROLLUP_SCHEMA_VERSION = "money-saved-team-rollup-v1"


def _measured_value(block: Any) -> int | None:
    """Return the int value of a measured/estimated sub-block iff it is available."""
    if not isinstance(block, dict) or not block.get("available"):
        return None
    value = block.get("value")
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return int(value)


def load_registered_export(path: Path) -> dict[str, Any]:
    """Load + validate one Registered Money Saved export (local file only)."""
    path = Path(path).expanduser()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise IncompatibleExportError(f"{path.name}: cannot read JSON ({exc.__class__.__name__}).") from exc
    if not isinstance(data, dict):
        raise IncompatibleExportError(f"{path.name}: export is not a JSON object.")
    if data.get("schema_version") != REGISTERED_EXPORT_SCHEMA_VERSION:
        raise IncompatibleExportError(
            f"{path.name}: incompatible schema_version "
            f"{data.get('schema_version')!r} (expected {REGISTERED_EXPORT_SCHEMA_VERSION!r})."
        )
    if data.get("export_type") != "money_saved_registered_export":
        raise IncompatibleExportError(
            f"{path.name}: not a Money Saved registered export (export_type={data.get('export_type')!r})."
        )
    try:
        assert_money_saved_safe(data)  # unsafe export is rejected before aggregation
    except RuntimeError as exc:
        raise IncompatibleExportError(f"{path.name}: unsafe export rejected ({exc}).") from exc
    return data


def _member_from_export(alias: str, data: dict[str, Any]) -> dict[str, Any]:
    body = data.get("body", {}) if isinstance(data.get("body"), dict) else {}
    window = body.get("window", {}) if isinstance(body.get("window"), dict) else {}
    measured = body.get("measured_bytes", {}) if isinstance(body.get("measured_bytes"), dict) else {}
    estimates = body.get("estimates", {}) if isinstance(body.get("estimates"), dict) else {}

    window_calls = window.get("window_call_count")
    window_calls = int(window_calls) if isinstance(window_calls, int) and not isinstance(window_calls, bool) else 0
    context_bytes = _measured_value(measured.get("context_bytes_avoided"))
    tokens_block = estimates.get("estimated_tokens_avoided") if isinstance(estimates.get("estimated_tokens_avoided"), dict) else {}
    est_tokens = _measured_value(tokens_block)
    method = tokens_block.get("method") if est_tokens is not None else None

    return {
        "alias": alias,
        # exact counts
        "window_call_count": window_calls,
        "is_complete_window": bool(window.get("is_complete_window", False)),
        # measured bytes (None when no local artifact exposed sizes)
        "measured_context_bytes_avoided": context_bytes,
        "measured_bytes_available": context_bytes is not None,
        # token estimate (method preserved)
        "estimated_tokens_avoided": est_tokens,
        "estimated_tokens_available": est_tokens is not None,
        "estimated_tokens_method": method,
    }


def build_money_saved_team_rollup(
    inputs: list[Path],
    *,
    aliases: list[str] | None = None,
    generated_at: str | None = None,
) -> dict[str, Any]:
    """Team-tier local rollup over multiple Registered Money Saved exports
    (O064-MSM-TEAM-IMPL).

    Inputs are local files gathered out of band; there is NO network fetch. Member
    aliases are local labels (operator-supplied or the input file stem) — never OS
    usernames or emails. Duplicate inputs are detected and counted once; an input
    with an incompatible schema or unsafe content is rejected via
    ``IncompatibleExportError``. Exact gateway-call counts and measured bytes are
    aggregated as facts; token *estimates* are aggregated with the estimation
    method preserved and never presented as exact. Dollars stay disabled by
    default. Fail-closed.
    """
    members: list[dict[str, Any]] = []
    duplicates: list[dict[str, Any]] = []
    seen: dict[str, str] = {}
    methods: set[str] = set()
    for index, raw in enumerate(inputs):
        path = Path(raw).expanduser()
        data = load_registered_export(path)
        alias = aliases[index] if aliases and index < len(aliases) and aliases[index] else path.stem
        digest = _content_hash(data)
        if digest in seen:
            duplicates.append({"alias": alias, "duplicate_of_alias": seen[digest]})
            continue
        seen[digest] = alias
        member = _member_from_export(alias, data)
        if member["estimated_tokens_method"]:
            methods.add(str(member["estimated_tokens_method"]))
        members.append(member)

    members_with_measured = [m for m in members if m["measured_bytes_available"]]
    members_with_estimate = [m for m in members if m["estimated_tokens_available"]]

    rollup: dict[str, Any] = {
        "schema_version": MSM_TEAM_ROLLUP_SCHEMA_VERSION,
        "report_type": "money_saved_team_rollup",
        "tier": "team",
        "export_profile": "team_local_rollup",
        "generated_at": generated_at or now_iso(),
        "source": "registered_money_saved_exports",
        "unlimited_skills_version": __version__,
        "member_count": len(members),
        "members": members,
        "exact_counts": {
            "team_window_call_count": sum(m["window_call_count"] for m in members),
            "complete_window_member_count": sum(1 for m in members if m["is_complete_window"]),
            "explanation": "Gateway-call counts are exact facts straight from each member's local meter.",
        },
        "measured_bytes": {
            "team_context_bytes_avoided": sum(m["measured_context_bytes_avoided"] for m in members_with_measured),
            "members_with_measured_bytes": len(members_with_measured),
            "members_without_measured_bytes": len(members) - len(members_with_measured),
            "explanation": "Measured bytes are summed only over members whose local artifacts exposed sizes.",
        },
        "estimates": {
            "team_estimated_tokens_avoided": sum(m["estimated_tokens_avoided"] for m in members_with_estimate),
            "members_with_estimated_tokens": len(members_with_estimate),
            "estimation_methods": sorted(methods),
            "measurement_kind": "estimated",
            "explanation": "Token totals are estimates (method preserved), never exact and never billing math.",
        },
        "dollars": _dollars_disabled(),
        "duplicate_inputs": duplicates,
        "privacy": {
            **_privacy(),
            "aliases_are_local_labels": True,
            "os_usernames_or_emails_included": False,
        },
        "claim_boundary": {
            "allowed_claims": [
                "Aggregates locally-gathered Registered Money Saved exports into a team view.",
                "All inputs are local files; nothing is fetched over a network.",
                "Bytes are measured when available; tokens are estimates; dollars are disabled by default.",
            ],
            "forbidden_claims": [
                "exact tokens saved",
                "exact money saved",
                "bill reduction guaranteed",
                "hosted team dashboard",
                "live team sync",
                "telemetry-backed team savings",
            ],
        },
        "delivery": {
            "produced_locally": True,
            "stays_local": True,
            "network_fetch": False,
            "hosted_sync": False,
            "upload": False,
            "dashboard": False,
            "note": "Inputs are gathered out of band; this rollup never fetches over a network.",
        },
    }
    assert_money_saved_safe(rollup)
    return rollup


def money_saved_team_rollup_json(rollup: dict[str, Any]) -> str:
    assert_money_saved_safe(rollup)
    return json.dumps(rollup, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


# --- Business tier (O064-MSM-BUSINESS-IMPL): admin CSV + JSON export ------------

MSM_ADMIN_EXPORT_SCHEMA_VERSION = "money-saved-admin-export-v1"
_UNLABELED = "unlabeled"
_ADMIN_CSV_COLUMNS = [
    "alias",
    "team",
    "workspace",
    "agent_class",
    "project",
    # measured facts
    "window_call_count",
    "measured_context_bytes_avoided",
    "measured_bytes_available",
    # estimate (never exact)
    "estimated_tokens_avoided",
    "estimated_tokens_available",
]


def load_team_rollup(path: Path) -> dict[str, Any]:
    """Load + validate one Team Money Saved rollup (local file only)."""
    path = Path(path).expanduser()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise IncompatibleExportError(f"{path.name}: cannot read JSON ({exc.__class__.__name__}).") from exc
    if not isinstance(data, dict):
        raise IncompatibleExportError(f"{path.name}: rollup is not a JSON object.")
    if data.get("schema_version") != MSM_TEAM_ROLLUP_SCHEMA_VERSION:
        raise IncompatibleExportError(
            f"{path.name}: incompatible schema_version "
            f"{data.get('schema_version')!r} (expected {MSM_TEAM_ROLLUP_SCHEMA_VERSION!r})."
        )
    try:
        assert_money_saved_safe(data)
    except RuntimeError as exc:
        raise IncompatibleExportError(f"{path.name}: unsafe rollup rejected ({exc}).") from exc
    return data


def _label_for(labels: dict[str, Any] | None, alias: str, key: str) -> str:
    if isinstance(labels, dict):
        entry = labels.get(alias)
        if isinstance(entry, dict):
            value = entry.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    return _UNLABELED


def _group_counts(rows: list[dict[str, Any]], key: str) -> dict[str, dict[str, int]]:
    groups: dict[str, dict[str, int]] = {}
    for row in rows:
        bucket = groups.setdefault(row[key], {"members": 0, "window_call_count": 0, "measured_context_bytes_avoided": 0})
        bucket["members"] += 1
        bucket["window_call_count"] += int(row["window_call_count"])
        if row["measured_bytes_available"]:
            bucket["measured_context_bytes_avoided"] += int(row["measured_context_bytes_avoided"] or 0)
    return groups


def build_money_saved_admin_export(
    rollup_path: Path,
    *,
    labels: dict[str, Any] | None = None,
    generated_at: str | None = None,
) -> dict[str, Any]:
    """Business-tier admin export over a Team Money Saved rollup
    (O064-MSM-BUSINESS-IMPL).

    Admin-supplied local labels (team/workspace/agent-class/project) group the
    members. Measured counts/bytes (facts) are kept separate from token estimates.
    Missing labels are handled safely (``unlabeled``). Dollars stay disabled by
    default. The CSV is rendered from the SAME rows as the JSON, so the two always
    agree. Local file; no hosted dashboard, billing, or telemetry. Fail-closed.
    """
    rollup = load_team_rollup(Path(rollup_path))
    members = rollup.get("members") if isinstance(rollup.get("members"), list) else []

    rows: list[dict[str, Any]] = []
    for member in members:
        if not isinstance(member, dict):
            continue
        alias = str(member.get("alias") or _UNLABELED)
        measured_available = bool(member.get("measured_bytes_available", False))
        est_available = bool(member.get("estimated_tokens_available", False))
        rows.append({
            "alias": alias,
            "team": _label_for(labels, alias, "team"),
            "workspace": _label_for(labels, alias, "workspace"),
            "agent_class": _label_for(labels, alias, "agent_class"),
            "project": _label_for(labels, alias, "project"),
            # measured facts
            "window_call_count": int(member.get("window_call_count", 0) or 0),
            "measured_context_bytes_avoided": int(member.get("measured_context_bytes_avoided") or 0) if measured_available else "",
            "measured_bytes_available": measured_available,
            # estimate (never exact)
            "estimated_tokens_avoided": int(member.get("estimated_tokens_avoided") or 0) if est_available else "",
            "estimated_tokens_available": est_available,
        })

    measured_rows = [r for r in rows if r["measured_bytes_available"]]
    est_rows = [r for r in rows if r["estimated_tokens_available"]]

    export: dict[str, Any] = {
        "schema_version": MSM_ADMIN_EXPORT_SCHEMA_VERSION,
        "report_type": "money_saved_admin_export",
        "tier": "business",
        "export_profile": "business_local_admin",
        "generated_at": generated_at or now_iso(),
        "source": "money_saved_team_rollup",
        "unlimited_skills_version": __version__,
        "csv_columns": list(_ADMIN_CSV_COLUMNS),
        "rows": rows,
        "measured": {
            "row_count": len(rows),
            "total_window_call_count": sum(int(r["window_call_count"]) for r in rows),
            "total_measured_context_bytes_avoided": sum(int(r["measured_context_bytes_avoided"] or 0) for r in measured_rows),
            "members_with_measured_bytes": len(measured_rows),
            "explanation": "Measured counts/bytes come straight from member meters; they are facts, not advice.",
        },
        "estimated": {
            "total_estimated_tokens_avoided": sum(int(r["estimated_tokens_avoided"] or 0) for r in est_rows),
            "members_with_estimated_tokens": len(est_rows),
            "measurement_kind": "estimated",
            "explanation": "Token totals are estimates, kept separate from measured facts; never exact, never billing math.",
        },
        "grouping": {
            "by_team": _group_counts(rows, "team"),
            "by_workspace": _group_counts(rows, "workspace"),
            "by_agent_class": _group_counts(rows, "agent_class"),
            "by_project": _group_counts(rows, "project"),
        },
        "dollars": _dollars_disabled(),
        "privacy": {
            **_privacy(),
            "labels_are_admin_supplied_local": True,
            "provider_account_ids_included": False,
        },
        "claim_boundary": {
            "allowed_claims": [
                "Local admin CSV/JSON view of Money Saved across labeled teams/workspaces/agent classes/projects.",
                "Measured counts/bytes are facts; tokens are estimates; dollars are disabled by default.",
            ],
            "forbidden_claims": [
                "exact tokens saved",
                "exact money saved",
                "bill reduction guaranteed",
                "hosted admin dashboard",
                "billing or entitlement",
                "telemetry-backed admin analytics",
            ],
        },
        "delivery": {
            "produced_locally": True,
            "stays_local": True,
            "upload": False,
            "hosted_dashboard": False,
            "billing_or_entitlement": False,
            "telemetry": False,
            "note": "Local CSV + JSON admin export; no hosted dashboard, billing, or telemetry.",
        },
    }
    assert_money_saved_safe(export)
    return export


def money_saved_admin_export_json(export: dict[str, Any]) -> str:
    assert_money_saved_safe(export)
    return json.dumps(export, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def money_saved_admin_export_csv(export: dict[str, Any]) -> str:
    """Render the admin export rows as CSV consistent with the JSON rows."""
    import csv
    import io

    assert_money_saved_safe(export)
    columns = export.get("csv_columns") or _ADMIN_CSV_COLUMNS
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=columns, extrasaction="ignore", lineterminator="\n")
    writer.writeheader()
    for row in export.get("rows", []):
        writer.writerow({col: row.get(col, "") for col in columns})
    return buffer.getvalue()


# --- Enterprise tier (O064-MSM-ENTERPRISE-IMPL): local evidence pack + verifier --

MSM_EVIDENCE_PACK_SCHEMA_VERSION = "money-saved-evidence-pack-v1"
MSM_EVIDENCE_VERIFICATION_SCHEMA_VERSION = "money-saved-evidence-pack-verification-v1"
_SCHEMA_CHAIN = [
    REGISTERED_EXPORT_SCHEMA_VERSION,
    MSM_TEAM_ROLLUP_SCHEMA_VERSION,
    MSM_ADMIN_EXPORT_SCHEMA_VERSION,
]


def load_admin_export(path: Path) -> dict[str, Any]:
    """Load + validate one Business admin export (local file only)."""
    path = Path(path).expanduser()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise IncompatibleExportError(f"{path.name}: cannot read JSON ({exc.__class__.__name__}).") from exc
    if not isinstance(data, dict):
        raise IncompatibleExportError(f"{path.name}: admin export is not a JSON object.")
    if data.get("schema_version") != MSM_ADMIN_EXPORT_SCHEMA_VERSION:
        raise IncompatibleExportError(
            f"{path.name}: incompatible schema_version "
            f"{data.get('schema_version')!r} (expected {MSM_ADMIN_EXPORT_SCHEMA_VERSION!r})."
        )
    try:
        assert_money_saved_safe(data)
    except RuntimeError as exc:
        raise IncompatibleExportError(f"{path.name}: unsafe admin export rejected ({exc}).") from exc
    return data


def _reproducibility_hash(admin_export: dict[str, Any]) -> str:
    """Stable for identical input data, independent of when it was generated."""
    stable = {k: v for k, v in admin_export.items() if k != "generated_at"}
    return _sha256_text(json.dumps(stable, ensure_ascii=False, sort_keys=True))


def build_money_saved_evidence_pack(
    admin_export_path: Path,
    *,
    input_filename: str | None = None,
    generated_at: str | None = None,
) -> dict[str, Any]:
    """Enterprise-tier local evidence pack over a Business admin export
    (O064-MSM-ENTERPRISE-IMPL).

    Produces a manifest plus method/assumptions, privacy, schema-version,
    measurement (measured-vs-estimated), claim-boundary, and reproducibility
    proofs, with a reproducibility hash that is stable for identical input data
    and content hashes over every pack file. Local only: no network, no egress.
    Makes no exact-money / exact-token / bill-reduction claim and no SSO/SCIM,
    hosted-governance, or signature-enforced claim. Fail-closed.
    """
    path = Path(admin_export_path)
    admin = load_admin_export(path)
    name = input_filename or path.name
    repro_hash = _reproducibility_hash(admin)

    measured = admin.get("measured", {}) if isinstance(admin.get("measured"), dict) else {}
    estimated = admin.get("estimated", {}) if isinstance(admin.get("estimated"), dict) else {}
    dollars = admin.get("dollars", {}) if isinstance(admin.get("dollars"), dict) else {}

    privacy_proof = {
        "privacy_block": admin.get("privacy", {}),
        "all_included_flags_false": all(
            value is False for key, value in admin.get("privacy", {}).items() if key.endswith("_included")
        ),
        "fail_closed_gate": "assert_money_saved_safe",
        "privacy_proof_passed": True,
    }
    schema_proof = {
        "input_schema_version": admin.get("schema_version"),
        "expected_input_schema_version": MSM_ADMIN_EXPORT_SCHEMA_VERSION,
        "schema_match": admin.get("schema_version") == MSM_ADMIN_EXPORT_SCHEMA_VERSION,
        "tier_schema_chain": list(_SCHEMA_CHAIN),
    }
    measurement_proof = {
        "row_count": int(measured.get("row_count", 0) or 0),
        "total_window_call_count": int(measured.get("total_window_call_count", 0) or 0),
        "total_measured_context_bytes_avoided": int(measured.get("total_measured_context_bytes_avoided", 0) or 0),
        "total_estimated_tokens_avoided": int(estimated.get("total_estimated_tokens_avoided", 0) or 0),
        "tokens_measurement_kind": estimated.get("measurement_kind"),
        "measured_and_estimated_are_separated": "estimated_tokens" not in measured and estimated.get("measurement_kind") == "estimated",
        "dollars_enabled": bool(dollars.get("enabled", False)),
    }
    claim_boundary_proof = {
        "claim_boundary": admin.get("claim_boundary", {}),
        "no_exact_money_claim": "exact money saved" in (admin.get("claim_boundary", {}) or {}).get("forbidden_claims", []),
        "no_exact_token_claim": "exact tokens saved" in (admin.get("claim_boundary", {}) or {}).get("forbidden_claims", []),
        "no_bill_reduction_claim": "bill reduction guaranteed" in (admin.get("claim_boundary", {}) or {}).get("forbidden_claims", []),
        "dollars_disabled_by_default": bool(dollars.get("enabled", False)) is False,
    }
    reproducibility_proof = {
        "reproducibility_hash": repro_hash,
        "method": "sha256 over the admin export with the volatile `generated_at` field removed",
        "stable_for_identical_input": True,
    }
    method_md = (
        "# Money Saved Enterprise Evidence Pack — Method & Assumptions\n\n"
        "## What is measured\n"
        "- Gateway-call counts and context bytes avoided come straight from member meters when local\n"
        "  artifacts expose sizes. They are facts.\n\n"
        "## What is estimated\n"
        "- Token totals are estimates (bytes divided by a fixed heuristic), kept separate from measured\n"
        "  facts. Dollars are disabled by default: the meter configures no local price.\n\n"
        "## Privacy boundary\n"
        "- Built only from aggregate Money Saved exports that never store raw prompts/queries, skill\n"
        "  bodies, filesystem paths, secrets, or machine/install/account ids. Every artifact passes the\n"
        "  fail-closed `assert_money_saved_safe` gate.\n\n"
        "## Reproducibility\n"
        f"- `reproducibility_hash` is `sha256` over the admin export with the volatile `generated_at`\n"
        "  field removed, so identical input data yields an identical hash regardless of generation time.\n\n"
        "## Explicit non-claims\n"
        "- No exact tokens saved, no exact money saved, no guaranteed bill reduction.\n"
        "- No data egress and no network access. No SSO/SCIM. No hosted governance. No enforced policy.\n"
        "- No cryptographic signature is produced or verified here (no signing code is invoked).\n"
    )
    source_inventory = [
        {
            "label": name,  # safe label only (basename) — never an absolute path
            "schema_version": admin.get("schema_version"),
            "row_count": int(measured.get("row_count", 0) or 0),
            "content_hash": repro_hash,
        }
    ]
    files = {
        "method-and-assumptions.md": method_md,
        "privacy-proof.json": json.dumps(privacy_proof, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        "schema-version-proof.json": json.dumps(schema_proof, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        "measurement-proof.json": json.dumps(measurement_proof, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        "claim-boundary-proof.json": json.dumps(claim_boundary_proof, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        "reproducibility-proof.json": json.dumps(reproducibility_proof, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
    }
    manifest = {
        "schema_version": MSM_EVIDENCE_PACK_SCHEMA_VERSION,
        "report_type": "money_saved_evidence_pack",
        "tier": "enterprise",
        "export_profile": "enterprise_local_evidence_pack",
        "generated_at": generated_at or now_iso(),
        "source": "money_saved_admin_export",
        "unlimited_skills_version": __version__,
        "reproducibility_hash": repro_hash,
        "source_inventory": source_inventory,
        "files": [
            {"name": fname, "content_hash": _sha256_text(content)} for fname, content in sorted(files.items())
        ],
        "dollars": _dollars_disabled(),
        "privacy": {
            **_privacy(),
            "no_egress": True,
            "network_access": False,
        },
        "non_claims": {
            "exact_money": False,
            "exact_tokens": False,
            "bill_reduction": False,
            "sso_scim": False,
            "hosted_governance": False,
            "enforced_policy": False,
            "signature_enforced": False,
        },
        "claim_boundary": {
            "allowed_claims": [
                "Local, reproducible evidence pack of Money Saved method, schema, measurement, claim boundary, and privacy.",
            ],
            "forbidden_claims": [
                "exact tokens saved",
                "exact money saved",
                "bill reduction guaranteed",
                "SSO or SCIM",
                "hosted governance",
                "enforced policy",
                "cryptographic signature enforced",
            ],
        },
    }
    assert_money_saved_safe(manifest)
    for proof in (privacy_proof, schema_proof, measurement_proof, claim_boundary_proof, reproducibility_proof):
        assert_money_saved_safe(proof)

    return {
        "manifest": manifest,
        "files": files,
        "reproducibility_hash": repro_hash,
        "privacy_proof": privacy_proof,
        "schema_proof": schema_proof,
        "measurement_proof": measurement_proof,
        "claim_boundary_proof": claim_boundary_proof,
        "reproducibility_proof": reproducibility_proof,
        "source_inventory": source_inventory,
    }


def validate_evidence_pack_manifest(manifest: dict[str, Any]) -> bool:
    """True iff the manifest has the required evidence-pack structure."""
    required = {
        "schema_version",
        "report_type",
        "reproducibility_hash",
        "source_inventory",
        "files",
        "non_claims",
    }
    if not required.issubset(manifest):
        return False
    if manifest.get("schema_version") != MSM_EVIDENCE_PACK_SCHEMA_VERSION:
        return False
    if not isinstance(manifest.get("files"), list) or not manifest["files"]:
        return False
    return all(isinstance(f, dict) and "name" in f and "content_hash" in f for f in manifest["files"])


def write_money_saved_evidence_pack(pack: dict[str, Any], out_dir: Path) -> list[str]:
    """Write the evidence pack into ``out_dir``; returns the written filenames."""
    out_dir = Path(out_dir).expanduser()
    out_dir.mkdir(parents=True, exist_ok=True)
    written: list[str] = []
    manifest_text = json.dumps(pack["manifest"], ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    (out_dir / "manifest.json").write_text(manifest_text, encoding="utf-8")
    written.append("manifest.json")
    for fname, content in sorted(pack["files"].items()):
        (out_dir / fname).write_text(content, encoding="utf-8")
        written.append(fname)
    return written


def verify_money_saved_evidence_pack(evidence_dir: Path) -> dict[str, Any]:
    """Independently verify a written Money Saved evidence pack
    (O064-MSM-ENTERPRISE-IMPL).

    Re-reads the pack from disk and proves it is a tamper-evident, local-only
    audit artifact: manifest schema, all files present, content hashes match the
    manifest, schema-version proof matches the Registered->Team->Business->
    Enterprise chain, privacy proof passes AND the fail-closed gate actually
    rejects unsafe input, measured-vs-estimated separation holds with dollars
    disabled, no exact-money/exact-token/bill-reduction claim, the reproducibility
    hash matches the source inventory, and the pack is local-only with no egress.
    Returns a structured report with ``ok`` and per-check results.
    """
    evidence_dir = Path(evidence_dir).expanduser()
    checks: list[dict[str, Any]] = []

    def add(name: str, ok: bool, detail: str = "") -> None:
        checks.append({"check": name, "ok": bool(ok), "detail": detail})

    def _load(fname: str) -> Any:
        p = evidence_dir / fname
        if not p.is_file():
            return None
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None

    manifest = _load("manifest.json")
    if not isinstance(manifest, dict):
        add("manifest_present", False, "manifest.json missing or unreadable")
        return {
            "schema_version": MSM_EVIDENCE_VERIFICATION_SCHEMA_VERSION,
            "ok": False,
            "evidence_dir_label": evidence_dir.name,
            "checks": checks,
        }
    add("manifest_present", True)
    add("manifest_schema", validate_evidence_pack_manifest(manifest), str(manifest.get("schema_version")))

    files_ok = True
    missing: list[str] = []
    bad_hash: list[str] = []
    for entry in manifest.get("files", []) or []:
        if not isinstance(entry, dict):
            files_ok = False
            continue
        fpath = evidence_dir / str(entry.get("name", ""))
        if not fpath.is_file():
            files_ok = False
            missing.append(str(entry.get("name")))
            continue
        if _sha256_text(fpath.read_text(encoding="utf-8")) != entry.get("content_hash"):
            files_ok = False
            bad_hash.append(str(entry.get("name")))
    add("files_exist_and_hashes_match", files_ok, f"missing={missing} bad_hash={bad_hash}")

    schema_proof = _load("schema-version-proof.json")
    add(
        "schema_version_proof_matches_chain",
        isinstance(schema_proof, dict)
        and schema_proof.get("schema_match") is True
        and schema_proof.get("tier_schema_chain") == _SCHEMA_CHAIN,
    )

    privacy_proof = _load("privacy-proof.json")
    privacy_ok = isinstance(privacy_proof, dict) and privacy_proof.get("all_included_flags_false") is True
    try:
        assert_money_saved_safe({"probe_local_absolute_paths_included": True})
        fail_closed_works = False
    except RuntimeError:
        fail_closed_works = True
    add("privacy_proof_passes_and_fail_closed_enforced", privacy_ok and fail_closed_works)

    measurement_proof = _load("measurement-proof.json")
    add(
        "measured_vs_estimated_proof_and_dollars_disabled",
        isinstance(measurement_proof, dict)
        and measurement_proof.get("measured_and_estimated_are_separated") is True
        and measurement_proof.get("dollars_enabled") is False,
    )

    claim_proof = _load("claim-boundary-proof.json")
    add(
        "no_exact_money_token_or_bill_reduction_claim",
        isinstance(claim_proof, dict)
        and claim_proof.get("no_exact_money_claim") is True
        and claim_proof.get("no_exact_token_claim") is True
        and claim_proof.get("no_bill_reduction_claim") is True
        and claim_proof.get("dollars_disabled_by_default") is True,
    )

    inventory = manifest.get("source_inventory", []) or []
    repro = manifest.get("reproducibility_hash")
    add(
        "reproducibility_hash_matches_inventory",
        bool(repro) and bool(inventory) and isinstance(inventory[0], dict) and inventory[0].get("content_hash") == repro,
    )

    privacy_block = manifest.get("privacy", {}) if isinstance(manifest.get("privacy"), dict) else {}
    add(
        "local_only_no_egress",
        privacy_block.get("no_egress") is True and privacy_block.get("network_access") is False and privacy_block.get("upload") is False,
    )

    ok = all(c["ok"] for c in checks)
    return {
        "schema_version": MSM_EVIDENCE_VERIFICATION_SCHEMA_VERSION,
        "ok": ok,
        "evidence_dir_label": evidence_dir.name,
        "checks": checks,
        "privacy": {"local_only": True, "upload": False, "network_access": False},
    }
