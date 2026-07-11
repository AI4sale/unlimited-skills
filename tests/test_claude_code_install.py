from __future__ import annotations

import json
from pathlib import Path

from unlimited_skills.installers.claude_code import ClaudeCodeInstallOptions, install_claude_code
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
    router = root / "skills" / "router-claude-code"
    router.mkdir(parents=True)
    (router / "SKILL.md").write_text(
        "---\nname: unlimited-skills\ndescription: test router\n---\n\n"
        "# Router\n\n"
        "{{CLAUDE_SH_LAUNCHER}}\n"
        "{{CLAUDE_PS_LAUNCHER}}\n"
        "{{UNLIMITED_SKILLS_LIBRARY_ROOT}}\n"
        "{{REMOTE_HUB_ROUTER_BLOCK}}\n",
        encoding="utf-8",
    )
    write_skill(root / "packs" / "ecc" / "skills", "security-review")
    write_skill(root / "packs" / "superpowers" / "skills", "systematic-debugging")
    hooks_dir = root / "plugin" / "hooks"
    hooks_dir.mkdir(parents=True)
    for script in ("_cli_resolve.py", "session_start.py", "user_prompt_submit.py", "pre_compact.py", "stop.py"):
        (hooks_dir / script).write_text(f"# stub {script}\n", encoding="utf-8")
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
    assert report.global_claude_patched is True
    assert report.lexical_index == "rebuilt"
    assert (router_target / "scripts" / "unlimited-skills.sh").is_file()
    assert (router_target / "scripts" / "unlimited-skills.ps1").is_file()
    assert (project_root / "CLAUDE.md").is_file()

    shell_launcher = (router_target / "scripts" / "unlimited-skills.sh").read_text(encoding="utf-8")
    ps_launcher = (router_target / "scripts" / "unlimited-skills.ps1").read_text(encoding="utf-8")
    assert "UNLIMITED_SKILLS_CLAUDE_PROJECT_ROOT" in shell_launcher
    assert project_root.as_posix() in shell_launcher
    assert "UNLIMITED_SKILLS_HOME" in shell_launcher
    assert install_root.as_posix() in shell_launcher
    assert "UNLIMITED_SKILLS_CLAUDE_PROJECT_ROOT" in ps_launcher
    assert json.dumps(str(project_root)) in ps_launcher
    assert "UNLIMITED_SKILLS_HOME" in ps_launcher
    assert json.dumps(str(install_root)) in ps_launcher

    router_text = (router_target / "SKILL.md").read_text(encoding="utf-8")
    assert "{{CLAUDE_SH_LAUNCHER}}" not in router_text
    assert "{{CLAUDE_PS_LAUNCHER}}" not in router_text
    assert "scripts/unlimited-skills.sh" in router_text
    assert "scripts/unlimited-skills.ps1" in router_text

    claude_text = (project_root / "CLAUDE.md").read_text(encoding="utf-8")
    assert "<!-- BEGIN UNLIMITED SKILLS -->" in claude_text
    assert 'suggest "<3-8 keyword phase summary>" --json --card --limit 1' in claude_text
    assert "PHASE FRESHNESS" in claude_text
    assert "for that same phase" in claude_text
    assert "TRIGGERS (any one suffices):" in claude_text
    assert "SKIP only when a relevant skill is already active" in claude_text
    assert "scripts/unlimited-skills.sh" in claude_text
    assert "scripts/unlimited-skills.ps1" in claude_text

    global_claude_text = (claude_home / "CLAUDE.md").read_text(encoding="utf-8")
    assert "<!-- BEGIN UNLIMITED SKILLS -->" in global_claude_text
    assert "scripts/unlimited-skills.sh" in global_claude_text

    settings = json.loads((claude_home / "settings.json").read_text(encoding="utf-8"))
    assert report.hooks_registered is True
    for event, script in (
        ("SessionStart", "session_start.py"),
        ("UserPromptSubmit", "user_prompt_submit.py"),
        ("PreCompact", "pre_compact.py"),
        ("Stop", "stop.py"),
    ):
        commands = [hook["command"] for entry in settings["hooks"][event] for hook in entry["hooks"]]
        assert any(script in command for command in commands), event
    hooks_dir = router_target / "hooks"
    for script in ("_cli_resolve.py", "session_start.py", "user_prompt_submit.py", "pre_compact.py", "stop.py"):
        assert (hooks_dir / script).is_file()

    assert (library / "registry" / "ecc" / "skills" / "security-review" / "SKILL.md").is_file()
    assert (library / "registry" / "superpowers" / "skills" / "systematic-debugging" / "SKILL.md").is_file()
    assert (library / "local" / "claude-code" / "skills" / "article-writing" / "SKILL.md").is_file()
    assert not (library / "local" / "claude-code" / "skills" / "unlimited-skills" / "SKILL.md").exists()
    assert (library / "local" / "claude-code-project" / "skills" / "project-checklist" / "SKILL.md").is_file()
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
            patch_global_claude=False,
            include_project_skills=False,
            skip_reindex=True,
        )
    )

    assert report.claude_patched is False
    assert report.global_claude_patched is False
    assert not (project_root / "CLAUDE.md").exists()
    assert not (claude_home / "CLAUDE.md").exists()
    assert (claude_home / "skills" / "unlimited-skills" / "SKILL.md").is_file()
    assert (install_root / "library" / "local" / "claude-code" / "skills" / "article-writing" / "SKILL.md").is_file()
    assert not (install_root / "library" / "local" / "claude-code-project").exists()


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

    library_skill = install_root / "library" / "local" / "claude-code" / "skills" / "custom-skill" / "SKILL.md"
    assert second.migrations[0].migrated_count == 1
    assert "description: v2" in library_skill.read_text(encoding="utf-8")


