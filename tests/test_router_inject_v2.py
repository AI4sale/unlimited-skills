from __future__ import annotations

import json
import runpy
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
GENERATOR = REPO_ROOT / "scripts" / "generate-router-inventory.py"
FIXTURE_VERIFIER = REPO_ROOT / "scripts" / "verify-router-inject-v2-fixture.py"


def _generator_module() -> dict:
    return runpy.run_path(str(GENERATOR))


def test_router_inventory_snapshot_is_generated_deterministic_and_private() -> None:
    module = _generator_module()
    first = module["build_snapshot"]()
    second = module["build_snapshot"]()

    assert first == second
    assert first["total_routable_skills"] == sum(first["collections"].values())
    assert set(first["collections"]) >= {"ecc", "superpowers", "local"}
    assert first["privacy"] == {
        "contains_local_absolute_paths": False,
        "contains_prompts_or_secrets": False,
        "contains_skill_bodies": False,
    }

    domains = first["domains"]
    assert len(domains) <= 15
    assert any(row["domain"] == "other/uncategorized" for row in domains)
    assert any(row["availability"] == "empty" for row in domains)
    assert str(REPO_ROOT) not in json.dumps(first)


def test_router_inventory_checked_in_outputs_and_agents_block_are_current() -> None:
    result = subprocess.run(
        [sys.executable, str(GENERATOR), "--check"],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_agents_router_inject_v2_block_has_required_contract_and_no_overclaim() -> None:
    text = (REPO_ROOT / "AGENTS.md").read_text(encoding="utf-8")

    assert 'unlimited-skills suggest "<3-8 keyword phase summary>" --json --card --limit 1' in text
    assert "A `suggest` result is fresh only for the current phase" in text
    assert "A no-hit result also applies only to the current phase" in text
    assert "Anti-spam rule" in text
    assert "Tier 1" in text and "Tier 2" in text and "Tier 3" in text
    assert "UNLIMITED_SKILLS_NO_INJECT=1" in text
    assert "<!-- BEGIN ROUTER INVENTORY SNAPSHOT -->" in text
    assert "Generated routable skills:" in text
    assert "other/uncategorized" in text
    assert "does not claim a runtime phase-boundary hook exists" in text
    assert "250+" not in text


def test_router_inject_fixture_proves_phase_requery_and_antispam() -> None:
    result = subprocess.run(
        [sys.executable, str(FIXTURE_VERIFIER), "--json"],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    report = json.loads(result.stdout)
    assert report["ok"] is True
    assert report["phase_count"] == 10
    assert report["step_count"] == 100
    assert report["required_requery_count"] >= 4
    assert report["same_domain_negative_count"] >= 2
    assert report["mechanism"] == "guidance_decision_level_not_runtime_hook"
