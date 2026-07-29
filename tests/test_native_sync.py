from __future__ import annotations

import stat
from pathlib import Path

from unlimited_skills.cli import main
from unlimited_skills.native import sync_native_sources


def write_skill(root: Path, name: str, description: str = "native skill") -> Path:
    skill_dir = root / name
    skill_dir.mkdir(parents=True, exist_ok=True)
    (skill_dir / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: {description}\n---\n\n# {name}\n\nNative body marker.\n",
        encoding="utf-8",
    )
    return skill_dir


def test_sync_native_sources_mirrors_hermes_skills(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / ".hermes"))
    source_skill = write_skill(tmp_path / ".hermes" / "skills", "native-review", "review native code")
    root = tmp_path / ".unlimited-skills" / "library"

    results = sync_native_sources(root, agents=["hermes"])

    assert results[0].collection == "hermes"
    assert results[0].imported_count == 1
    mirrored = root / "local" / "hermes" / "skills" / "native-review" / "SKILL.md"
    assert mirrored.is_file()
    assert mirrored.read_text(encoding="utf-8") == (source_skill / "SKILL.md").read_text(encoding="utf-8")


def test_search_auto_syncs_native_hermes_skills(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / ".hermes"))
    write_skill(tmp_path / ".hermes" / "skills", "native-review", "review native code")
    root = tmp_path / ".unlimited-skills" / "library"

    exit_code = main(["--root", str(root), "search", "native review", "--mode", "lexical", "--native-agent", "hermes"])

    output = capsys.readouterr().out
    assert exit_code == 0
    assert "native-review [local]" in output
    assert (root / "local" / "hermes" / "skills" / "native-review" / "SKILL.md").is_file()


def test_sync_native_sources_mirrors_claude_personal_and_project_skills(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("CLAUDE_HOME", str(tmp_path / ".claude-home"))
    monkeypatch.setenv("UNLIMITED_SKILLS_CLAUDE_PROJECT_ROOT", str(tmp_path / "project"))
    write_skill(tmp_path / ".claude-home" / "skills", "personal-skill", "personal Claude Code skill")
    write_skill(tmp_path / "project" / ".claude" / "skills", "project-skill", "project Claude Code skill")
    root = tmp_path / ".unlimited-skills" / "library"

    results = sync_native_sources(root, agents=["claude-code"])

    assert [item.collection for item in results] == ["claude-code", "claude-code-project"]
    assert [item.imported_count for item in results] == [1, 1]
    assert (root / "local" / "claude-code" / "skills" / "personal-skill" / "SKILL.md").is_file()
    assert (root / "local" / "claude-code-project" / "skills" / "project-skill" / "SKILL.md").is_file()


def test_sync_native_sources_mirrors_codex_system_skills_without_router(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / ".codex"))
    write_skill(tmp_path / ".codex" / "skills" / ".system", "skill-creator", "system skill")
    write_skill(tmp_path / ".codex" / "skills", "unlimited-skills", "router")
    root = tmp_path / ".unlimited-skills" / "library"

    results = sync_native_sources(root, agents=["codex"])

    assert results[0].collection == "local"
    assert results[0].imported_count == 1
    assert (root / "local" / "skills" / ".system" / "skill-creator" / "SKILL.md").is_file()
    assert not (root / "local" / "skills" / "unlimited-skills" / "SKILL.md").exists()


def test_sync_native_sources_never_deletes_existing_local_library_files(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / ".codex"))
    root = tmp_path / ".unlimited-skills" / "library"
    preserved = root / "local" / "skills" / "custom-pack" / "custom-skill" / "SKILL.md"
    preserved.parent.mkdir(parents=True)
    preserved.write_text("---\nname: custom-skill\ndescription: keep me\n---\n", encoding="utf-8")
    source_skill = write_skill(tmp_path / ".codex" / "skills", "native-skill", "native v1")
    extra_file = root / "local" / "skills" / "native-skill" / "notes.txt"
    extra_file.parent.mkdir(parents=True)
    extra_file.write_text("must survive overlay sync\n", encoding="utf-8")

    sync_native_sources(root, agents=["codex"])
    (source_skill / "SKILL.md").write_text(
        "---\nname: native-skill\ndescription: native v2\n---\n\n# native-skill\n",
        encoding="utf-8",
    )
    sync_native_sources(root, agents=["codex"])

    assert preserved.is_file()
    assert extra_file.is_file()
    assert "native v2" in (root / "local" / "skills" / "native-skill" / "SKILL.md").read_text(encoding="utf-8")


def test_sync_native_sources_repeats_and_updates_read_only_skills(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / ".hermes"))
    source_skill = write_skill(
        tmp_path / ".hermes" / "skills",
        "managed-skill",
        "managed v1",
    )
    source_file = source_skill / "SKILL.md"
    source_file.chmod(stat.S_IREAD)
    root = tmp_path / ".unlimited-skills" / "library"
    mirrored = (
        root
        / "local"
        / "hermes"
        / "skills"
        / "managed-skill"
        / "SKILL.md"
    )

    sync_native_sources(root, agents=["hermes"])
    sync_native_sources(root, agents=["hermes"])
    assert "managed v1" in mirrored.read_text(encoding="utf-8")

    source_file.chmod(stat.S_IWRITE | stat.S_IREAD)
    source_file.write_text(
        "---\nname: managed-skill\ndescription: managed v2\n---\n",
        encoding="utf-8",
    )
    source_file.chmod(stat.S_IREAD)
    sync_native_sources(root, agents=["hermes"])

    assert "managed v2" in mirrored.read_text(encoding="utf-8")
    assert not mirrored.stat().st_mode & stat.S_IWRITE
    source_file.chmod(stat.S_IWRITE | stat.S_IREAD)
    mirrored.chmod(stat.S_IWRITE | stat.S_IREAD)


def test_sync_native_sources_ignore_managed_backup_trees(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / ".hermes"))
    skills_root = tmp_path / ".hermes" / "skills"
    write_skill(skills_root, "active-skill", "active")
    backup = write_skill(
        skills_root / ".skills-backup-deadbeef",
        "backup-skill",
        "backup",
    )
    backup_file = backup / "SKILL.md"
    backup_file.chmod(stat.S_IREAD)
    root = tmp_path / ".unlimited-skills" / "library"

    first = sync_native_sources(root, agents=["hermes"])
    second = sync_native_sources(root, agents=["hermes"])

    assert first[0].imported_count == 1
    assert second[0].imported_count == 1
    assert (
        root
        / "local"
        / "hermes"
        / "skills"
        / "active-skill"
        / "SKILL.md"
    ).is_file()
    assert not any(
        ".skills-backup-" in str(path)
        for path in root.rglob("SKILL.md")
    )
    backup_file.chmod(stat.S_IWRITE | stat.S_IREAD)
