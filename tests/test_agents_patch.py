from __future__ import annotations

from pathlib import Path

from unlimited_skills.agents_patch import patch_agents_file, patch_agents_text


UNLIMITED_BLOCK = "\n".join(
    [
        "<!-- BEGIN UNLIMITED SKILLS -->",
        "## Unlimited Skills Library",
        "",
        "Before doing substantive work, check whether Unlimited Skills has a relevant skill.",
        "<!-- END UNLIMITED SKILLS -->",
    ]
)


def test_patch_agents_text_replaces_ecc_block() -> None:
    text = "\ufeff<!-- BEGIN ECC -->\n# Everything Claude Code\nold skills\n<!-- END ECC -->\n"

    patched = patch_agents_text(text, UNLIMITED_BLOCK)

    assert "<!-- BEGIN ECC -->" not in patched
    assert "Everything Claude Code" not in patched
    assert "<!-- BEGIN UNLIMITED SKILLS -->" in patched
    assert "Before doing substantive work" in patched


def test_patch_agents_text_replaces_existing_unlimited_and_removes_ecc() -> None:
    text = "\n".join(
        [
            "<!-- BEGIN ECC -->",
            "old ECC",
            "<!-- END ECC -->",
            "",
            "<!-- BEGIN UNLIMITED SKILLS -->",
            "old Unlimited",
            "<!-- END UNLIMITED SKILLS -->",
        ]
    )

    patched = patch_agents_text(text, UNLIMITED_BLOCK)

    assert "old ECC" not in patched
    assert "old Unlimited" not in patched
    assert patched.count("<!-- BEGIN UNLIMITED SKILLS -->") == 1


def test_patch_agents_file_creates_agents_md_backup(tmp_path: Path) -> None:
    agents_file = tmp_path / "AGENTS.md"
    agents_file.write_text("<!-- BEGIN ECC -->\nold\n<!-- END ECC -->\n", encoding="utf-8")

    backup = patch_agents_file(agents_file, UNLIMITED_BLOCK)

    assert backup is not None
    assert backup.name.startswith("Agents_md_")
    assert backup.name.endswith(".back")
    assert "old" in backup.read_text(encoding="utf-8")
    assert "<!-- BEGIN UNLIMITED SKILLS -->" in agents_file.read_text(encoding="utf-8")


def test_patch_agents_file_does_not_backup_when_content_is_unchanged(tmp_path: Path) -> None:
    agents_file = tmp_path / "AGENTS.md"
    patch_agents_file(agents_file, UNLIMITED_BLOCK)

    backup = patch_agents_file(agents_file, UNLIMITED_BLOCK)

    assert backup is None
    assert list(tmp_path.glob("Agents_md_*.back")) == []
