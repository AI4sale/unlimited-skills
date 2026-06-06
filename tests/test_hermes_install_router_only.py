from __future__ import annotations

import json
from pathlib import Path

from unlimited_skills.installers.hermes import HermesInstallOptions, count_visible_skills, install_hermes


ROOT = Path(__file__).resolve().parents[1]


def write_skill(root: Path, name: str, description: str = "test skill") -> Path:
    skill_dir = root / name
    skill_dir.mkdir(parents=True, exist_ok=True)
    (skill_dir / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: {description}\n---\n\n# {name}\n",
        encoding="utf-8",
    )
    return skill_dir


def test_hermes_install_evacuates_visible_skills_and_leaves_only_router(tmp_path: Path) -> None:
    hermes_home = tmp_path / ".hermes"
    visible_root = hermes_home / "skills"
    install_root = tmp_path / ".unlimited-skills"
    write_skill(visible_root, "alpha")
    write_skill(visible_root / "category", "beta")

    report = install_hermes(
        HermesInstallOptions(
            hermes_home=hermes_home,
            install_root=install_root,
            repo_root=ROOT,
            mode="evacuate-visible-skills",
            apply=True,
            skip_reindex=True,
        )
    )

    assert report.before_visible_count == 2
    assert report.migrated_count == 2
    assert report.after_visible_count == 1
    assert count_visible_skills(visible_root) == 1
    assert [p.parent.name for p in visible_root.rglob("SKILL.md")] == ["unlimited-skills"]

    assert (install_root / "library" / "hermes" / "skills" / "alpha" / "SKILL.md").is_file()
    assert (install_root / "library" / "hermes" / "skills" / "beta" / "SKILL.md").is_file()

    router = visible_root / "unlimited-skills" / "SKILL.md"
    router_text = router.read_text(encoding="utf-8")
    assert ".hermes" in router_text
    assert ".codex" not in router_text
    assert "scripts/unlimited-skills.sh" in router_text

    launcher = visible_root / "unlimited-skills" / "scripts" / "unlimited-skills.sh"
    assert launcher.is_file()
    launcher_text = launcher.read_text(encoding="utf-8")
    assert (install_root / "library").as_posix() in launcher_text

    assert report.rollback_manifest is not None
    manifest = json.loads(Path(report.rollback_manifest).read_text(encoding="utf-8"))
    assert manifest["agent"] == "hermes"
    assert manifest["visible_root"] == str(visible_root)
    assert manifest["before_visible_count"] == 2
    assert {item["name"] for item in manifest["items"]} == {"alpha", "beta"}


def test_hermes_install_dry_run_does_not_change_visible_skills(tmp_path: Path) -> None:
    hermes_home = tmp_path / ".hermes"
    visible_root = hermes_home / "skills"
    install_root = tmp_path / ".unlimited-skills"
    write_skill(visible_root, "alpha")

    report = install_hermes(
        HermesInstallOptions(
            hermes_home=hermes_home,
            install_root=install_root,
            repo_root=ROOT,
            mode="evacuate-visible-skills",
            apply=False,
            skip_reindex=True,
        )
    )

    assert report.dry_run is True
    assert "Dry run. No files were changed." in report.messages
    assert count_visible_skills(visible_root) == 1
    assert (visible_root / "alpha" / "SKILL.md").is_file()
    assert not (visible_root / "unlimited-skills").exists()
    assert not (install_root / "library" / "hermes" / "skills" / "alpha").exists()


def test_hermes_install_missing_skill_root_is_explicit_not_silent(tmp_path: Path) -> None:
    hermes_home = tmp_path / ".hermes"
    install_root = tmp_path / ".unlimited-skills"

    report = install_hermes(
        HermesInstallOptions(
            hermes_home=hermes_home,
            install_root=install_root,
            repo_root=ROOT,
            mode="router-only",
            apply=True,
            skip_reindex=True,
        )
    )

    assert report.before_visible_count == 0
    assert report.migrated_count == 0
    assert "No Hermes skills found" in "\n".join(report.messages)
    assert (hermes_home / "skills" / "unlimited-skills" / "SKILL.md").is_file()
