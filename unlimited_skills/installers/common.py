"""Installer helpers for moving agent-visible skills behind Unlimited Skills."""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Iterable

IGNORED_DIR_NAMES = {
    ".chroma-skills",
    ".git",
    ".learning",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    "__pycache__",
    "node_modules",
}


def should_ignore_path(path: Path) -> bool:
    return any(part in IGNORED_DIR_NAMES for part in path.parts)


def iter_skill_dirs(root: Path, exclude_names: Iterable[str] = ()) -> list[Path]:
    """Return directories below *root* that contain a SKILL.md file."""
    excluded = set(exclude_names)
    if not root.is_dir():
        return []
    skill_dirs: list[Path] = []
    for skill_file in sorted(root.rglob("SKILL.md")):
        try:
            rel = skill_file.relative_to(root)
        except ValueError:
            rel = skill_file
        if should_ignore_path(rel):
            continue
        skill_dir = skill_file.parent
        if skill_dir.name in excluded:
            continue
        skill_dirs.append(skill_dir)
    return skill_dirs


def count_skill_files(root: Path) -> int:
    if not root.is_dir():
        return 0
    return sum(1 for skill_file in root.rglob("SKILL.md") if not should_ignore_path(skill_file.relative_to(root)))


def copy_skill_tree(source: Path, destination: Path) -> None:
    if destination.exists():
        shutil.rmtree(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(
        source,
        destination,
        ignore=shutil.ignore_patterns(*IGNORED_DIR_NAMES),
    )


def move_skill_tree(source: Path, destination: Path) -> None:
    if destination.exists():
        shutil.rmtree(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(source), str(destination))


def prune_empty_parents(start: Path, stop: Path) -> None:
    """Remove empty parent directories up to but not including *stop*."""
    current = start
    stop = stop.resolve()
    while current.exists():
        try:
            if current.resolve() == stop:
                return
        except OSError:
            return
        try:
            current.rmdir()
        except OSError:
            return
        current = current.parent
