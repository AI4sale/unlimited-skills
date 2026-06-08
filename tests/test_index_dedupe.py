from __future__ import annotations

import json
from pathlib import Path

from unlimited_skills.cli import save_index


def write_skill(path: Path, name: str, description: str) -> None:
    path.mkdir(parents=True, exist_ok=True)
    (path / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: {description}\n---\n\n# {name}\n",
        encoding="utf-8",
    )


def test_index_deduplicates_skill_names_with_local_priority(tmp_path: Path) -> None:
    root = tmp_path / "library"
    write_skill(root / "registry" / "ecc" / "skills" / "review" / "security-review", "security-review", "registry copy")
    write_skill(root / "local" / "skills" / "security-review", "security-review", "local copy")
    write_skill(root / "registry" / "superpowers" / "skills" / "debug", "systematic-debugging", "debug")

    index = json.loads(save_index(root).read_text(encoding="utf-8"))

    assert [row["name"] for row in index] == ["security-review", "systematic-debugging"]
    security = next(row for row in index if row["name"] == "security-review")
    assert security["collection"] == "local"
    assert "local copy" in security["description"]
