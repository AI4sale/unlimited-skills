from __future__ import annotations

from pathlib import Path

from unlimited_skills.adapters import import_skill_dirs
from unlimited_skills.cli import main
from unlimited_skills.frontmatter import load_frontmatter, split_frontmatter


def write_skill(root: Path, name: str, description: str = "a skill", body: str = "Body.") -> Path:
    skill_dir = root / name
    skill_dir.mkdir(parents=True, exist_ok=True)
    (skill_dir / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: {description}\n---\n\n# {name}\n\n{body}\n",
        encoding="utf-8",
    )
    return skill_dir


# --- frontmatter ---------------------------------------------------------

def test_load_frontmatter_handles_colon_in_value() -> None:
    meta, body = load_frontmatter("---\nname: x\nsource: https://example.com/a:b\n---\nbody")
    assert meta["source"] == "https://example.com/a:b"
    assert body == "body"


def test_split_frontmatter_flattens_list_and_drops_nested_map() -> None:
    text = "---\nname: x\nallowed-tools:\n  - Read\n  - Edit\nmetadata:\n  type: user\n---\nbody"
    meta, _ = split_frontmatter(text)
    # list flattened to a joined string; nested map dropped from the flat view
    assert "Read" in meta.get("allowed-tools", "")
    assert "metadata" not in meta or meta["metadata"] == ""


def test_split_frontmatter_no_frontmatter_returns_empty() -> None:
    meta, body = split_frontmatter("# just a heading\n\ntext")
    assert meta == {}
    assert body.startswith("# just a heading")


# --- import-dir dedup ----------------------------------------------------

def test_import_dir_imports_new_skills(tmp_path: Path) -> None:
    source = tmp_path / "src"
    write_skill(source, "alpha")
    write_skill(source, "beta")
    library = tmp_path / "library"

    report = import_skill_dirs(source, library, "vendor")

    assert sorted(report.imported) == ["alpha", "beta"]
    assert report.conflicts == []
    assert (library / "local" / "vendor" / "skills" / "alpha" / "SKILL.md").is_file()


def test_import_dir_skips_identical_on_reimport(tmp_path: Path) -> None:
    source = tmp_path / "src"
    write_skill(source, "alpha")
    library = tmp_path / "library"

    import_skill_dirs(source, library, "vendor")
    second = import_skill_dirs(source, library, "vendor")

    assert second.imported == []
    assert second.skipped_identical == ["alpha"]
    assert second.conflicts == []


def test_import_dir_reports_conflict_on_same_name_different_content(tmp_path: Path) -> None:
    source_a = tmp_path / "a"
    write_skill(source_a, "alpha", description="first")
    library = tmp_path / "library"
    import_skill_dirs(source_a, library, "vendor")

    source_b = tmp_path / "b"
    write_skill(source_b, "alpha", description="second different content")
    report = import_skill_dirs(source_b, library, "other")

    assert report.imported == []
    assert len(report.conflicts) == 1
    assert report.conflicts[0].name == "alpha"
    assert (library / "local" / "other" / "duplicates" / "alpha" / "SKILL.md").is_file()


def test_import_dir_dry_run_writes_nothing(tmp_path: Path) -> None:
    source = tmp_path / "src"
    write_skill(source, "alpha")
    library = tmp_path / "library"

    report = import_skill_dirs(source, library, "vendor", dry_run=True)

    assert report.imported == ["alpha"]
    assert report.dry_run is True
    assert not (library / "local" / "vendor").exists()


def test_cli_import_dir_command(tmp_path: Path, capsys) -> None:
    source = tmp_path / "src"
    write_skill(source, "alpha")
    library = tmp_path / "library"

    exit_code = main(["--root", str(library), "import-dir", str(source), "--collection", "vendor", "--json"])

    assert exit_code == 0
    assert (library / "local" / "vendor" / "skills" / "alpha" / "SKILL.md").is_file()
    assert '"imported"' in capsys.readouterr().out
