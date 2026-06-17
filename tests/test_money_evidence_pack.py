"""Tests for the Enterprise evidence pack + verifier (O064-R2-07)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from unlimited_skills import money_evidence_pack as ep
from unlimited_skills import money_saved_meter_v2 as m2
from unlimited_skills import money_saved_tiers_v2 as t2

_MODEL_ENV = (
    "UNLIMITED_SKILLS_MODEL", "UNLIMITED_SKILLS_RUNTIME_MODEL", "UNLIMITED_SKILLS_AGENT",
    "ANTHROPIC_MODEL", "CLAUDE_MODEL", "OPENAI_MODEL", "GOOGLE_MODEL", "DEEPSEEK_MODEL",
    "CODEX_HOME", "OPENCLAW_HOME", "OPENCLAW_WORKSPACE", "HERMES_HOME",
)


@pytest.fixture
def clean_env(monkeypatch):
    for var in _MODEL_ENV:
        monkeypatch.delenv(var, raising=False)
    return monkeypatch


def _block(total, *, kind):
    common = {"baseline_tokens": total + 60, "tokens_saved_per_event": total, "event_count": 1,
              "total_tokens_saved": total,
              "token_counter": {"provider": "anthropic", "method": "anthropic_count_tokens",
                                "exact_for_model": True, "release_acceptable": True},
              "token_count_privacy": {"provider_count_tokens_used": True,
                                      "sent_material": "level1_skill_descriptions_and_mcp_tool_schemas",
                                      "raw_prompts_sent": False, "skill_bodies_sent": False, "requires_provider_api": True}}
    if kind == "skills":
        common.update({"baseline_skill_count": 372, "actual_router_tokens": 60})
    else:
        common.update({"baseline_server_count": 2, "measured_server_count": 2, "skipped_server_count": 0, "actual_gateway_tokens": 60})
    return common


def _admin_export():
    meter = m2.build_meter_v2(model="anthropic:claude-opus-4.8", agent="claude-code",
                             skills_block=_block(85305, kind="skills"), mcp_block=_block(66864, kind="mcp"))
    reg = t2.build_registered_export_v2(meter, alias="alice")
    rollup = t2.build_team_rollup_v2([reg])
    return t2.build_admin_export_v2(rollup)


def _restamp(directory: Path):
    """Recompute the manifest hashes (simulates a sophisticated tamper)."""
    files = []
    for name in ep.PROOF_FILES:
        files.append({"name": name, "sha256": ep._sha256_text((directory / name).read_text(encoding="utf-8"))})
    files.sort(key=lambda f: f["name"])
    manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
    manifest["files"] = files
    manifest["pack_sha256"] = ep._sha256_text("".join(f["sha256"] for f in files))
    (directory / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _edit_json(path: Path, mutate):
    data = json.loads(path.read_text(encoding="utf-8"))
    mutate(data)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def test_evidence_pack_has_13_files_and_verifies(clean_env, tmp_path: Path):
    ep.write_evidence_pack(_admin_export(), tmp_path)
    names = {p.name for p in tmp_path.iterdir()}
    assert "manifest.json" in names
    assert len(names) == 13
    report = ep.verify_evidence_pack(tmp_path)
    assert report["ok"] is True and report["exit_code"] == 0
    assert report["recompute"]["rows_checked"] == 1
    assert report["recompute"]["rows_recomputed_ok"] == 1


def test_tamper_money_total_stale_manifest_is_caught(clean_env, tmp_path: Path):
    ep.write_evidence_pack(_admin_export(), tmp_path)
    fp = tmp_path / "money-formula-proof.json"
    _edit_json(fp, lambda d: d["rows"][0].__setitem__("total_estimated_money_saved_usd", 999.0))
    report = ep.verify_evidence_pack(tmp_path)  # manifest hash now stale
    assert report["ok"] is False and report["exit_code"] == 1
    assert any(t["check"] == "file_sha256" for t in report["tamper"])


def test_tamper_price_with_restamped_manifest_is_caught_semantically(clean_env, tmp_path: Path):
    ep.write_evidence_pack(_admin_export(), tmp_path)
    fp = tmp_path / "money-formula-proof.json"
    _edit_json(fp, lambda d: d["rows"][0].__setitem__("price_per_1m_input_tokens", 999.0))
    _restamp(tmp_path)  # integrity now passes; only recompute can catch it
    report = ep.verify_evidence_pack(tmp_path)
    assert report["ok"] is False and report["exit_code"] == 1
    assert any(t["check"] == "price_matches_db" for t in report["tamper"])


def test_tamper_model_with_restamped_manifest_is_caught(clean_env, tmp_path: Path):
    ep.write_evidence_pack(_admin_export(), tmp_path)
    fp = tmp_path / "money-formula-proof.json"
    # Swap to sonnet but keep opus money -> price no longer matches DB.
    _edit_json(fp, lambda d: d["rows"][0].__setitem__("model", "claude-sonnet-4.6"))
    _restamp(tmp_path)
    report = ep.verify_evidence_pack(tmp_path)
    assert report["ok"] is False and report["exit_code"] == 1


def test_tamper_claim_boundary_is_caught(clean_env, tmp_path: Path):
    ep.write_evidence_pack(_admin_export(), tmp_path)
    fp = tmp_path / "claim-boundary-proof.json"
    _edit_json(fp, lambda d: d["claim_boundary"].__setitem__("not_provider_bill_reconciliation", False))
    _restamp(tmp_path)
    report = ep.verify_evidence_pack(tmp_path)
    assert report["ok"] is False
    assert any(t["check"] == "claim_boundary_intact" for t in report["tamper"])


def test_missing_proof_file_is_caught(clean_env, tmp_path: Path):
    ep.write_evidence_pack(_admin_export(), tmp_path)
    (tmp_path / "pricing-proof.json").unlink()
    report = ep.verify_evidence_pack(tmp_path)
    assert report["ok"] is False and report["exit_code"] == 1
    assert any(t["check"] == "file_present" for t in report["tamper"])


def test_bad_input_dir_is_exit_2(tmp_path: Path):
    report = ep.verify_evidence_pack(tmp_path)  # no manifest
    assert report["ok"] is False and report["exit_code"] == 2
