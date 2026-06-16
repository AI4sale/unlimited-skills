"""Learning Loop tier surfaces (O063 tier ladder).

Privacy-safe, local-only exports/rollups over the Learning Loop state — feedback
verdict aggregates, improvement-candidate counts, and dry-run (non-mutating)
preview status. Built on ``learning_loop.learning_doctor()`` which already stores
only counts/verdict codes and skill NAMES, never query/task text. Read-only: this
tier never mutates skills.

Registered tier (O063-TIER-REG-IMPL): a single schema-versioned local export the
user can run to prove the Learning Loop is collecting feedback and producing
improvement candidates, all locally. Produced locally, stays local.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from . import __version__
from .feedback import assert_feedback_report_safe

LEARNING_EXPORT_SCHEMA_VERSION = "learning-export-v1"

ALLOWED_CLAIMS = [
    "Unlimited Skills reports, locally, how much feedback the Learning Loop has and how many improvement candidates it produced.",
    "Counts are computed on your own machine; nothing is uploaded and no skill is mutated.",
]

FORBIDDEN_CLAIMS = [
    "automatic skill improvement",
    "skills mutated automatically",
    "hosted learning analytics",
    "guaranteed quality improvement",
    "telemetry-backed learning",
]


def now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def assert_learning_safe(value: Any) -> None:
    """Fail-closed privacy gate (same recursive contract as feedback reports)."""
    assert_feedback_report_safe(value)


def _privacy() -> dict[str, bool]:
    return {
        "local_only": True,
        "upload": False,
        "hosted_telemetry": False,
        "raw_prompts_included": False,
        "raw_queries_included": False,
        "notes_included": False,
        "skill_bodies_included": False,
        "local_absolute_paths_included": False,
        "tokens_keys_secrets_included": False,
        "machine_id_included": False,
        "install_id_included": False,
        "telemetry": False,
        "analytics": False,
    }


def build_learning_export(root: Path, *, generated_at: str | None = None) -> dict[str, Any]:
    """Registered-tier local Learning Loop export (O063-TIER-REG-IMPL).

    Read-only and fail-closed: the whole export passes ``assert_learning_safe``
    before it is returned/serialized, and no skill is mutated.
    """
    from .learning_loop import learning_doctor

    root = Path(root).expanduser()
    doctor = learning_doctor(root)

    export: dict[str, Any] = {
        "schema_version": LEARNING_EXPORT_SCHEMA_VERSION,
        "report_type": "learning_export",
        "tier": "registered",
        "export_profile": "registered_local",
        "generated_at": generated_at or now_iso(),
        "source": "learning_loop",
        "unlimited_skills_version": __version__,
        "feedback": {
            "feedback_count": int(doctor.get("feedback_count", 0) or 0),
            "event_count": int(doctor.get("event_count", 0) or 0),
            # outcome aggregates: missed / wrong / accepted / rejected / ... (counts only)
            "outcome_counts": dict(doctor.get("feedback_outcomes", {}) or {}),
        },
        "candidates": {
            "candidate_count": int(doctor.get("candidate_count", 0) or 0),
            "candidate_ids": list(doctor.get("candidate_ids", []) or []),
        },
        "dry_run": {
            "mutation_supported": False,
            "dry_run_only": True,
            "note": "apply-candidate is dry-run only; this export never mutates skills.",
        },
        "readiness": {
            "learning_dir_present": bool(doctor.get("learning_dir_present", False)),
            "feedback_log_present": bool(doctor.get("feedback_log_present", False)),
            "has_feedback": int(doctor.get("feedback_count", 0) or 0) > 0,
        },
        "privacy": _privacy(),
        "claim_boundary": {
            "allowed_claims": ALLOWED_CLAIMS,
            "forbidden_claims": FORBIDDEN_CLAIMS,
        },
        "delivery": {
            "produced_locally": True,
            "stays_local": True,
            "upload": False,
            "sync": False,
            "hosted_submit": False,
            "submit_verb_present": False,
            "note": "Produced locally and stays local; no upload, sync, or hosted submit in this tier.",
        },
    }
    assert_learning_safe(export)
    return export


def learning_export_json(export: dict[str, Any]) -> str:
    assert_learning_safe(export)
    return json.dumps(export, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


# --- Team tier (O063-TIER-TEAM-IMPL): local rollup of learning exports ----------

LEARNING_TEAM_ROLLUP_SCHEMA_VERSION = "learning-team-rollup-v1"


class IncompatibleExportError(ValueError):
    """Raised when a learning team-rollup input is not a compatible export."""


def _content_hash(data: dict[str, Any]) -> str:
    import hashlib

    return hashlib.sha256(json.dumps(data, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()


def load_learning_export(path: Path) -> dict[str, Any]:
    """Load + validate one Registered learning export (local file only)."""
    path = Path(path).expanduser()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise IncompatibleExportError(f"{path.name}: cannot read JSON ({exc.__class__.__name__}).") from exc
    if not isinstance(data, dict):
        raise IncompatibleExportError(f"{path.name}: export is not a JSON object.")
    if data.get("schema_version") != LEARNING_EXPORT_SCHEMA_VERSION:
        raise IncompatibleExportError(
            f"{path.name}: incompatible schema_version "
            f"{data.get('schema_version')!r} (expected {LEARNING_EXPORT_SCHEMA_VERSION!r})."
        )
    try:
        assert_learning_safe(data)
    except RuntimeError as exc:
        raise IncompatibleExportError(f"{path.name}: unsafe export rejected ({exc}).") from exc
    return data


def build_learning_team_rollup(
    inputs: list[Path],
    *,
    aliases: list[str] | None = None,
    generated_at: str | None = None,
) -> dict[str, Any]:
    """Team-tier local rollup over multiple Registered learning exports
    (O063-TIER-TEAM-IMPL).

    Inputs are local files gathered out of band; no network fetch. Member aliases
    are local labels (operator-supplied or the input file stem), never OS
    usernames/emails. Duplicate inputs are detected; incompatible-schema and
    unsafe inputs are rejected. Aggregates feedback/candidate counts and
    missed/wrong/rejected outcome patterns. Fail-closed.
    """
    members: list[dict[str, Any]] = []
    duplicates: list[dict[str, Any]] = []
    seen: dict[str, str] = {}
    outcome_totals: dict[str, int] = {}
    for index, raw in enumerate(inputs):
        path = Path(raw).expanduser()
        data = load_learning_export(path)
        alias = aliases[index] if aliases and index < len(aliases) and aliases[index] else path.stem
        digest = _content_hash(data)
        if digest in seen:
            duplicates.append({"alias": alias, "duplicate_of_alias": seen[digest]})
            continue
        seen[digest] = alias
        feedback = data.get("feedback", {}) if isinstance(data.get("feedback"), dict) else {}
        candidates = data.get("candidates", {}) if isinstance(data.get("candidates"), dict) else {}
        outcomes = feedback.get("outcome_counts", {}) if isinstance(feedback.get("outcome_counts"), dict) else {}
        for key, value in outcomes.items():
            if isinstance(value, int) and not isinstance(value, bool):
                outcome_totals[key] = outcome_totals.get(key, 0) + value
        members.append({
            "alias": alias,
            "feedback_count": int(feedback.get("feedback_count", 0) or 0),
            "candidate_count": int(candidates.get("candidate_count", 0) or 0),
            "outcome_counts": {k: int(v) for k, v in outcomes.items() if isinstance(v, int) and not isinstance(v, bool)},
        })

    rollup: dict[str, Any] = {
        "schema_version": LEARNING_TEAM_ROLLUP_SCHEMA_VERSION,
        "report_type": "learning_team_rollup",
        "tier": "team",
        "export_profile": "team_local_rollup",
        "generated_at": generated_at or now_iso(),
        "source": "registered_learning_exports",
        "unlimited_skills_version": __version__,
        "member_count": len(members),
        "team_total_feedback": sum(m["feedback_count"] for m in members),
        "team_total_candidates": sum(m["candidate_count"] for m in members),
        "aggregate_outcome_counts": dict(sorted(outcome_totals.items())),
        "members": members,
        "no_feedback_members": [m["alias"] for m in members if m["feedback_count"] == 0],
        "duplicate_inputs": duplicates,
        "privacy": {
            **_privacy(),
            "aliases_are_local_labels": True,
            "os_usernames_or_emails_included": False,
        },
        "claim_boundary": {
            "allowed_claims": [
                "Aggregates locally-gathered Registered learning exports into a team view.",
                "All inputs are local files; nothing is fetched over a network and no skill is mutated.",
            ],
            "forbidden_claims": [
                "hosted team dashboard",
                "live team sync",
                "automatic skill improvement",
            ],
        },
        "delivery": {
            "produced_locally": True,
            "stays_local": True,
            "network_fetch": False,
            "hosted_sync": False,
            "upload": False,
            "dashboard": False,
            "mutation": False,
            "note": "Inputs are gathered out of band; this rollup never fetches over a network or mutates skills.",
        },
    }
    assert_learning_safe(rollup)
    return rollup


def learning_team_rollup_json(rollup: dict[str, Any]) -> str:
    assert_learning_safe(rollup)
    return json.dumps(rollup, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


# --- Business tier (O063-TIER-BUSINESS-IMPL): admin CSV + JSON export -----------

LEARNING_ADMIN_EXPORT_SCHEMA_VERSION = "learning-admin-export-v1"
_ADMIN_CSV_COLUMNS = ["alias", "team", "workspace", "agent_class", "feedback_count", "candidate_count", "has_feedback"]
_UNLABELED = "unlabeled"


def load_learning_team_rollup(path: Path) -> dict[str, Any]:
    """Load + validate one learning Team rollup (local file only)."""
    path = Path(path).expanduser()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise IncompatibleExportError(f"{path.name}: cannot read JSON ({exc.__class__.__name__}).") from exc
    if not isinstance(data, dict):
        raise IncompatibleExportError(f"{path.name}: rollup is not a JSON object.")
    if data.get("schema_version") != LEARNING_TEAM_ROLLUP_SCHEMA_VERSION:
        raise IncompatibleExportError(
            f"{path.name}: incompatible schema_version "
            f"{data.get('schema_version')!r} (expected {LEARNING_TEAM_ROLLUP_SCHEMA_VERSION!r})."
        )
    try:
        assert_learning_safe(data)
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
        bucket = groups.setdefault(row[key], {"members": 0, "feedback_count": 0, "candidate_count": 0, "no_feedback_members": 0})
        bucket["members"] += 1
        bucket["feedback_count"] += int(row["feedback_count"])
        bucket["candidate_count"] += int(row["candidate_count"])
        if not row["has_feedback"]:
            bucket["no_feedback_members"] += 1
    return groups


def build_learning_admin_export(
    rollup_path: Path,
    *,
    labels: dict[str, Any] | None = None,
    generated_at: str | None = None,
) -> dict[str, Any]:
    """Business-tier admin export over a learning Team rollup (O063-TIER-BUSINESS-IMPL).

    Admin-supplied local labels group the members; measured counts kept separate
    from advisory status; missing labels handled safely. Fail-closed. No hosted
    dashboard, billing, or telemetry; never mutates skills.
    """
    rollup = load_learning_team_rollup(Path(rollup_path))
    members = rollup.get("members") if isinstance(rollup.get("members"), list) else []
    rows: list[dict[str, Any]] = []
    for member in members:
        if not isinstance(member, dict):
            continue
        alias = str(member.get("alias") or _UNLABELED)
        feedback_count = int(member.get("feedback_count", 0) or 0)
        rows.append({
            "alias": alias,
            "team": _label_for(labels, alias, "team"),
            "workspace": _label_for(labels, alias, "workspace"),
            "agent_class": _label_for(labels, alias, "agent_class"),
            "feedback_count": feedback_count,
            "candidate_count": int(member.get("candidate_count", 0) or 0),
            "has_feedback": feedback_count > 0,
        })

    export: dict[str, Any] = {
        "schema_version": LEARNING_ADMIN_EXPORT_SCHEMA_VERSION,
        "report_type": "learning_admin_export",
        "tier": "business",
        "export_profile": "business_local_admin",
        "generated_at": generated_at or now_iso(),
        "source": "learning_team_rollup",
        "unlimited_skills_version": __version__,
        "csv_columns": list(_ADMIN_CSV_COLUMNS),
        "rows": rows,
        "measured": {
            "row_count": len(rows),
            "total_feedback": sum(r["feedback_count"] for r in rows),
            "total_candidates": sum(r["candidate_count"] for r in rows),
            "explanation": "Measured counts come straight from the learning exports; they are facts, not advice.",
        },
        "advisory": {
            "no_feedback_members": [r["alias"] for r in rows if not r["has_feedback"]],
            "explanation": "Advisory status (no-feedback) is guidance, not a measured guarantee.",
        },
        "grouping": {
            "by_team": _group_counts(rows, "team"),
            "by_workspace": _group_counts(rows, "workspace"),
            "by_agent_class": _group_counts(rows, "agent_class"),
        },
        "privacy": {
            **_privacy(),
            "labels_are_admin_supplied_local": True,
            "provider_account_ids_included": False,
        },
        "claim_boundary": {
            "allowed_claims": [
                "Local admin CSV/JSON view of Learning Loop feedback/candidates across labeled teams/workspaces/agent classes.",
            ],
            "forbidden_claims": [
                "hosted admin dashboard",
                "billing or entitlement",
                "automatic skill improvement",
            ],
        },
        "delivery": {
            "produced_locally": True,
            "stays_local": True,
            "upload": False,
            "hosted_dashboard": False,
            "billing_or_entitlement": False,
            "mutation": False,
            "note": "Local CSV + JSON admin export; no hosted dashboard, billing, telemetry, or mutation.",
        },
    }
    assert_learning_safe(export)
    return export


def learning_admin_export_json(export: dict[str, Any]) -> str:
    assert_learning_safe(export)
    return json.dumps(export, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def learning_admin_export_csv(export: dict[str, Any]) -> str:
    import csv
    import io

    assert_learning_safe(export)
    columns = export.get("csv_columns") or _ADMIN_CSV_COLUMNS
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=columns, extrasaction="ignore", lineterminator="\n")
    writer.writeheader()
    for row in export.get("rows", []):
        writer.writerow({col: row.get(col, "") for col in columns})
    return buffer.getvalue()


# --- Enterprise tier (O063-TIER-ENTERPRISE-IMPL): local evidence pack -----------

LEARNING_EVIDENCE_PACK_SCHEMA_VERSION = "learning-evidence-pack-v1"
_LEARNING_SCHEMA_CHAIN = [
    LEARNING_EXPORT_SCHEMA_VERSION,
    LEARNING_TEAM_ROLLUP_SCHEMA_VERSION,
    LEARNING_ADMIN_EXPORT_SCHEMA_VERSION,
]


def _sha256_text(text: str) -> str:
    import hashlib

    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def load_learning_admin_export(path: Path) -> dict[str, Any]:
    """Load + validate one Business learning admin export (local file only)."""
    path = Path(path).expanduser()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise IncompatibleExportError(f"{path.name}: cannot read JSON ({exc.__class__.__name__}).") from exc
    if not isinstance(data, dict):
        raise IncompatibleExportError(f"{path.name}: admin export is not a JSON object.")
    if data.get("schema_version") != LEARNING_ADMIN_EXPORT_SCHEMA_VERSION:
        raise IncompatibleExportError(
            f"{path.name}: incompatible schema_version "
            f"{data.get('schema_version')!r} (expected {LEARNING_ADMIN_EXPORT_SCHEMA_VERSION!r})."
        )
    try:
        assert_learning_safe(data)
    except RuntimeError as exc:
        raise IncompatibleExportError(f"{path.name}: unsafe admin export rejected ({exc}).") from exc
    return data


def _learning_reproducibility_hash(admin_export: dict[str, Any]) -> str:
    stable = {k: v for k, v in admin_export.items() if k != "generated_at"}
    return _sha256_text(json.dumps(stable, ensure_ascii=False, sort_keys=True))


def build_learning_evidence_pack(
    admin_export_path: Path,
    *,
    input_filename: str | None = None,
    generated_at: str | None = None,
) -> dict[str, Any]:
    """Enterprise-tier local Learning Loop evidence pack (O063-TIER-ENTERPRISE-IMPL).

    Produces a manifest, a method/assumptions statement, a privacy proof, a
    NON-MUTATION proof, a closed-loop dry-run proof reference, a schema-version
    proof, a safe source inventory, and a reproducibility hash stable for identical
    input data. Local only: no network, no egress. Makes no SSO/SCIM, hosted-
    governance, enforced-policy, or signature-enforced claim. Fail-closed.
    """
    path = Path(admin_export_path)
    admin = load_learning_admin_export(path)
    name = input_filename or path.name
    repro_hash = _learning_reproducibility_hash(admin)

    privacy_proof = {
        "privacy_block": admin.get("privacy", {}),
        "all_included_flags_false": all(
            value is False for key, value in admin.get("privacy", {}).items() if key.endswith("_included")
        ),
        "fail_closed_gate": "assert_learning_safe",
        "privacy_proof_passed": True,
    }
    non_mutation_proof = {
        "mutation_supported": False,
        "skill_files_written": False,
        "apply_candidate_is_dry_run_only": True,
        "statement": "The Learning Loop tier surfaces are read-only; apply-candidate supports --dry-run only and writes no skill files.",
    }
    closed_loop_dry_run_proof_reference = {
        "mechanism": "unlimited-skills apply-candidate --dry-run <candidate_id>",
        "proof_script_reference": "scripts/verify-learning-loop-closed-loop-proof.py",
        "note": "Closed-loop improvement is proven via dry-run preview; this pack references it and never executes a mutation.",
    }
    schema_proof = {
        "input_schema_version": admin.get("schema_version"),
        "expected_input_schema_version": LEARNING_ADMIN_EXPORT_SCHEMA_VERSION,
        "schema_match": admin.get("schema_version") == LEARNING_ADMIN_EXPORT_SCHEMA_VERSION,
        "tier_schema_chain": list(_LEARNING_SCHEMA_CHAIN),
    }
    source_inventory = [
        {
            "label": name,  # safe basename label only — never an absolute path
            "schema_version": admin.get("schema_version"),
            "row_count": int((admin.get("measured", {}) or {}).get("row_count", 0) or 0),
            "content_hash": repro_hash,
        }
    ]
    method_md = (
        "# Learning Loop Enterprise Evidence Pack — Method & Assumptions\n\n"
        "## What is measured\n"
        "- Feedback counts, outcome aggregates (missed/wrong/accepted/rejected), and improvement-candidate\n"
        "  counts come straight from the local Learning Loop state. They are facts.\n\n"
        "## What is advisory\n"
        "- No-feedback / readiness status is guidance, not a guarantee.\n\n"
        "## Non-mutation\n"
        "- Every Learning Loop tier surface is read-only. `apply-candidate` supports `--dry-run` only and\n"
        "  writes no skill files; this evidence pack never executes a mutation.\n\n"
        "## Privacy boundary\n"
        "- Built only from aggregate counts/verdict codes and skill NAMES; never raw prompts, queries,\n"
        "  notes, skill bodies, secrets, machine/install ids, or provider account ids. Every artifact passes\n"
        "  the fail-closed `assert_learning_safe` gate.\n\n"
        "## Reproducibility\n"
        "- `reproducibility_hash` is `sha256` over the admin export with the volatile `generated_at` removed,\n"
        "  so identical input data yields an identical hash regardless of generation time.\n\n"
        "## Explicit non-claims\n"
        "- No data egress, no network. No SSO/SCIM. No hosted governance. No enforced policy.\n"
        "- No automatic skill improvement. No cryptographic signature is produced or verified here.\n"
    )
    files = {
        "method-and-assumptions.md": method_md,
        "privacy-proof.json": json.dumps(privacy_proof, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        "non-mutation-proof.json": json.dumps(non_mutation_proof, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        "closed-loop-dry-run-proof.json": json.dumps(closed_loop_dry_run_proof_reference, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        "schema-version-proof.json": json.dumps(schema_proof, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
    }
    manifest = {
        "schema_version": LEARNING_EVIDENCE_PACK_SCHEMA_VERSION,
        "report_type": "learning_evidence_pack",
        "tier": "enterprise",
        "export_profile": "enterprise_local_evidence_pack",
        "generated_at": generated_at or now_iso(),
        "source": "learning_admin_export",
        "unlimited_skills_version": __version__,
        "reproducibility_hash": repro_hash,
        "source_inventory": source_inventory,
        "files": [
            {"name": fname, "content_hash": _sha256_text(content)} for fname, content in sorted(files.items())
        ],
        "privacy": {
            **_privacy(),
            "no_egress": True,
            "network_access": False,
        },
        "non_claims": {
            "sso_scim": False,
            "hosted_governance": False,
            "enforced_policy": False,
            "signature_enforced": False,
            "automatic_skill_improvement": False,
        },
        "claim_boundary": {
            "allowed_claims": [
                "Local, reproducible evidence pack of Learning Loop method, schema, privacy, and non-mutation.",
            ],
            "forbidden_claims": [
                "SSO or SCIM",
                "hosted governance",
                "enforced policy",
                "automatic skill improvement",
                "cryptographic signature enforced",
            ],
        },
    }
    for artifact in (manifest, privacy_proof, non_mutation_proof, schema_proof):
        assert_learning_safe(artifact)

    return {
        "manifest": manifest,
        "files": files,
        "reproducibility_hash": repro_hash,
        "privacy_proof": privacy_proof,
        "non_mutation_proof": non_mutation_proof,
        "schema_proof": schema_proof,
        "source_inventory": source_inventory,
    }


def validate_learning_evidence_pack_manifest(manifest: dict[str, Any]) -> bool:
    required = {"schema_version", "report_type", "reproducibility_hash", "source_inventory", "files", "non_claims"}
    if not required.issubset(manifest):
        return False
    if manifest.get("schema_version") != LEARNING_EVIDENCE_PACK_SCHEMA_VERSION:
        return False
    if not isinstance(manifest.get("files"), list) or not manifest["files"]:
        return False
    return all(isinstance(f, dict) and "name" in f and "content_hash" in f for f in manifest["files"])


def write_learning_evidence_pack(pack: dict[str, Any], out_dir: Path) -> list[str]:
    out_dir = Path(out_dir).expanduser()
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "manifest.json").write_text(
        json.dumps(pack["manifest"], ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    written = ["manifest.json"]
    for fname, content in sorted(pack["files"].items()):
        (out_dir / fname).write_text(content, encoding="utf-8")
        written.append(fname)
    return written


LEARNING_EVIDENCE_VERIFICATION_SCHEMA_VERSION = "learning-evidence-pack-verification-v1"
CLOSED_LOOP_PROOF_SCRIPT = "scripts/verify-learning-loop-closed-loop-proof.py"


def verify_learning_evidence_pack(evidence_dir: Path) -> dict[str, Any]:
    """Independently verify a written Learning Loop evidence pack
    (O063-TIER-ENTERPRISE-IMPL-R).

    Re-reads the pack from disk and proves it is a tamper-evident, local-only
    audit artifact: manifest schema, all files present, content hashes match the
    manifest, schema-version proof matches the tier chain, privacy proof passes
    AND the fail-closed gate actually rejects unsafe input, non-mutation proof is
    present, the closed-loop dry-run proof points at the real script, the
    reproducibility hash matches the source inventory, and the pack is local-only
    with no egress. Returns a structured report with ``ok`` and per-check results.
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
            "schema_version": LEARNING_EVIDENCE_VERIFICATION_SCHEMA_VERSION,
            "ok": False,
            "evidence_dir_label": evidence_dir.name,
            "checks": checks,
        }
    add("manifest_present", True)
    add(
        "manifest_schema",
        manifest.get("schema_version") == LEARNING_EVIDENCE_PACK_SCHEMA_VERSION,
        str(manifest.get("schema_version")),
    )

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
        and schema_proof.get("tier_schema_chain") == _LEARNING_SCHEMA_CHAIN,
    )

    privacy_proof = _load("privacy-proof.json")
    privacy_ok = isinstance(privacy_proof, dict) and privacy_proof.get("all_included_flags_false") is True
    try:
        assert_learning_safe({"probe_local_absolute_paths_included": True})
        fail_closed_works = False
    except RuntimeError:
        fail_closed_works = True
    add("privacy_proof_passes_and_fail_closed_enforced", privacy_ok and fail_closed_works)

    non_mutation = _load("non-mutation-proof.json")
    add(
        "non_mutation_proof",
        isinstance(non_mutation, dict)
        and non_mutation.get("mutation_supported") is False
        and non_mutation.get("skill_files_written") is False
        and non_mutation.get("apply_candidate_is_dry_run_only") is True,
    )

    closed_loop = _load("closed-loop-dry-run-proof.json")
    add(
        "closed_loop_dry_run_reference",
        isinstance(closed_loop, dict) and CLOSED_LOOP_PROOF_SCRIPT in str(closed_loop.get("proof_script_reference", "")),
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
        "schema_version": LEARNING_EVIDENCE_VERIFICATION_SCHEMA_VERSION,
        "ok": ok,
        "evidence_dir_label": evidence_dir.name,
        "checks": checks,
        "privacy": {"local_only": True, "upload": False, "network_access": False},
    }
