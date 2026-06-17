"""Enterprise evidence pack + verifier (O064-R2-07).

``evidence-pack`` turns a Business admin export (``money-saved-admin-export-v2``)
into a self-contained, independently checkable proof bundle. ``verify-evidence-pack``
RECOMPUTES the money from first principles and fails (exit 1) on any tamper.

The pack is 13 files:

    manifest.json                # file list + per-file sha256 + pack sha256
    method-and-assumptions.md    # human-readable method + assumptions
    privacy-proof.json           # what left the machine (token_count_privacy)
    schema-version-proof.json     # money_model_version + schema lineage
    model-binding-proof.json      # per-row provider/model/source
    pricing-proof.json            # per-row currency/price_class/price_per_1m + source
    skills-savings-proof.json     # per-row skills tokens + money
    mcp-savings-proof.json        # per-row mcp tokens + money
    event-count-proof.json        # event scaling note + per-row total tokens
    cache-pricing-proof.json      # per-row price_class + cache-class multipliers
    money-formula-proof.json      # canonical recompute rows + the formula
    claim-boundary-proof.json     # allowed/forbidden claims
    reproducibility-proof.json    # input hash + recompute recipe

Verification is two independent layers:

1. **Integrity** — recompute the sha256 of every listed file; any mismatch is
   tamper (catches edits to ANY proof: model, price, tokens, money, claim, …).
2. **Semantic recompute** — for every money-formula row, re-resolve the price from
   the live price DB by (provider, model, price_class) and recompute
   ``money = tokens / 1e6 * price``; any disagreement with the stored figure is
   tamper. This catches a model/price swap even if the manifest were regenerated.

Exit codes: ``0`` valid, ``1`` tampered, ``2`` bad input.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from .money_events import MONEY_MODEL_VERSION
from .money_pricing import PRICE_DB_SCHEMA_VERSION, money_for_tokens, price_per_1m, resolve_model
from .money_saved_meter_v2 import claim_boundary

EVIDENCE_PACK_SCHEMA = "money-saved-evidence-pack-v1"
VERIFICATION_SCHEMA = "money-saved-evidence-pack-verification-v1"
MONEY_FORMULA = "estimated_money_saved_usd = total_tokens_saved / 1_000_000 * price_per_1m_input_tokens"
ADMIN_EXPORT_V2_SCHEMA = "money-saved-admin-export-v2"

PROOF_FILES = (
    "method-and-assumptions.md",
    "privacy-proof.json",
    "schema-version-proof.json",
    "model-binding-proof.json",
    "pricing-proof.json",
    "skills-savings-proof.json",
    "mcp-savings-proof.json",
    "event-count-proof.json",
    "cache-pricing-proof.json",
    "money-formula-proof.json",
    "claim-boundary-proof.json",
    "reproducibility-proof.json",
)
# manifest.json + the 12 entries above = 13 files total.

_MONEY_TOLERANCE = 1e-9


class EvidenceInputError(ValueError):
    """The input is not a valid admin export / evidence pack (exit 2)."""


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _json_text(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def _rows(admin_export: dict[str, Any]) -> list[dict[str, Any]]:
    rows = admin_export.get("rows")
    if not isinstance(rows, list):
        raise EvidenceInputError("admin export has no rows")
    return rows


def _method_md(admin_export: dict[str, Any]) -> str:
    return (
        "# Money Saved — Method and Assumptions\n\n"
        f"money_model_version: {admin_export.get('money_model_version', MONEY_MODEL_VERSION)}\n\n"
        "## What is measured\n"
        "- Skills baseline: the Level-1 (name + description) descriptor of every visible skill, "
        "collapsed by the router to a single descriptor.\n"
        "- MCP baseline: the full upstream tools/list of all configured servers, collapsed by the "
        "gateway to 3 meta-tools.\n"
        "- Tokens are counted with the model's own counter (Anthropic count_tokens for Claude); "
        "the byte heuristic is not release-acceptable.\n\n"
        "## Money\n"
        f"- {MONEY_FORMULA}\n"
        "- Prices come from the published provider pricing snapshot in the in-package price DB.\n"
        "- Money is API-equivalent (applies even on a subscription, which still consumes limits). "
        "It is NOT a provider-invoice reconciliation and NOT a guaranteed bill reduction.\n\n"
        "## Assumptions\n"
        "- When the runtime hides the live model, the agent's documented baseline profile is used "
        "and the row is marked assumed.\n"
        "- Cache price class defaults to cache_write_5m for standing-context re-writes "
        "(compaction etc.); first session with no warm cache uses base_input.\n"
    )


def _privacy_proof() -> dict[str, Any]:
    return {
        "schema_version": "money-saved-privacy-proof-v1",
        "token_count_privacy": {
            "sent_material": "level1_skill_descriptions_and_mcp_tool_schemas",
            "raw_prompts_sent": False,
            "skill_bodies_sent": False,
            "requires_provider_api": True,
        },
        "evidence_pack_contains": {
            "raw_prompts": False, "raw_task_text": False, "skill_bodies": False,
            "local_absolute_paths": False, "install_or_machine_or_account_id": False,
            "mcp_schema_contents": False, "tokens_keys_secrets": False,
        },
    }


def _money_formula_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    for row in rows:
        out.append({
            "alias": row.get("alias"),
            "provider": row.get("provider"),
            "model": row.get("model"),
            "currency": row.get("currency"),
            "price_class": row.get("price_class"),
            "price_per_1m_input_tokens": row.get("price_per_1m_input_tokens"),
            "skills_tokens_saved": row.get("skills_tokens_saved"),
            "mcp_tokens_saved": row.get("mcp_tokens_saved"),
            "total_tokens_saved": row.get("total_tokens_saved"),
            "skills_estimated_money_saved_usd": row.get("skills_estimated_money_saved_usd"),
            "mcp_estimated_money_saved_usd": row.get("mcp_estimated_money_saved_usd"),
            "total_estimated_money_saved_usd": row.get("total_estimated_money_saved_usd"),
        })
    return out


def build_evidence_pack_files(admin_export: dict[str, Any], *, generated_at: str | None = None) -> dict[str, str]:
    """Return ``{filename: text}`` for all 13 evidence-pack files."""
    if admin_export.get("schema_version") != ADMIN_EXPORT_V2_SCHEMA:
        raise EvidenceInputError(f"evidence pack requires a {ADMIN_EXPORT_V2_SCHEMA}")
    rows = _rows(admin_export)
    admin_text = _json_text(admin_export)
    admin_sha = _sha256_text(admin_text)

    proofs: dict[str, str] = {}
    proofs["method-and-assumptions.md"] = _method_md(admin_export)
    proofs["privacy-proof.json"] = _json_text(_privacy_proof())
    proofs["schema-version-proof.json"] = _json_text({
        "schema_version": "money-saved-schema-version-proof-v1",
        "money_model_version": admin_export.get("money_model_version", MONEY_MODEL_VERSION),
        "input_schema": ADMIN_EXPORT_V2_SCHEMA,
        "evidence_pack_schema": EVIDENCE_PACK_SCHEMA,
        "price_db_schema": PRICE_DB_SCHEMA_VERSION,
    })
    proofs["model-binding-proof.json"] = _json_text({
        "schema_version": "money-saved-model-binding-proof-v1",
        "rows": [{"alias": r.get("alias"), "provider": r.get("provider"), "model": r.get("model")} for r in rows],
        "note": "Money is model-bound per row; price is resolved from (provider, model, price_class).",
    })
    proofs["pricing-proof.json"] = _json_text({
        "schema_version": "money-saved-pricing-proof-v1",
        "rows": [{"alias": r.get("alias"), "currency": r.get("currency"), "price_class": r.get("price_class"),
                  "price_per_1m_input_tokens": r.get("price_per_1m_input_tokens"),
                  "pricing_source": r.get("pricing_source"), "pricing_source_date": r.get("pricing_source_date")} for r in rows],
    })
    proofs["skills-savings-proof.json"] = _json_text({
        "schema_version": "money-saved-skills-savings-proof-v1",
        "rows": [{"alias": r.get("alias"), "skills_tokens_saved": r.get("skills_tokens_saved"),
                  "skills_estimated_money_saved_usd": r.get("skills_estimated_money_saved_usd")} for r in rows],
    })
    proofs["mcp-savings-proof.json"] = _json_text({
        "schema_version": "money-saved-mcp-savings-proof-v1",
        "rows": [{"alias": r.get("alias"), "mcp_tokens_saved": r.get("mcp_tokens_saved"),
                  "mcp_estimated_money_saved_usd": r.get("mcp_estimated_money_saved_usd")} for r in rows],
    })
    proofs["event-count-proof.json"] = _json_text({
        "schema_version": "money-saved-event-count-proof-v1",
        "note": "Per-row token totals already incorporate event scaling (per-event saving x event_count).",
        "rows": [{"alias": r.get("alias"), "total_tokens_saved": r.get("total_tokens_saved")} for r in rows],
    })
    proofs["cache-pricing-proof.json"] = _json_text({
        "schema_version": "money-saved-cache-pricing-proof-v1",
        "rows": [{"alias": r.get("alias"), "price_class": r.get("price_class")} for r in rows],
        "anthropic_cache_multipliers": {"cache_write_5m": 1.25, "cache_write_1h": 2.0, "cache_hit_refresh": 0.1},
    })
    proofs["money-formula-proof.json"] = _json_text({
        "schema_version": "money-saved-money-formula-proof-v1",
        "formula": MONEY_FORMULA,
        "rows": _money_formula_rows(rows),
    })
    proofs["claim-boundary-proof.json"] = _json_text({
        "schema_version": "money-saved-claim-boundary-proof-v1",
        "claim_boundary": claim_boundary(),
        "forbidden_claims": [
            "Your provider bill was reduced by $X.",
            "Exact tokens saved.",
            "Provider invoice reconciliation.",
        ],
    })
    proofs["reproducibility-proof.json"] = _json_text({
        "schema_version": "money-saved-reproducibility-proof-v1",
        "input_admin_export_sha256": admin_sha,
        "money_model_version": admin_export.get("money_model_version", MONEY_MODEL_VERSION),
        "price_db_schema": PRICE_DB_SCHEMA_VERSION,
        "recompute_recipe": (
            "For each money-formula row, resolve the price by (provider, model, price_class) from the "
            "price DB, then money = tokens / 1e6 * price_per_1m_input_tokens. Verify it matches the row."
        ),
    })

    # manifest last: hashes over every other file.
    files = []
    for name in PROOF_FILES:
        files.append({"name": name, "sha256": _sha256_text(proofs[name])})
    files.sort(key=lambda f: f["name"])
    manifest = {
        "schema_version": EVIDENCE_PACK_SCHEMA,
        "pack_type": "money_saved_evidence_pack",
        "money_model_version": admin_export.get("money_model_version", MONEY_MODEL_VERSION),
        "input_admin_export_sha256": admin_sha,
        "files": files,
        "pack_sha256": _sha256_text("".join(f["sha256"] for f in files)),
    }
    if generated_at is not None:
        manifest["generated_at"] = generated_at
    all_files = dict(proofs)
    all_files["manifest.json"] = _json_text(manifest)
    return all_files


def write_evidence_pack(admin_export: dict[str, Any], out_dir: str | Path, *, generated_at: str | None = None) -> dict[str, Any]:
    out = Path(out_dir).expanduser()
    out.mkdir(parents=True, exist_ok=True)
    files = build_evidence_pack_files(admin_export, generated_at=generated_at)
    for name, text in files.items():
        (out / name).write_text(text, encoding="utf-8")
    return json.loads(files["manifest.json"])


# --- verification --------------------------------------------------------------

def _money_close(a: float, b: float) -> bool:
    return abs(float(a) - float(b)) <= _MONEY_TOLERANCE * max(1.0, abs(float(b)))


def verify_evidence_pack(in_dir: str | Path, *, db: dict[str, Any] | None = None) -> dict[str, Any]:
    """Recompute + integrity-check an evidence pack. Never raises for tamper."""
    directory = Path(in_dir).expanduser()
    manifest_path = directory / "manifest.json"
    tamper: list[dict[str, Any]] = []

    if not manifest_path.is_file():
        return {"schema_version": VERIFICATION_SCHEMA, "ok": False, "exit_code": 2,
                "error": "manifest.json not found"}
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"schema_version": VERIFICATION_SCHEMA, "ok": False, "exit_code": 2,
                "error": "manifest.json unreadable"}
    if not isinstance(manifest, dict) or manifest.get("schema_version") != EVIDENCE_PACK_SCHEMA:
        return {"schema_version": VERIFICATION_SCHEMA, "ok": False, "exit_code": 2,
                "error": "not a money-saved evidence pack manifest"}

    # 1. Integrity: every listed file present with the manifest's sha256.
    listed = {entry.get("name"): entry.get("sha256") for entry in manifest.get("files", []) if isinstance(entry, dict)}
    missing = [name for name in PROOF_FILES if name not in listed]
    if missing:
        tamper.append({"check": "manifest_completeness", "missing_files": missing})
    for name, expected in listed.items():
        path = directory / name
        if not path.is_file():
            tamper.append({"check": "file_present", "file": name})
            continue
        actual = _sha256_text(path.read_text(encoding="utf-8"))
        if actual != expected:
            tamper.append({"check": "file_sha256", "file": name})

    # 2. Semantic recompute against the live price DB.
    recompute = {"rows_checked": 0, "rows_recomputed_ok": 0}
    formula_path = directory / "money-formula-proof.json"
    if formula_path.is_file():
        try:
            formula = json.loads(formula_path.read_text(encoding="utf-8"))
            rows = formula.get("rows", [])
        except (OSError, json.JSONDecodeError):
            rows = []
            tamper.append({"check": "money_formula_readable"})
        for row in rows:
            recompute["rows_checked"] += 1
            alias = row.get("alias")
            price = resolve_model(f"{row.get('provider')}:{row.get('model')}", db)
            if price is None:
                tamper.append({"check": "model_resolvable", "alias": alias, "model": row.get("model")})
                continue
            pc = row.get("price_class")
            try:
                rate = price_per_1m(price, pc)
            except Exception:
                tamper.append({"check": "price_class_valid", "alias": alias, "price_class": pc})
                continue
            if not _money_close(rate, row.get("price_per_1m_input_tokens", -1)):
                tamper.append({"check": "price_matches_db", "alias": alias})
                continue
            checks = (
                ("skills_estimated_money_saved_usd", "skills_tokens_saved"),
                ("mcp_estimated_money_saved_usd", "mcp_tokens_saved"),
                ("total_estimated_money_saved_usd", "total_tokens_saved"),
            )
            ok = True
            for money_field, token_field in checks:
                expected_money = money_for_tokens(int(row.get(token_field, 0)), price, pc)
                if not _money_close(expected_money, row.get(money_field, 0.0)):
                    tamper.append({"check": money_field, "alias": alias})
                    ok = False
            if ok:
                recompute["rows_recomputed_ok"] += 1
    else:
        tamper.append({"check": "money_formula_present"})

    # 3. Claim boundary must still be the safe one.
    claim_path = directory / "claim-boundary-proof.json"
    if claim_path.is_file():
        try:
            claim = json.loads(claim_path.read_text(encoding="utf-8")).get("claim_boundary", {})
        except (OSError, json.JSONDecodeError):
            claim = {}
        if not (claim.get("not_provider_bill_reconciliation") and claim.get("not_guaranteed_bill_reduction")
                and claim.get("money_kind") == "api_equivalent_estimate"):
            tamper.append({"check": "claim_boundary_intact"})

    ok = not tamper
    return {
        "schema_version": VERIFICATION_SCHEMA,
        "ok": ok,
        "exit_code": 0 if ok else 1,
        "files_checked": len(listed),
        "recompute": recompute,
        "tamper": tamper,
    }
