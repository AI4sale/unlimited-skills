"""Tests for `sync-inject` — refresh stale agent injects after a package upgrade.

Reproduces the root cause: an inject written by an older install keeps its stale
contract because `pip install --upgrade` never re-runs the installer. The fix
stamps every agent inject (CLAUDE.md block, AGENTS.md block, Hermes router
SKILL.md block) with a contract version, lets `doctor` detect staleness, and
lets `sync-inject` refresh each installed agent idempotently.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from unlimited_skills.agents_patch import (
    CONTRACT_VERSION,
    agents_block,
    parse_contract_version,
)
from unlimited_skills.installers.claude_code import apply_claude_block, router_block_lines
from unlimited_skills.launchers import LAUNCHER_CONTRACT_VERSION, parse_launcher_contract
from unlimited_skills.sync_inject import refresh_injects
from unlimited_skills.commands.sync_inject import cmd_sync_inject


def _install_router(home: Path) -> None:
    scripts = home / "skills" / "unlimited-skills" / "scripts"
    scripts.mkdir(parents=True, exist_ok=True)
    (home / "skills" / "unlimited-skills" / "SKILL.md").write_text("---\nname: unlimited-skills\n---\nrouter body\n", encoding="utf-8")
    (scripts / "unlimited-skills.sh").write_text("#!/usr/bin/env bash\n", encoding="utf-8")
    (scripts / "unlimited-skills.ps1").write_text("param()\n", encoding="utf-8")


_STALE_V1_BLOCK = (
    "# My Notes\n\n"
    "<!-- BEGIN UNLIMITED SKILLS -->\n"
    "## Unlimited Skills Library\n\n"
    "RUN this single command BEFORE starting any task that matches a trigger below.\n"
    "<!-- END UNLIMITED SKILLS -->\n"
)


def _homes(tmp_path: Path) -> dict[str, Path]:
    openclaw_home = tmp_path / "openclaw"
    return {
        "claude_home": tmp_path / "claude",
        "codex_home": tmp_path / "codex",
        "hermes_home": tmp_path / "hermes",
        "openclaw_home": openclaw_home,
        "openclaw_workspace": openclaw_home / "workspace",
        "project_root": tmp_path / "proj",
    }


# --- contract stamp ------------------------------------------------------------

def test_fresh_blocks_are_stamped_with_current_contract():
    claude = "\n".join(router_block_lines("/x/us.sh", "/x/us.ps1"))
    codex = agents_block("/x/us.sh")
    assert parse_contract_version(claude) == CONTRACT_VERSION
    assert parse_contract_version(codex) == CONTRACT_VERSION
    assert "PHASE FRESHNESS" in claude and "PHASE FRESHNESS" in codex  # v2 content


def test_parse_contract_version_legacy_and_absent():
    assert parse_contract_version(_STALE_V1_BLOCK) == 1
    assert parse_contract_version("# nothing here\n") is None


# --- Claude Code ---------------------------------------------------------------

def test_claude_stale_block_upgraded_in_place_not_duplicated(tmp_path):
    h = _homes(tmp_path)
    _install_router(h["claude_home"])
    global_file = h["claude_home"] / "CLAUDE.md"
    global_file.write_text(_STALE_V1_BLOCK, encoding="utf-8")

    report = refresh_injects(**h, agents={"claude-code"}, patch_project=False, timestamp="20260617_000000")
    assert report.ok and "claude-code" in report.agents_present
    result = report.files[0]
    assert result.agent == "claude-code" and result.from_contract == 1 and result.to_contract == CONTRACT_VERSION
    assert result.changed and result.backup

    text = global_file.read_text(encoding="utf-8")
    assert parse_contract_version(text) == CONTRACT_VERSION
    assert text.count("<!-- BEGIN UNLIMITED SKILLS -->") == 1
    assert "# My Notes" in text and "PHASE FRESHNESS" in text


def test_idempotent_second_run_makes_no_change(tmp_path):
    h = _homes(tmp_path)
    _install_router(h["claude_home"])
    (h["claude_home"] / "CLAUDE.md").write_text(_STALE_V1_BLOCK, encoding="utf-8")
    refresh_injects(**h, agents={"claude-code"}, patch_project=False, timestamp="20260617_000000")
    second = refresh_injects(**h, agents={"claude-code"}, patch_project=False, timestamp="20260617_000001")
    assert second.files[0].changed is False
    assert second.files[0].from_contract == CONTRACT_VERSION
    assert second.files[0].backup == ""


def test_missing_file_is_created(tmp_path):
    h = _homes(tmp_path)
    _install_router(h["claude_home"])
    report = refresh_injects(**h, agents={"claude-code"}, patch_project=False, timestamp="20260617_000000")
    assert report.files[0].existed is False and report.files[0].changed is True
    assert (h["claude_home"] / "CLAUDE.md").is_file()


# --- Codex ---------------------------------------------------------------------

def test_codex_agents_md_refreshed(tmp_path):
    h = _homes(tmp_path)
    _install_router(h["codex_home"])
    agents_file = h["project_root"] / "AGENTS.md"
    agents_file.parent.mkdir(parents=True, exist_ok=True)
    agents_file.write_text(_STALE_V1_BLOCK, encoding="utf-8")
    report = refresh_injects(**h, agents={"codex"}, timestamp="20260617_000000")
    assert "codex" in report.agents_present
    result = report.files[0]
    assert result.agent == "codex" and result.from_contract == 1 and result.changed
    text = agents_file.read_text(encoding="utf-8")
    assert parse_contract_version(text) == CONTRACT_VERSION
    assert text.count("<!-- BEGIN UNLIMITED SKILLS -->") == 1


# --- OpenClaw ------------------------------------------------------------------

def test_openclaw_agents_md_refreshed(tmp_path):
    h = _homes(tmp_path)
    _install_router(h["openclaw_workspace"])
    agents_file = h["openclaw_workspace"] / "AGENTS.md"
    agents_file.write_text(_STALE_V1_BLOCK, encoding="utf-8")
    report = refresh_injects(**h, agents={"openclaw"}, timestamp="20260617_000000")
    assert "openclaw" in report.agents_present
    result = report.files[0]
    assert result.agent == "openclaw" and result.from_contract == 1 and result.changed
    text = agents_file.read_text(encoding="utf-8")
    assert parse_contract_version(text) == CONTRACT_VERSION
    assert text.count("<!-- BEGIN UNLIMITED SKILLS -->") == 1


# --- Hermes --------------------------------------------------------------------

def test_hermes_skill_md_block_refreshed(tmp_path):
    h = _homes(tmp_path)
    _install_router(h["hermes_home"])
    skill = h["hermes_home"] / "skills" / "unlimited-skills" / "SKILL.md"
    # fresh install has no block yet -> sync appends the stamped contract block
    report = refresh_injects(**h, agents={"hermes"}, timestamp="20260617_000000")
    assert "hermes" in report.agents_present
    result = report.files[0]
    assert result.agent == "hermes" and result.from_contract is None and result.changed
    text = skill.read_text(encoding="utf-8")
    assert parse_contract_version(text) == CONTRACT_VERSION
    assert "name: unlimited-skills" in text  # original frontmatter preserved
    # second run is idempotent (block now present + current)
    second = refresh_injects(**h, agents={"hermes"}, timestamp="20260617_000001")
    assert second.files[0].changed is False


# --- multi-agent / failure -----------------------------------------------------

def test_all_installed_agents_refreshed(tmp_path):
    h = _homes(tmp_path)
    for key in ("claude_home", "codex_home", "hermes_home"):
        _install_router(h[key])
    _install_router(h["openclaw_workspace"])
    report = refresh_injects(**h, patch_project=True, timestamp="20260617_000000")
    assert set(report.agents_present) == {"claude-code", "codex", "openclaw", "hermes"}


def test_no_router_present_is_a_noop_failure(tmp_path):
    h = _homes(tmp_path)
    report = refresh_injects(**h)
    assert report.ok is False and report.files == [] and report.messages


# --- CLI -----------------------------------------------------------------------

def _cli_args(h: dict, **over):
    base = dict(
        claude_home=str(h["claude_home"]), codex_home=str(h["codex_home"]),
        hermes_home=str(h["hermes_home"]), openclaw_home=str(h["openclaw_home"]),
        openclaw_workspace=str(h["openclaw_workspace"]), project_root=str(h["project_root"]),
        agent=None, no_global=False, no_project=True, no_backup=False, json=True,
    )
    base.update(over)
    return argparse.Namespace(**base)


def test_cli_returns_0_and_json(tmp_path, capsys):
    h = _homes(tmp_path)
    _install_router(h["claude_home"])
    (h["claude_home"] / "CLAUDE.md").write_text(_STALE_V1_BLOCK, encoding="utf-8")
    assert cmd_sync_inject(_cli_args(h, agent=["claude-code"])) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["contract_version"] == CONTRACT_VERSION
    assert payload["files"][0]["from_contract"] == 1


def test_cli_exit_1_when_no_router(tmp_path):
    h = _homes(tmp_path)
    assert cmd_sync_inject(_cli_args(h)) == 1


def test_cli_refreshes_openclaw_workspace_agents_md(tmp_path, capsys):
    h = _homes(tmp_path)
    _install_router(h["openclaw_workspace"])
    agents_file = h["openclaw_workspace"] / "AGENTS.md"
    agents_file.write_text(_STALE_V1_BLOCK, encoding="utf-8")
    assert cmd_sync_inject(_cli_args(h, agent=["openclaw"], no_project=False)) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["files"][0]["agent"] == "openclaw"
    assert parse_contract_version(agents_file.read_text(encoding="utf-8")) == CONTRACT_VERSION


# --- doctor staleness ----------------------------------------------------------

def test_doctor_flags_stale_injects(tmp_path, monkeypatch):
    from unlimited_skills import doctor

    h = _homes(tmp_path)
    _install_router(h["claude_home"])
    _install_router(h["codex_home"])
    _install_router(h["openclaw_workspace"])
    (h["claude_home"] / "CLAUDE.md").write_text(_STALE_V1_BLOCK, encoding="utf-8")
    agents_file = h["project_root"] / "AGENTS.md"
    agents_file.parent.mkdir(parents=True, exist_ok=True)
    agents_file.write_text(_STALE_V1_BLOCK, encoding="utf-8")
    openclaw_agents_file = h["openclaw_workspace"] / "AGENTS.md"
    openclaw_agents_file.write_text(_STALE_V1_BLOCK, encoding="utf-8")
    monkeypatch.setenv("CLAUDE_HOME", str(h["claude_home"]))
    monkeypatch.setenv("CODEX_HOME", str(h["codex_home"]))
    monkeypatch.setenv("OPENCLAW_HOME", str(h["openclaw_home"]))

    claude = doctor._claude_summary(h["project_root"])
    codex = doctor._codex_summary(h["project_root"])
    openclaw = doctor._openclaw_summary()
    assert claude["global_contract_version"] == 1 and claude["status"] == "warn"
    assert codex["agents_contract_version"] == 1 and codex["status"] == "warn"
    assert openclaw["agents_contract_version"] == 1 and openclaw["status"] == "warn"
    assert any("sync-inject" in r for r in claude["recommendations"])
    assert any("sync-inject" in r for r in codex["recommendations"])
    assert any("sync-inject" in r for r in openclaw["recommendations"])


def test_apply_claude_block_appends_when_no_block():
    out = apply_claude_block("# Existing\n\nnotes\n", "<!-- BEGIN UNLIMITED SKILLS -->\nX\n<!-- END UNLIMITED SKILLS -->")
    assert out.count("<!-- BEGIN UNLIMITED SKILLS -->") == 1 and "# Existing" in out


# --- launcher healing (--heal-launchers) ---------------------------------------

_LEGACY_SH = (
    "#!/usr/bin/env bash\nset -euo pipefail\nexport PYTHONPATH=/old/repo\n"
    'exec /old/py -m unlimited_skills --root /old/lib "$@"\n'
)
_LEGACY_PS = "param()\n$env:PYTHONPATH='/old/repo'\n& /old/py -m unlimited_skills --root /old/lib @Args\n"


def _install_legacy_launchers(home: Path) -> Path:
    _install_router(home)
    scripts = home / "skills" / "unlimited-skills" / "scripts"
    (scripts / "unlimited-skills.sh").write_text(_LEGACY_SH, encoding="utf-8")
    (scripts / "unlimited-skills.ps1").write_text(_LEGACY_PS, encoding="utf-8")
    return scripts


def _heal_kwargs(tmp_path: Path):
    return dict(
        heal_launchers=True,
        python_executable=sys.executable,
        library_root=tmp_path / "lib",
        repo_root=None,
        timestamp="20260617_000000",
    )


def test_heal_launchers_rewrites_stale_launcher(tmp_path):
    h = _homes(tmp_path)
    scripts = _install_legacy_launchers(h["claude_home"])
    assert parse_launcher_contract((scripts / "unlimited-skills.sh").read_text(encoding="utf-8")) == 0

    report = refresh_injects(**h, agents={"claude-code"}, patch_project=False, **_heal_kwargs(tmp_path))
    kinds = {l.kind: l for l in report.launchers}
    assert set(kinds) == {"sh", "ps"}
    assert kinds["sh"].from_contract == 0 and kinds["sh"].to_contract == LAUNCHER_CONTRACT_VERSION
    assert kinds["sh"].changed and kinds["sh"].backup  # legacy launcher backed up before rewrite
    new_sh = (scripts / "unlimited-skills.sh").read_text(encoding="utf-8")
    assert "export PYTHONPATH=" not in new_sh  # no more shadowing source path
    assert parse_launcher_contract(new_sh) == LAUNCHER_CONTRACT_VERSION
    assert sys.executable.replace("\\", "/") in new_sh  # runs the recorded interpreter


def test_heal_launchers_idempotent_second_run(tmp_path):
    h = _homes(tmp_path)
    _install_legacy_launchers(h["claude_home"])
    refresh_injects(**h, agents={"claude-code"}, patch_project=False, **_heal_kwargs(tmp_path))
    kwargs = _heal_kwargs(tmp_path)
    kwargs["timestamp"] = "20260617_000001"
    second = refresh_injects(**h, agents={"claude-code"}, patch_project=False, **kwargs)
    for launcher in second.launchers:
        assert launcher.changed is False and launcher.backup == ""


def test_heal_launchers_does_not_fabricate_missing_ps(tmp_path):
    # Codex/OpenClaw write only the .sh; heal must not create a .ps1 the installer never made.
    h = _homes(tmp_path)
    scripts = _install_legacy_launchers(h["codex_home"])
    (scripts / "unlimited-skills.ps1").unlink()
    report = refresh_injects(**h, agents={"codex"}, **_heal_kwargs(tmp_path))
    assert {l.kind for l in report.launchers} == {"sh"}
    assert not (scripts / "unlimited-skills.ps1").exists()


def test_heal_launchers_off_by_default(tmp_path):
    h = _homes(tmp_path)
    _install_legacy_launchers(h["claude_home"])
    report = refresh_injects(**h, agents={"claude-code"}, patch_project=False, timestamp="20260617_000000")
    assert report.launchers == []  # inject-only refresh leaves launchers untouched


def test_heal_all_agents(tmp_path):
    h = _homes(tmp_path)
    for key in ("claude_home", "codex_home", "hermes_home"):
        _install_legacy_launchers(h[key])
    _install_legacy_launchers(h["openclaw_workspace"])
    report = refresh_injects(**h, patch_project=True, **_heal_kwargs(tmp_path))
    healed_agents = {l.agent for l in report.launchers}
    assert healed_agents == {"claude-code", "codex", "openclaw", "hermes"}
    assert all(l.to_contract == LAUNCHER_CONTRACT_VERSION for l in report.launchers)


def test_doctor_flags_stale_launcher(tmp_path, monkeypatch):
    from unlimited_skills import doctor

    h = _homes(tmp_path)
    _install_legacy_launchers(h["claude_home"])
    monkeypatch.setenv("CLAUDE_HOME", str(h["claude_home"]))
    summary = doctor._claude_summary(h["project_root"])
    assert summary["launcher_stale"] is True and summary["status"] == "warn"
    assert summary["launcher_contract_version"] == 0
    assert any("heal-launchers" in r for r in summary["recommendations"])


def test_cli_heal_launchers_flag(tmp_path, capsys):
    h = _homes(tmp_path)
    _install_legacy_launchers(h["claude_home"])
    args = _cli_args(
        h,
        agent=["claude-code"],
        heal_launchers=True,
        library_root=str(tmp_path / "lib"),
        repo_root="",
    )
    assert cmd_sync_inject(args) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["launcher_contract_version"] == LAUNCHER_CONTRACT_VERSION
    assert any(item["kind"] == "sh" and item["changed"] for item in payload["launchers"])
