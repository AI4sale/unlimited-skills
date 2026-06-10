from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
MARKETPLACE = REPO_ROOT / ".claude-plugin" / "marketplace.json"
PLUGIN_ROOT = REPO_ROOT / "plugin"
PLUGIN_MANIFEST = PLUGIN_ROOT / ".claude-plugin" / "plugin.json"
HOOKS_FILE = PLUGIN_ROOT / "hooks" / "hooks.json"
SESSION_START = PLUGIN_ROOT / "hooks" / "session_start.py"
ROUTER_SKILL = PLUGIN_ROOT / "skills" / "unlimited-skills" / "SKILL.md"


def test_marketplace_manifest_points_at_plugin_dir() -> None:
    payload = json.loads(MARKETPLACE.read_text(encoding="utf-8"))
    assert payload["name"] == "unlimited-skills"
    plugins = payload["plugins"]
    assert len(plugins) == 1
    entry = plugins[0]
    assert entry["name"] == "unlimited-skills"
    assert entry["source"] == "./plugin"
    assert entry["license"] == "MIT"
    assert (REPO_ROOT / "plugin").is_dir()


def test_plugin_manifest_declares_skills_and_hooks() -> None:
    payload = json.loads(PLUGIN_MANIFEST.read_text(encoding="utf-8"))
    assert payload["name"] == "unlimited-skills"
    assert payload["skills"] == ["./skills/"]
    assert payload["hooks"] == "./hooks/hooks.json"
    for rel in payload["skills"]:
        assert (PLUGIN_ROOT / rel).is_dir()
    assert (PLUGIN_ROOT / payload["hooks"]).is_file()


def test_plugin_and_marketplace_versions_match_package_version() -> None:
    from unlimited_skills import __version__

    plugin_version = json.loads(PLUGIN_MANIFEST.read_text(encoding="utf-8"))["version"]
    marketplace_version = json.loads(MARKETPLACE.read_text(encoding="utf-8"))["plugins"][0]["version"]
    assert plugin_version == __version__
    assert marketplace_version == __version__


def test_plugin_router_skill_has_frontmatter_and_no_machine_paths() -> None:
    text = ROUTER_SKILL.read_text(encoding="utf-8")
    assert text.startswith("---\nname: unlimited-skills\n")
    assert "description:" in text
    assert "{{" not in text  # no unrendered installer placeholders
    assert "C:/Users" not in text and "/home/" not in text  # no machine-specific paths
    assert "unlimited-skills search" in text


def test_session_start_hook_references_existing_script() -> None:
    payload = json.loads(HOOKS_FILE.read_text(encoding="utf-8"))
    session_start = payload["hooks"]["SessionStart"]
    command = session_start[0]["hooks"][0]["command"]
    assert "session_start.py" in command
    assert "${CLAUDE_PLUGIN_ROOT}" in command
    assert SESSION_START.is_file()


def test_session_start_hook_prints_router_contract_and_exits_zero() -> None:
    result = subprocess.run(
        [sys.executable, str(SESSION_START)],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0
    assert "Unlimited Skills Library" in result.stdout
    assert "unlimited-skills" in result.stdout
    # The hook must never leak skill bodies or library contents.
    assert len(result.stdout) < 2000
