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
    seen: set[str] = set()

    def add_skill_dir(skill_dir: Path, rel: Path) -> None:
        if should_ignore_path(rel):
            return
        if skill_dir.name in excluded:
            return
        key = str(skill_dir)
        if key in seen:
            return
        seen.add(key)
        skill_dirs.append(skill_dir)

    for skill_file in sorted(root.rglob("SKILL.md")):
        try:
            rel = skill_file.relative_to(root)
        except ValueError:
            rel = skill_file
        add_skill_dir(skill_file.parent, rel)

    for child in sorted(root.iterdir()):
        if not child.is_symlink() or not child.is_dir():
            continue
        target = child.resolve()
        if not target.is_dir():
            continue
        for skill_file in sorted(target.rglob("SKILL.md")):
            rel = skill_file.relative_to(target)
            synthetic_skill_dir = child / rel.parent
            add_skill_dir(synthetic_skill_dir, child.relative_to(root) / rel)
    return skill_dirs


def count_skill_files(root: Path) -> int:
    return len(iter_skill_dirs(root))


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
