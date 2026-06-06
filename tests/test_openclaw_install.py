from __future__ import annotations

import os
from pathlib import Path

from unlimited_skills.installers import openclaw
from unlimited_skills.installers.openclaw import OpenClawInstallOptions, install_openclaw


def write_skill(root: Path, name: str, description: str = "test skill") -> Path:
    skill_dir = root / name
    skill_dir.mkdir(parents=True, exist_ok=True)
    (skill_dir / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: {description}\n---\n\n# {name}\n",
        encoding="utf-8",
    )
    return skill_dir


def make_repo(root: Path) -> Path:
    router = root / "skills" / "router-openclaw"
    router.mkdir(parents=True)
    (router / "SKILL.md").write_text(
        "---\nname: unlimited-skills\ndescription: test router\n---\n\n"
        "# Router\n\n"
        "{{OPENCLAW_SH_LAUNCHER}}\n"
        "{{UNLIMITED_SKILLS_LIBRARY_ROOT}}\n",
        encoding="utf-8",
    )
    write_skill(root / "packs" / "ecc" / "skills", "security-review")
    write_skill(root / "packs" / "superpowers" / "skills", "systematic-debugging")
    return root


def test_openclaw_install_bundled_imports_workspace_plugin_and_builtin_skills(tmp_path: Path, monkeypatch) -> None:
    repo_root = make_repo(tmp_path / "repo")
    openclaw_home = tmp_path / ".openclaw"
    workspace_root = openclaw_home / "workspace"
    install_root = tmp_path / ".unlimited-skills"
    builtin_root = tmp_path / "usr" / "local" / "lib" / "node_modules" / "openclaw" / "skills"

    write_skill(workspace_root / "skills", "redmine")
    write_skill(workspace_root / "skills", "unlimited-skills")
    write_skill(openclaw_home / "plugin-skills", "browser-automation")
    write_skill(builtin_root, "healthcheck")

    def fake_sources(openclaw_home_arg, workspace_root_arg, include_builtin, include_plugin_skills):
        sources = [("openclaw-workspace", workspace_root_arg / "skills")]
        if include_plugin_skills:
            sources.append(("openclaw-plugin", openclaw_home_arg / "plugin-skills"))
        if include_builtin:
            sources.append(("openclaw-builtin", builtin_root))
        return sources

    monkeypatch.setattr(openclaw, "_openclaw_sources", fake_sources)

    report = install_openclaw(
        OpenClawInstallOptions(
            openclaw_home=openclaw_home,
            workspace_root=workspace_root,
            install_root=install_root,
            repo_root=repo_root,
            mode="bundled",
            skip_reindex=False,
        )
    )

    library = install_root / "library"
    assert report.router_installed is True
    assert report.agents_patched is True
    assert report.lexical_index == "rebuilt"
    assert (workspace_root / "skills" / "unlimited-skills" / "scripts" / "unlimited-skills.sh").is_file()
    assert (workspace_root / "AGENTS.md").is_file()

    router_text = (workspace_root / "skills" / "unlimited-skills" / "SKILL.md").read_text(encoding="utf-8")
    assert ".codex" not in router_text
    assert "scripts/unlimited-skills.sh" in router_text
    assert "{{OPENCLAW_SH_LAUNCHER}}" not in router_text

    agents_text = (workspace_root / "AGENTS.md").read_text(encoding="utf-8")
    assert "scripts/unlimited-skills.sh" in agents_text
    assert ".codex" not in agents_text
    assert "<!-- BEGIN UNLIMITED SKILLS -->" in agents_text

    assert (library / "ecc" / "skills" / "security-review" / "SKILL.md").is_file()
    assert (library / "superpowers" / "skills" / "systematic-debugging" / "SKILL.md").is_file()
    assert (library / "openclaw-workspace" / "skills" / "redmine" / "SKILL.md").is_file()
    assert not (library / "openclaw-workspace" / "skills" / "unlimited-skills" / "SKILL.md").exists()
    assert (library / "openclaw-plugin" / "skills" / "browser-automation" / "SKILL.md").is_file()
    assert (library / "openclaw-builtin" / "skills" / "healthcheck" / "SKILL.md").is_file()
    assert (library / ".unlimited-skills-index.json").is_file()

    counts = {item.collection: item.migrated_count for item in report.migrations}
    assert counts["ecc"] == 1
    assert counts["superpowers"] == 1
    assert counts["openclaw-workspace"] == 1
    assert counts["openclaw-plugin"] == 1
    assert counts["openclaw-builtin"] == 1


def test_openclaw_install_can_skip_agents_patch_and_optional_sources(tmp_path: Path, monkeypatch) -> None:
    repo_root = make_repo(tmp_path / "repo")
    openclaw_home = tmp_path / ".openclaw"
    workspace_root = openclaw_home / "workspace"
    install_root = tmp_path / ".unlimited-skills"
    write_skill(workspace_root / "skills", "redmine")

    def fake_sources(openclaw_home_arg, workspace_root_arg, include_builtin, include_plugin_skills):
        assert include_builtin is False
        assert include_plugin_skills is False
        return [("openclaw-workspace", workspace_root_arg / "skills")]

    monkeypatch.setattr(openclaw, "_openclaw_sources", fake_sources)

    report = install_openclaw(
        OpenClawInstallOptions(
            openclaw_home=openclaw_home,
            workspace_root=workspace_root,
            install_root=install_root,
            repo_root=repo_root,
            patch_agents=False,
            include_builtin=False,
            include_plugin_skills=False,
            skip_reindex=True,
        )
    )

    assert report.agents_patched is False
    assert not (workspace_root / "AGENTS.md").exists()
    assert (workspace_root / "skills" / "unlimited-skills" / "SKILL.md").is_file()
    assert (install_root / "library" / "openclaw-workspace" / "skills" / "redmine" / "SKILL.md").is_file()


def test_openclaw_plugin_symlink_is_migrated(tmp_path: Path, monkeypatch) -> None:
    if not hasattr(os, "symlink"):
        return

    repo_root = make_repo(tmp_path / "repo")
    openclaw_home = tmp_path / ".openclaw"
    workspace_root = openclaw_home / "workspace"
    install_root = tmp_path / ".unlimited-skills"
    write_skill(workspace_root / "skills", "redmine")
    real_plugin = write_skill(tmp_path / "actual-plugin", "browser-automation")
    plugin_link = openclaw_home / "plugin-skills" / "browser-automation"
    plugin_link.parent.mkdir(parents=True)
    plugin_link.symlink_to(real_plugin, target_is_directory=True)

    def fake_sources(openclaw_home_arg, workspace_root_arg, include_builtin, include_plugin_skills):
        return [
            ("openclaw-workspace", workspace_root_arg / "skills"),
            ("openclaw-plugin", openclaw_home_arg / "plugin-skills"),
        ]

    monkeypatch.setattr(openclaw, "_openclaw_sources", fake_sources)

    install_openclaw(
        OpenClawInstallOptions(
            openclaw_home=openclaw_home,
            workspace_root=workspace_root,
            install_root=install_root,
            repo_root=repo_root,
            include_builtin=False,
            skip_reindex=True,
        )
    )

    assert (install_root / "library" / "openclaw-plugin" / "skills" / "browser-automation" / "SKILL.md").is_file()
