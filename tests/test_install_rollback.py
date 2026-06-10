from __future__ import annotations

import json
from pathlib import Path

import pytest

from unlimited_skills.installers import claude_code as claude_code_installer
from unlimited_skills.installers.claude_code import ClaudeCodeInstallOptions, install_claude_code
from unlimited_skills.installers.common import rollback_install
from unlimited_skills.installers.openclaw import OpenClawInstallOptions, install_openclaw


ROOT = Path(__file__).resolve().parents[1]


def write_skill(root: Path, name: str) -> None:
    skill_dir = root / name
    skill_dir.mkdir(parents=True, exist_ok=True)
    (skill_dir / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: {name}\n---\n\n# {name}\n",
        encoding="utf-8",
    )


def claude_options(tmp_path: Path, **overrides) -> ClaudeCodeInstallOptions:
    defaults = dict(
        claude_home=tmp_path / ".claude",
        project_root=tmp_path / "project",
        install_root=tmp_path / ".unlimited-skills",
        repo_root=ROOT,
        skip_reindex=True,
    )
    defaults.update(overrides)
    return ClaudeCodeInstallOptions(**defaults)


def test_claude_code_rollback_restores_prior_state(tmp_path: Path) -> None:
    claude_home = tmp_path / ".claude"
    project_root = tmp_path / "project"
    write_skill(claude_home / "skills", "alpha")
    claude_file = project_root / "CLAUDE.md"
    claude_file.parent.mkdir(parents=True, exist_ok=True)
    claude_file.write_text("# My project\n", encoding="utf-8")
    global_claude_file = claude_home / "CLAUDE.md"
    global_claude_file.write_text("# Global memory\n", encoding="utf-8")

    report = install_claude_code(claude_options(tmp_path))

    assert report.rollback_manifest
    manifest = Path(report.rollback_manifest)
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    assert payload["schema_version"] == 2
    assert payload["agent"] == "claude-code"
    assert payload["actions"]
    assert "UNLIMITED SKILLS" in claude_file.read_text(encoding="utf-8")
    library_copy = tmp_path / ".unlimited-skills" / "library" / "local" / "claude-code" / "skills" / "alpha"
    assert library_copy.is_dir()

    dry = rollback_install(manifest, apply=False)
    assert dry.dry_run is True
    assert "UNLIMITED SKILLS" in claude_file.read_text(encoding="utf-8")

    rollback_report = rollback_install(manifest, apply=True)

    assert rollback_report.dry_run is False
    assert claude_file.read_text(encoding="utf-8") == "# My project\n"
    assert global_claude_file.read_text(encoding="utf-8") == "# Global memory\n"
    assert not (claude_home / "skills" / "unlimited-skills").exists()
    assert not library_copy.exists()
    # The original visible skill is untouched by install and rollback.
    assert (claude_home / "skills" / "alpha" / "SKILL.md").is_file()


def test_claude_code_rollback_removes_created_claude_md(tmp_path: Path) -> None:
    report = install_claude_code(claude_options(tmp_path))
    claude_file = tmp_path / "project" / "CLAUDE.md"
    global_claude_file = tmp_path / ".claude" / "CLAUDE.md"
    assert claude_file.is_file()
    assert global_claude_file.is_file()

    rollback_install(Path(report.rollback_manifest), apply=True)

    assert not claude_file.exists()
    assert not global_claude_file.exists()


def test_claude_code_failed_install_rolls_back_automatically(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    claude_home = tmp_path / ".claude"
    write_skill(claude_home / "skills", "alpha")
    claude_file = tmp_path / "project" / "CLAUDE.md"
    claude_file.parent.mkdir(parents=True, exist_ok=True)
    claude_file.write_text("# My project\n", encoding="utf-8")

    def boom(*args, **kwargs):
        raise RuntimeError("migration exploded")

    monkeypatch.setattr(claude_code_installer, "migrate_source", boom)

    with pytest.raises(RuntimeError, match="migration exploded"):
        install_claude_code(claude_options(tmp_path))

    assert claude_file.read_text(encoding="utf-8") == "# My project\n"
    assert not (claude_home / "skills" / "unlimited-skills").exists()
    assert not (tmp_path / ".unlimited-skills" / "library" / "local" / "claude-code").exists()


def test_claude_code_reinstall_rollback_restores_previous_router(tmp_path: Path) -> None:
    first = install_claude_code(claude_options(tmp_path))
    router_skill = tmp_path / ".claude" / "skills" / "unlimited-skills" / "SKILL.md"
    marker = "<!-- first install marker -->"
    router_skill.write_text(router_skill.read_text(encoding="utf-8") + "\n" + marker, encoding="utf-8")

    second = install_claude_code(claude_options(tmp_path))
    assert first.rollback_manifest != second.rollback_manifest
    assert marker not in router_skill.read_text(encoding="utf-8")

    rollback_install(Path(second.rollback_manifest), apply=True)

    assert marker in router_skill.read_text(encoding="utf-8")


def test_openclaw_rollback_restores_agents_file(tmp_path: Path) -> None:
    openclaw_home = tmp_path / ".openclaw"
    workspace_root = openclaw_home / "workspace"
    write_skill(workspace_root / "skills", "alpha")
    agents_file = workspace_root / "AGENTS.md"
    agents_file.parent.mkdir(parents=True, exist_ok=True)
    agents_file.write_text("# Agents\n", encoding="utf-8")

    report = install_openclaw(
        OpenClawInstallOptions(
            openclaw_home=openclaw_home,
            workspace_root=workspace_root,
            install_root=tmp_path / ".unlimited-skills",
            repo_root=ROOT,
            include_builtin=False,
            include_plugin_skills=False,
            skip_reindex=True,
        )
    )

    assert report.rollback_manifest
    assert "UNLIMITED SKILLS" in agents_file.read_text(encoding="utf-8")

    rollback_report = rollback_install(Path(report.rollback_manifest), apply=True)

    assert rollback_report.dry_run is False
    assert agents_file.read_text(encoding="utf-8") == "# Agents\n"
    assert not (workspace_root / "skills" / "unlimited-skills").exists()
    assert (workspace_root / "skills" / "alpha" / "SKILL.md").is_file()
