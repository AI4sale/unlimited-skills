from __future__ import annotations

from pathlib import Path

from unlimited_skills.installers.hermes import HermesInstallOptions, install_hermes, rollback_hermes


ROOT = Path(__file__).resolve().parents[1]


def write_skill(root: Path, name: str) -> None:
    skill_dir = root / name
    skill_dir.mkdir(parents=True, exist_ok=True)
    (skill_dir / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: {name}\n---\n\n# {name}\n",
        encoding="utf-8",
    )


def test_hermes_rollback_restores_evacuated_visible_skills(tmp_path: Path) -> None:
    hermes_home = tmp_path / ".hermes"
    visible_root = hermes_home / "skills"
    install_root = tmp_path / ".unlimited-skills"
    write_skill(visible_root, "alpha")
    write_skill(visible_root, "beta")

    install_report = install_hermes(
        HermesInstallOptions(
            hermes_home=hermes_home,
            install_root=install_root,
            repo_root=ROOT,
            mode="evacuate-visible-skills",
            apply=True,
            skip_reindex=True,
        )
    )

    assert install_report.rollback_manifest is not None
    assert sorted(p.parent.name for p in visible_root.rglob("SKILL.md")) == ["unlimited-skills"]

    rollback_report = rollback_hermes(Path(install_report.rollback_manifest), apply=True)

    assert rollback_report.restored_count == 2
    assert rollback_report.removed_router is True
    assert sorted(p.parent.name for p in visible_root.rglob("SKILL.md")) == ["alpha", "beta"]
    assert not (visible_root / "unlimited-skills").exists()


def test_hermes_rollback_dry_run_does_not_change_visible_skills(tmp_path: Path) -> None:
    hermes_home = tmp_path / ".hermes"
    visible_root = hermes_home / "skills"
    install_root = tmp_path / ".unlimited-skills"
    write_skill(visible_root, "alpha")

    install_report = install_hermes(
        HermesInstallOptions(
            hermes_home=hermes_home,
            install_root=install_root,
            repo_root=ROOT,
            mode="evacuate-visible-skills",
            apply=True,
            skip_reindex=True,
        )
    )

    assert install_report.rollback_manifest is not None
    rollback_report = rollback_hermes(Path(install_report.rollback_manifest), apply=False)

    assert rollback_report.dry_run is True
    assert rollback_report.restored_count == 1
    assert sorted(p.parent.name for p in visible_root.rglob("SKILL.md")) == ["unlimited-skills"]