def test_claude_code_install_patches_global_claude_even_when_same_as_project_file(tmp_path: Path) -> None:
    repo_root = make_repo(tmp_path / "repo")
    claude_home = tmp_path / ".claude-home"
    project_root = tmp_path / "project"
    install_root = tmp_path / ".unlimited-skills"

    report = install_claude_code(
        ClaudeCodeInstallOptions(
            claude_home=claude_home,
            project_root=project_root,
            install_root=install_root,
            repo_root=repo_root,
            claude_file=claude_home / "CLAUDE.md",
            skip_reindex=True,
        )
    )

    assert report.claude_patched is True
    assert report.global_claude_patched is True
    text = (claude_home / "CLAUDE.md").read_text(encoding="utf-8")
    assert text.count("<!-- BEGIN UNLIMITED SKILLS -->") == 1


def test_claude_code_install_hooks_can_be_skipped_and_merge_is_idempotent(tmp_path: Path) -> None:
    repo_root = make_repo(tmp_path / "repo")
    claude_home = tmp_path / ".claude-home"
    project_root = tmp_path / "project"
    install_root = tmp_path / ".unlimited-skills"

    options = ClaudeCodeInstallOptions(
        claude_home=claude_home,
        project_root=project_root,
        install_root=install_root,
        repo_root=repo_root,
        register_hooks=False,
        skip_reindex=True,
    )
    report = install_claude_code(options)
    assert report.hooks_registered is False
    assert not (claude_home / "settings.json").exists()

    # Pre-existing user settings survive, and re-installs do not duplicate entries.
    (claude_home / "settings.json").write_text(
        json.dumps({"enabledPlugins": {"other@other": True}, "hooks": {"SessionStart": [{"hooks": [{"type": "command", "command": "echo hi"}]}]}}),
        encoding="utf-8",
    )
    options.register_hooks = True
    install_claude_code(options)
    install_claude_code(options)
    settings = json.loads((claude_home / "settings.json").read_text(encoding="utf-8"))
    assert settings["enabledPlugins"] == {"other@other": True}
    session_start_commands = [hook["command"] for entry in settings["hooks"]["SessionStart"] for hook in entry["hooks"]]
    assert session_start_commands.count("echo hi") == 1
    assert sum("session_start.py" in command for command in session_start_commands) == 1
    prompt_commands = [hook["command"] for entry in settings["hooks"]["UserPromptSubmit"] for hook in entry["hooks"]]
    assert sum("user_prompt_submit.py" in command for command in prompt_commands) == 1
    precompact_commands = [hook["command"] for entry in settings["hooks"]["PreCompact"] for hook in entry["hooks"]]
    assert sum("pre_compact.py" in command for command in precompact_commands) == 1
    stop_commands = [hook["command"] for entry in settings["hooks"]["Stop"] for hook in entry["hooks"]]
    assert sum("stop.py" in command for command in stop_commands) == 1


