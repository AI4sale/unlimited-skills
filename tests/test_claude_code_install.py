from __future__ import annotations

from pathlib import Path

from unlimited_skills.installers.claude_code import ClaudeCodeInstallOptions, install_claude_code


def write_skill(root: Path, name: str, description: str = "test skill") -> Path:
    skill_dir = root / name
    skill_dir.mkdir(parents=True, exist_ok=True)
    (skill_dir / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: {description}\n---\n\n# {name}\n",
        encoding="utf-8",
    )
    return skill_dir


def make_repo(root: Path) -> Path:
    router = root / "skills" / "router-claude-code"
    router.mkdir(parents=True)
    (router / "SKILL.md").write_text(
        "---\nname: unlimited-skills\ndescription: test router\n---\n\n"
        "# Router\n\n"
        "{{CLAUDE_SH_LAUNCHER}}\n"
        "{{CLAUDE_PS_LAUNCHER}}\n"
        "{{UNLIMITED_SKILLS_LIBRARY_ROOT}}\n",
        encoding="utf-8",
    )
    write_skill(root / "packs" / "ecc" / "skills", "security-review")
    write_skill(root / "packs" / "superpowers" / "skills", "systematic-debugging")
    return root


def test_claude_code_install_bundled_imports_personal_and_project_skills(tmp_path: Path) -> None:
    repo_root = make_repo(tmp_path / "repo")
    claude_home = tmp_path / ".claude-home"
    project_root = tmp_path / "project"
    install_root = tmp_path / ".unlimited-skills"

    write_skill(claude_home / "skills", "article-writing")
    write_skill(claude_home / "skills", "unlimited-skills")
    write_skill(project_root / ".claude" / "skills", "project-checklist")

    report = install_claude_code(
        ClaudeCodeInstallOptions(
            claude_home=claude_home,
            project_root=project_root,
            install_root=install_root,
            repo_root=repo_root,
            mode="bundled",
            skip_reindex=False,
        )
    )

    library = install_root / "library"
    router_target = claude_home / "skills" / "unlimited-skills"
    assert report.router_installed is True
    assert report.claude_patched is True
    assert report.lexical_index == "rebuilt"
    assert (router_target / "scripts" / "unlimited-skills.sh").is_file()
    assert (router_target / "scripts" / "unlimited-skills.ps1").is_file()
    assert (project_root / "CLAUDE.md").is_file()

    router_text = (router_target / "SKILL.md").read_text(encoding="utf-8")
    assert "{{CLAUDE_SH_LAUNCHER}}" not in router_text
    assert "{{CLAUDE_PS_LAUNCHER}}" not in router_text
    assert "scripts/unlimited-skills.sh" in router_text
    assert "scripts/unlimited-skills.ps1" in router_text

    claude_text = (project_root / "CLAUDE.md").read_text(encoding="utf-8")
    assert "<!-- BEGIN UNLIMITED SKILLS -->" in claude_text
    assert "Claude Code's current skill listing" in claude_text
    assert "scripts/unlimited-skills.sh" in claude_text
    assert "scripts/unlimited-skills.ps1" in claude_text

    assert (library / "ecc" / "skills" / "security-review" / "SKILL.md").is_file()
    assert (library / "superpowers" / "skills" / "systematic-debugging" / "SKILL.md").is_file()
    assert (library / "claude-code" / "skills" / "article-writing" / "SKILL.md").is_file()
    assert not (library / "claude-code" / "skills" / "unlimited-skills" / "SKILL.md").exists()
    assert (library / "claude-code-project" / "skills" / "project-checklist" / "SKILL.md").is_file()
    assert (library / ".unlimited-skills-index.json").is_file()

    counts = {item.collection: item.migrated_count for item in report.migrations}
    assert counts["ecc"] == 1
    assert counts["superpowers"] == 1
    assert counts["claude-code"] == 1
    assert counts["claude-code-project"] == 1


def test_claude_code_install_can_skip_claude_patch_and_project_skills(tmp_path: Path) -> None:
    repo_root = make_repo(tmp_path / "repo")
    claude_home = tmp_path / ".claude-home"
    project_root = tmp_path / "project"
    install_root = tmp_path / ".unlimited-skills"
    write_skill(claude_home / "skills", "article-writing")
    write_skill(project_root / ".claude" / "skills", "project-checklist")

    report = install_claude_code(
        ClaudeCodeInstallOptions(
            claude_home=claude_home,
            project_root=project_root,
            install_root=install_root,
            repo_root=repo_root,
            patch_claude=False,
            include_project_skills=False,
            skip_reindex=True,
        )
    )

    assert report.claude_patched is False
    assert not (project_root / "CLAUDE.md").exists()
    assert (claude_home / "skills" / "unlimited-skills" / "SKILL.md").is_file()
    assert (install_root / "library" / "claude-code" / "skills" / "article-writing" / "SKILL.md").is_file()
    assert not (install_root / "library" / "claude-code-project").exists()


def test_claude_code_reinstall_refreshes_same_collection_skills(tmp_path: Path) -> None:
    repo_root = make_repo(tmp_path / "repo")
    claude_home = tmp_path / ".claude-home"
    project_root = tmp_path / "project"
    install_root = tmp_path / ".unlimited-skills"
    source_skill = write_skill(claude_home / "skills", "custom-skill", "v1")

    options = ClaudeCodeInstallOptions(
        claude_home=claude_home,
        project_root=project_root,
        install_root=install_root,
        repo_root=repo_root,
        include_project_skills=False,
        skip_reindex=True,
    )
    first = install_claude_code(options)
    assert first.migrations[0].migrated_count == 1

    (source_skill / "SKILL.md").write_text(
        "---\nname: custom-skill\ndescription: v2\n---\n\n# custom-skill\n",
        encoding="utf-8",
    )
    second = install_claude_code(options)

    library_skill = install_root / "library" / "claude-code" / "skills" / "custom-skill" / "SKILL.md"
    assert second.migrations[0].migrated_count == 1
    assert "description: v2" in library_skill.read_text(encoding="utf-8")
