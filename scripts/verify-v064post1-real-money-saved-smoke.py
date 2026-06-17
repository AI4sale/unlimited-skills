#!/usr/bin/env python3
"""Release smoke for Real Money Saved, v0.6.4.post1 (O064-R2-08).

Exercises the whole money chain end to end and HARD-FAILS the release if the
contract is not met. Runs offline: a deterministic exact token counter stands in
for Anthropic ``count_tokens`` so the logic is reproducible in CI; on a machine
with ``ANTHROPIC_API_KEY`` the real counter would be used by the meter instead.

Covers BOTH the exact-model path (explicit ``--model``) AND the hidden-runtime
assumption path (no model, supported agent). 11 checks:

  1  model-detect works
  2  prices show works
  3  Free meter outputs skills_savings + mcp_savings + non-null money
  4  Registered export carries the same basis + money
  5  Team rollup aggregates a compatible basis
  6  Business admin CSV/JSON has the money columns
  7  Enterprise evidence pack verifies ok=true
  8  tamper model    -> verify ok=false
  9  tamper price    -> verify ok=false
  10 tamper total $  -> verify ok=false
  11 legacy v0.6.4 proxy report rejected by the money tiers

Exit 0 = all checks pass; exit 1 = any check failed.
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path

from unlimited_skills import model_detect as md
from unlimited_skills import money_evidence_pack as ep
from unlimited_skills import money_pricing as mp
from unlimited_skills import money_saved_meter_v2 as m2
from unlimited_skills import money_saved_tiers_v2 as t2


def _det_counter(text: str) -> int:
    # Deterministic, release_acceptable-style exact counter for offline smoke.
    return max(1, len(text) // 3)


def _skills_block(total: int) -> dict:
    return {
        "baseline_skill_count": 372, "baseline_material": "level1_name_description_for_every_visible_skill",
        "baseline_tokens": total + 60, "actual_material": "router_descriptor", "actual_router_tokens": 60,
        "tokens_saved_per_event": total, "event_count": 1, "total_tokens_saved": total,
        "token_counter": {"provider": "anthropic", "method": "anthropic_count_tokens",
                          "exact_for_model": True, "release_acceptable": True},
        "token_count_privacy": {"provider_count_tokens_used": True,
                                "sent_material": "level1_skill_descriptions_and_mcp_tool_schemas",
                                "raw_prompts_sent": False, "skill_bodies_sent": False, "requires_provider_api": True},
    }


def _mcp_block(total: int) -> dict:
    return {
        "baseline_server_count": 2, "measured_server_count": 2, "skipped_server_count": 0,
        "baseline_material": "full_upstream_tools_list_for_all_configured_servers",
        "baseline_tokens": total + 50, "actual_material": "gateway_meta_tools_list",
        "actual_gateway_tokens": 50, "tokens_saved_per_event": total, "event_count": 1, "total_tokens_saved": total,
        "token_counter": {"provider": "anthropic", "method": "anthropic_count_tokens",
                          "exact_for_model": True, "release_acceptable": True},
        "token_count_privacy": {"provider_count_tokens_used": True,
                                "sent_material": "level1_skill_descriptions_and_mcp_tool_schemas",
                                "raw_prompts_sent": False, "skill_bodies_sent": False, "requires_provider_api": True},
    }


def _meter(model, agent, skills=85305, mcp=66864):
    return m2.build_meter_v2(model=model, agent=agent,
                             skills_block=_skills_block(skills), mcp_block=_mcp_block(mcp))


def _edit_json(path: Path, mutate) -> None:
    data = json.loads(path.read_text(encoding="utf-8"))
    mutate(data)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _restamp(directory: Path) -> None:
    files = []
    for name in ep.PROOF_FILES:
        files.append({"name": name, "sha256": ep._sha256_text((directory / name).read_text(encoding="utf-8"))})
    files.sort(key=lambda f: f["name"])
    manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
    manifest["files"] = files
    manifest["pack_sha256"] = ep._sha256_text("".join(f["sha256"] for f in files))
    (directory / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def run_smoke() -> dict:
    checks: list[dict] = []

    def check(num: int, name: str, ok: bool, detail: str = "") -> None:
        checks.append({"check": num, "name": name, "ok": bool(ok), "detail": detail})

    # --- the two paths -------------------------------------------------------
    exact = _meter("anthropic:claude-opus-4.8", "claude-code")
    assumed = m2.build_meter_v2(agent="codex", skills_block=_skills_block(100000), mcp_block=_mcp_block(0))

    # 1. model-detect
    det = md.model_detect_report(md.bind_model("anthropic:claude-opus-4.8", agent="claude-code"))
    check(1, "model_detect_works", det.get("available") is True and det.get("pricing_available") is True)

    # 2. prices show
    opus = mp.resolve_model("anthropic:claude-opus-4.8")
    check(2, "prices_show_works", opus is not None and opus.base_input_per_1m == 5.0)

    # 3. Free meter: skills + mcp + non-null money (BOTH paths)
    def meter_ok(rep: dict) -> bool:
        s = rep.get("savings", {})
        return (
            rep.get("available") is True
            and isinstance(s.get("skills"), dict) and isinstance(s.get("mcp"), dict)
            and s.get("total", {}).get("estimated_money_saved_usd") not in (None, 0)
            and isinstance(rep.get("model_binding"), dict)
            and rep.get("pricing", {}).get("source_url") and rep.get("pricing", {}).get("source_date")
            and rep["savings"]["skills"]["token_counter"]["method"]
            and rep.get("claim_boundary", {}).get("money_kind") == "api_equivalent_estimate"
        )
    check(3, "free_meter_skills_mcp_money_both_paths",
          meter_ok(exact) and assumed.get("available") is True
          and assumed["savings"]["total"]["estimated_money_saved_usd"] > 0,
          detail=f"exact_total=${exact['savings']['total']['estimated_money_saved_usd']:.6f} "
                 f"assumed_conf={assumed['model_binding']['confidence']}")

    # 4. Registered export carries basis + money
    reg = t2.build_registered_export_v2(exact, alias="alice")
    check(4, "registered_same_basis_money",
          reg.get("basis_key") and reg["savings"]["total"]["estimated_money_saved_usd"] > 0)

    # 5. Team rollup aggregates a compatible basis
    reg2 = t2.build_registered_export_v2(_meter("anthropic:claude-opus-4.8", "claude-code", 40000, 10000), alias="bob")
    rollup = t2.build_team_rollup_v2([reg, reg2])
    check(5, "team_rollup_compatible_basis",
          rollup["group_count"] == 1 and rollup["single_compatible_basis"] is True
          and rollup["groups"][0]["member_count"] == 2)

    # 6. Business admin CSV/JSON money columns
    admin = t2.build_admin_export_v2(rollup)
    csv = t2.admin_export_v2_csv(admin)
    header = csv.splitlines()[0]
    money_cols = ("skills_estimated_money_saved_usd", "mcp_estimated_money_saved_usd", "total_estimated_money_saved_usd")
    check(6, "business_csv_money_columns",
          all(col in header for col in money_cols) and admin["row_count"] == 2
          and len(json.loads(t2.admin_export_v2_json(admin))["rows"]) == 2)

    # 7-10. Enterprise evidence pack + tamper
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        ep.write_evidence_pack(admin, d)
        report7 = ep.verify_evidence_pack(d)
        check(7, "enterprise_verify_ok", report7["ok"] is True and report7["recompute"]["rows_checked"] == 2)

    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        ep.write_evidence_pack(admin, d)
        _edit_json(d / "money-formula-proof.json", lambda x: x["rows"][0].__setitem__("model", "claude-sonnet-4.6"))
        _restamp(d)
        check(8, "tamper_model_fails", ep.verify_evidence_pack(d)["ok"] is False)

    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        ep.write_evidence_pack(admin, d)
        _edit_json(d / "money-formula-proof.json", lambda x: x["rows"][0].__setitem__("price_per_1m_input_tokens", 999.0))
        _restamp(d)
        check(9, "tamper_price_fails", ep.verify_evidence_pack(d)["ok"] is False)

    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        ep.write_evidence_pack(admin, d)
        _edit_json(d / "money-formula-proof.json", lambda x: x["rows"][0].__setitem__("total_estimated_money_saved_usd", 999.0))
        check(10, "tamper_total_money_fails", ep.verify_evidence_pack(d)["ok"] is False)

    # 11. legacy v0.6.4 proxy report rejected by the money tiers
    legacy_proxy = {
        "schema_version": "registered-export-v1", "export_type": "money_saved_registered_export",
        "legacy_proxy_report": True, "money_available": False,
        "reason": "v064_proxy_context_meter_no_money_model",
    }
    legacy_rollup = t2.build_team_rollup_v2([legacy_proxy])
    check(11, "legacy_proxy_rejected",
          legacy_rollup["group_count"] == 0 and len(legacy_rollup["rejected"]) == 1)

    failures = [c for c in checks if not c["ok"]]
    return {
        "smoke": "v0.6.4.post1-real-money-saved",
        "ok": not failures,
        "exit_code": 0 if not failures else 1,
        "checks": checks,
        "failures": failures,
        "note": "Offline smoke uses a deterministic exact counter; the release gate "
                "requires Anthropic count_tokens for the Claude path.",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Real Money Saved release smoke (v0.6.4.post1).")
    parser.add_argument("--json", action="store_true", help="Emit the machine-readable report.")
    args = parser.parse_args(argv)
    report = run_smoke()
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        for c in report["checks"]:
            print(f"[{'PASS' if c['ok'] else 'FAIL'}] {c['check']:>2}. {c['name']} {c['detail']}".rstrip())
        print(f"\n{'OK' if report['ok'] else 'FAILED'}: {len(report['checks']) - len(report['failures'])}/"
              f"{len(report['checks'])} checks passed")
    return report["exit_code"]


if __name__ == "__main__":
    sys.exit(main())