def test_claude_code_install_hooks_fail_soft_on_invalid_settings(tmp_path: Path) -> None:
    repo_root = make_repo(tmp_path / "repo")
    claude_home = tmp_path / ".claude-home"
    claude_home.mkdir(parents=True)
    (claude_home / "settings.json").write_text("{not json", encoding="utf-8")

    report = install_claude_code(
        ClaudeCodeInstallOptions(
            claude_home=claude_home,
            project_root=tmp_path / "project",
            install_root=tmp_path / ".unlimited-skills",
            repo_root=repo_root,
            skip_reindex=True,
        )
    )
    assert report.hooks_registered is False
    assert any("not valid JSON" in message for message in report.messages)
    # The broken file is left untouched, never overwritten.
    assert (claude_home / "settings.json").read_text(encoding="utf-8") == "{not json"


def test_claude_code_remote_first_router_config_uses_token_env(tmp_path: Path) -> None:
    repo_root = make_repo(tmp_path / "repo")
    claude_home = tmp_path / ".claude-home"
    project_root = tmp_path / "project"
    install_root = tmp_path / ".unlimited-skills"

    report = install_claude_code(
        ClaudeCodeInstallOptions(
            claude_home=claude_home,
            project_root=project_root,
            install_root=install_root,
            repo_root=repo_root,
            skip_reindex=True,
            remote=RemoteHubInstallOptions(
                remote_first=True,
                remote_hub_url="http://127.0.0.1:8766",
                hub_token_env="ULS_HUB_TOKEN",
                remote_fallback="hub_required",
            ),
        )
    )

    router_text = (claude_home / "skills" / "unlimited-skills" / "SKILL.md").read_text(encoding="utf-8")
    remote_config = json.loads((install_root / "remote.json").read_text(encoding="utf-8"))
    assert report.remote_first is True
    assert "remote resolve" in router_text
    assert "--agent claude-code" in router_text
    assert "hub_required" in router_text
    assert "ULS_HUB_TOKEN" in router_text
    assert remote_config["token_env"] == "ULS_HUB_TOKEN"
    assert "token" not in remote_config


def test_claude_code_remote_first_redacts_raw_token_from_visible_outputs(tmp_path: Path) -> None:
    repo_root = make_repo(tmp_path / "repo")
    claude_home = tmp_path / ".claude-home"
    project_root = tmp_path / "project"
    install_root = tmp_path / ".unlimited-skills"
    raw_token = "uls_hub_raw_secret_for_test"

    report = install_claude_code(
        ClaudeCodeInstallOptions(
            claude_home=claude_home,
            project_root=project_root,
            install_root=install_root,
            repo_root=repo_root,
            skip_reindex=True,
            remote=RemoteHubInstallOptions(
                remote_first=True,
                remote_hub_url="http://127.0.0.1:8766",
                hub_token=raw_token,
                remote_fallback="local_allowed",
            ),
        )
    )

    router_text = (claude_home / "skills" / "unlimited-skills" / "SKILL.md").read_text(encoding="utf-8")
    report_text = report.format_text()
    remote_config = json.loads((install_root / "remote.json").read_text(encoding="utf-8"))
    assert raw_token not in router_text
    assert raw_token not in report_text
    assert remote_config["token"] == raw_token
    assert report.remote_token_source == "private remote.json"
