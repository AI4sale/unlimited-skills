from __future__ import annotations

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
    mirrored = root / "hermes" / "skills" / "native-review" / "SKILL.md"
    assert mirrored.is_file()
    assert mirrored.read_text(encoding="utf-8") == (source_skill / "SKILL.md").read_text(encoding="utf-8")


def test_search_auto_syncs_native_hermes_skills(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / ".hermes"))
    write_skill(tmp_path / ".hermes" / "skills", "native-review", "review native code")
    root = tmp_path / ".unlimited-skills" / "library"

    exit_code = main(["--root", str(root), "search", "native review", "--mode", "lexical", "--native-agent", "hermes"])

    output = capsys.readouterr().out
    assert exit_code == 0
    assert "native-review [hermes]" in output
    assert (root / "hermes" / "skills" / "native-review" / "SKILL.md").is_file()


def test_sync_native_sources_mirrors_claude_personal_and_project_skills(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("CLAUDE_HOME", str(tmp_path / ".claude-home"))
    monkeypatch.setenv("UNLIMITED_SKILLS_CLAUDE_PROJECT_ROOT", str(tmp_path / "project"))
    write_skill(tmp_path / ".claude-home" / "skills", "personal-skill", "personal Claude Code skill")
    write_skill(tmp_path / "project" / ".claude" / "skills", "project-skill", "project Claude Code skill")
    root = tmp_path / ".unlimited-skills" / "library"

    results = sync_native_sources(root, agents=["claude-code"])

    assert [item.collection for item in results] == ["claude-code", "claude-code-project"]
    assert [item.imported_count for item in results] == [1, 1]
    assert (root / "claude-code" / "skills" / "personal-skill" / "SKILL.md").is_file()
    assert (root / "claude-code-project" / "skills" / "project-skill" / "SKILL.md").is_file()
