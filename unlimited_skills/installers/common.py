"""Installer helpers for moving agent-visible skills behind Unlimited Skills."""

from __future__ import annotations

import json
import shutil
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

IGNORED_DIR_NAMES = {
    ".chroma-skills",
    ".git",
    ".learning",
    "duplicates",
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
        if any(part in excluded for part in rel.parts):
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


@dataclass
class MigrationResult:
    collection: str
    source_root: str
    migrated_count: int
    skipped: bool = False
    reason: str = ""


def existing_skill_names(library_root: Path, exclude_target: Path | None = None) -> set[str]:
    if not library_root.is_dir():
        return set()
    names = set()
    exclude_target_resolved = exclude_target.resolve() if exclude_target else None
    for path in library_root.rglob("SKILL.md"):
        if exclude_target_resolved:
            try:
                resolved = path.resolve()
            except OSError:
                resolved = path
            if resolved == exclude_target_resolved or exclude_target_resolved in resolved.parents:
                continue
        if "duplicates" in path.relative_to(library_root).parts:
            continue
        names.add(path.parent.name)
    return names


def migrate_source(
    source_root: Path,
    library_root: Path,
    collection: str,
    *,
    exclude_names: set[str] | None = None,
    skip_existing_names: bool = True,
    registry_collection: bool = False,
    transaction: "InstallTransaction | None" = None,
) -> MigrationResult:
    source_root = Path(source_root).expanduser()
    if not source_root.is_dir():
        return MigrationResult(collection=collection, source_root=str(source_root), migrated_count=0, skipped=True, reason="source root not found")

    target_skills = library_root / ("registry" if registry_collection else "local") / collection / "skills"
    existing = existing_skill_names(library_root, exclude_target=target_skills) if skip_existing_names else set()
    excluded = exclude_names or set()
    migrated = 0
    for skill_dir in iter_skill_dirs(source_root, exclude_names=excluded):
        if skip_existing_names and skill_dir.name in existing:
            continue
        relative = skill_dir.relative_to(source_root)
        destination = target_skills / relative
        if transaction is not None:
            transaction.stage_dir_replace(destination)
        copy_skill_tree(skill_dir, destination)
        existing.add(skill_dir.name)
        migrated += 1
    return MigrationResult(collection=collection, source_root=str(source_root), migrated_count=migrated)


MANIFEST_NAME = "manifest.json"
MANIFEST_SCHEMA_VERSION = 2


@dataclass
class InstallRollbackReport:
    manifest: str
    agent: str
    dry_run: bool
    restored_count: int
    actions_total: int
    messages: list[str] = field(default_factory=list)

    def format_text(self) -> str:
        lines = [
            f"{self.agent or 'Unlimited Skills'} install rollback report",
            "",
            f"Manifest: {self.manifest}",
            f"Dry run: {'yes' if self.dry_run else 'no'}",
            f"Restored skills: {self.restored_count}",
            f"Actions undone: {self.actions_total}",
        ]
        if self.messages:
            lines.extend(["", "Messages:"])
            lines.extend(f"  - {message}" for message in self.messages)
        return "\n".join(lines)


def _delete_path(path: Path) -> None:
    if path.is_dir() and not path.is_symlink():
        shutil.rmtree(path, ignore_errors=True)
    elif path.exists() or path.is_symlink():
        try:
            path.unlink()
        except OSError:
            pass


def _undo_actions(actions: list[dict], messages: list[str]) -> int:
    """Replay recorded actions in reverse order. Returns the number of restored skill moves."""
    restored = 0
    for action in reversed(actions):
        kind = str(action.get("kind") or "")
        path = Path(str(action.get("path") or ""))
        backup = str(action.get("backup") or "")
        if not str(path):
            continue
        if kind == "created_path":
            _delete_path(path)
        elif kind in {"dir_replaced", "skill_moved", "file_snapshot"}:
            if not backup:
                if kind == "file_snapshot" and not action.get("existed"):
                    _delete_path(path)
                continue
            backup_path = Path(backup)
            if not backup_path.exists():
                messages.append(f"Backup missing, cannot restore: {path}")
                continue
            _delete_path(path)
            path.parent.mkdir(parents=True, exist_ok=True)
            if kind == "file_snapshot":
                shutil.copy2(backup_path, path)
            else:
                shutil.move(str(backup_path), str(path))
            if kind == "skill_moved":
                restored += 1
    return restored


class InstallTransaction:
    """Records reversible filesystem actions while an installer applies changes.

    Every destructive step backs up prior state under *backup_root* first, so a
    failed install can be undone in-process (``rollback_now``) and a completed
    install can be undone later from the written manifest (``rollback_install``).
    """

    def __init__(self, agent: str, install_root: Path, backup_root: Path | None = None) -> None:
        self.agent = agent
        self.install_root = Path(install_root)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        candidate = Path(backup_root) if backup_root else self.install_root / "backups" / f"{agent}-{stamp}"
        # Timestamps only resolve to the second; never reuse a backup area from
        # an earlier install, or its manifest and staged state would be clobbered.
        suffix = 2
        unique = candidate
        while unique.exists():
            unique = candidate.with_name(f"{candidate.name}-{suffix}")
            suffix += 1
        self.backup_root = unique
        self.actions: list[dict] = []
        self._sequence = 0

    def _next_backup(self, label: str) -> Path:
        self._sequence += 1
        return self.backup_root / "state" / f"{self._sequence:04d}-{label}"

    def snapshot_file(self, path: Path) -> None:
        """Back up a file that is about to be created or rewritten in place."""
        path = Path(path)
        action = {"kind": "file_snapshot", "path": str(path), "backup": "", "existed": path.is_file()}
        if path.is_file():
            backup = self._next_backup(path.name)
            backup.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, backup)
            action["backup"] = str(backup)
        self.actions.append(action)

    def stage_dir_replace(self, path: Path) -> None:
        """Move an existing directory aside before it gets replaced.

        After this call *path* no longer exists, so callers can copy the new
        tree directly. A missing *path* is recorded as a plain creation.
        """
        path = Path(path)
        if path.exists():
            backup = self._next_backup(path.name)
            backup.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(path), str(backup))
            self.actions.append({"kind": "dir_replaced", "path": str(path), "backup": str(backup), "existed": True})
        else:
            self.record_created(path)

    def record_created(self, path: Path) -> None:
        self.actions.append({"kind": "created_path", "path": str(Path(path)), "backup": "", "existed": False})

    def record_skill_moved(self, *, name: str, relative: str, visible_path: Path, backup_destination: Path, library_destination: Path) -> None:
        """Record a skill directory evacuated from an agent's visible root."""
        self.actions.append(
            {
                "kind": "skill_moved",
                "name": name,
                "relative": str(relative),
                "path": str(Path(visible_path)),
                "backup": str(Path(backup_destination)),
                "library_destination": str(Path(library_destination)),
                "existed": True,
            }
        )

    def write_manifest(self, extra: dict | None = None) -> Path:
        payload: dict = {
            "schema_version": MANIFEST_SCHEMA_VERSION,
            "agent": self.agent,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "backup_root": str(self.backup_root),
            "actions": self.actions,
        }
        if extra:
            payload.update(extra)
        manifest_path = self.backup_root / MANIFEST_NAME
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        manifest_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return manifest_path

    def rollback_now(self) -> list[str]:
        """Undo everything recorded so far (used when an install fails mid-way)."""
        messages: list[str] = []
        _undo_actions(self.actions, messages)
        return messages


def rollback_install(manifest: Path, apply: bool = False) -> InstallRollbackReport:
    """Restore prior state from a schema v2 install manifest."""
    manifest = Path(manifest).expanduser()
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    actions = [action for action in payload.get("actions") or [] if isinstance(action, dict)]
    messages: list[str] = [] if apply else ["Dry run. No files were changed."]
    if apply:
        restored = _undo_actions(actions, messages)
    else:
        restored = sum(1 for action in actions if action.get("kind") == "skill_moved")
    return InstallRollbackReport(
        manifest=str(manifest),
        agent=str(payload.get("agent") or ""),
        dry_run=not apply,
        restored_count=restored,
        actions_total=len(actions),
        messages=messages,
    )
