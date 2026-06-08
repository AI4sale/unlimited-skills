from __future__ import annotations

import os
import json
from pathlib import Path

import pytest

from unlimited_skills.installers import openclaw
from unlimited_skills.installers.openclaw import OpenClawInstallOptions, install_openclaw
from unlimited_skills.installers.remote import RemoteHubInstallOptions


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
        "{{UNLIMITED_SKILLS_LIBRARY_ROOT}}\n"
        "{{REMOTE_HUB_ROUTER_BLOCK}}\n",
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

    assert (library / "registry" / "ecc" / "skills" / "security-review" / "SKILL.md").is_file()
    assert (library / "registry" / "superpowers" / "skills" / "systematic-debugging" / "SKILL.md").is_file()
    assert (library / "local" / "openclaw-workspace" / "skills" / "redmine" / "SKILL.md").is_file()
    assert not (library / "local" / "openclaw-workspace" / "skills" / "unlimited-skills" / "SKILL.md").exists()
    assert (library / "local" / "openclaw-plugin" / "skills" / "browser-automation" / "SKILL.md").is_file()
    assert (library / "local" / "openclaw-builtin" / "skills" / "healthcheck" / "SKILL.md").is_file()
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
    assert (install_root / "library" / "local" / "openclaw-workspace" / "skills" / "redmine" / "SKILL.md").is_file()


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
    try:
        plugin_link.symlink_to(real_plugin, target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"Symlink creation is not permitted in this environment: {exc}")

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

    assert (install_root / "library" / "local" / "openclaw-plugin" / "skills" / "browser-automation" / "SKILL.md").is_file()


def test_openclaw_reinstall_refreshes_same_collection_skills(tmp_path: Path, monkeypatch) -> None:
    repo_root = make_repo(tmp_path / "repo")
    openclaw_home = tmp_path / ".openclaw"
    workspace_root = openclaw_home / "workspace"
    install_root = tmp_path / ".unlimited-skills"
    source_skill = write_skill(workspace_root / "skills", "custom-skill", "v1")

    def fake_sources(openclaw_home_arg, workspace_root_arg, include_builtin, include_plugin_skills):
        return [("openclaw-workspace", workspace_root_arg / "skills")]

    monkeypatch.setattr(openclaw, "_openclaw_sources", fake_sources)

    options = OpenClawInstallOptions(
        openclaw_home=openclaw_home,
        workspace_root=workspace_root,
        install_root=install_root,
        repo_root=repo_root,
        include_builtin=False,
        include_plugin_skills=False,
        skip_reindex=True,
    )
    first = install_openclaw(options)
    assert first.migrations[0].migrated_count == 1

    (source_skill / "SKILL.md").write_text(
        "---\nname: custom-skill\ndescription: v2\n---\n\n# custom-skill\n",
        encoding="utf-8",
    )
    second = install_openclaw(options)

    library_skill = install_root / "library" / "local" / "openclaw-workspace" / "skills" / "custom-skill" / "SKILL.md"
    assert second.migrations[0].migrated_count == 1
    assert "description: v2" in library_skill.read_text(encoding="utf-8")


def test_openclaw_remote_first_router_uses_token_env_without_raw_token(tmp_path: Path, monkeypatch) -> None:
    repo_root = make_repo(tmp_path / "repo")
    openclaw_home = tmp_path / ".openclaw"
    workspace_root = openclaw_home / "workspace"
    install_root = tmp_path / ".unlimited-skills"
    write_skill(workspace_root / "skills", "redmine")

    def fake_sources(openclaw_home_arg, workspace_root_arg, include_builtin, include_plugin_skills):
        return [("openclaw-workspace", workspace_root_arg / "skills")]

    monkeypatch.setattr(openclaw, "_openclaw_sources", fake_sources)

    report = install_openclaw(
        OpenClawInstallOptions(
            openclaw_home=openclaw_home,
            workspace_root=workspace_root,
            install_root=install_root,
            repo_root=repo_root,
            include_builtin=False,
            include_plugin_skills=False,
            skip_reindex=True,
            remote=RemoteHubInstallOptions(
                remote_first=True,
                remote_hub_url="http://127.0.0.1:8766",
                hub_token_env="ULS_HUB_TOKEN",
                remote_fallback="hub_required",
            ),
        )
    )

    router_text = (workspace_root / "skills" / "unlimited-skills" / "SKILL.md").read_text(encoding="utf-8")
    remote_config = json.loads((install_root / "remote.json").read_text(encoding="utf-8"))
    assert report.remote_first is True
    assert "remote resolve" in router_text
    assert "--agent openclaw" in router_text
    assert "hub_required" in router_text
    assert "ULS_HUB_TOKEN" in router_text
    assert remote_config["token_env"] == "ULS_HUB_TOKEN"
    assert "token" not in remote_config
