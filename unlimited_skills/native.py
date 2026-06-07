from __future__ import annotations

import os
import shutil
from dataclasses import asdict, dataclass
from pathlib import Path

from .installers.common import copy_skill_tree, iter_skill_dirs


ROUTER_NAME = "unlimited-skills"
DEFAULT_AGENT_ORDER = ("codex", "claude-code", "hermes", "openclaw")


@dataclass(frozen=True)
class NativeSource:
    agent: str
    collection: str
    root: Path

    def to_json(self) -> dict[str, str]:
        payload = asdict(self)
        payload["root"] = str(self.root)
        return payload


@dataclass(frozen=True)
class NativeSyncResult:
    agent: str
    collection: str
    source_root: str
    imported_count: int
    skipped: bool = False
    reason: str = ""


def _home_path(*parts: str) -> Path:
    return Path.home().joinpath(*parts)


def _codex_home() -> Path:
    return Path(os.environ.get("CODEX_HOME") or _home_path(".codex"))


def _claude_home() -> Path:
    return Path(os.environ.get("CLAUDE_HOME") or _home_path(".claude"))


def _claude_project_root() -> Path | None:
    value = os.environ.get("UNLIMITED_SKILLS_CLAUDE_PROJECT_ROOT") or os.environ.get("CLAUDE_PROJECT_DIR") or ""
    return Path(value).expanduser() if value else None


def _hermes_home() -> Path:
    return Path(os.environ.get("HERMES_HOME") or _home_path(".hermes"))


def _openclaw_home() -> Path:
    return Path(os.environ.get("OPENCLAW_HOME") or _home_path(".openclaw"))


def _openclaw_workspace(openclaw_home: Path) -> Path:
    return Path(os.environ.get("OPENCLAW_WORKSPACE") or openclaw_home / "workspace")


def native_sources(agent: str = "") -> list[NativeSource]:
    """Return native agent skill roots that Unlimited Skills can mirror into the library."""
    wanted = {agent} if agent else set(DEFAULT_AGENT_ORDER)
    sources: list[NativeSource] = []
    if "codex" in wanted:
        sources.append(NativeSource("codex", "codex", _codex_home() / "skills"))
    if "claude-code" in wanted or "claude" in wanted:
        sources.append(NativeSource("claude-code", "claude-code", _claude_home() / "skills"))
        claude_project_root = _claude_project_root()
        if claude_project_root is not None:
            sources.append(NativeSource("claude-code", "claude-code-project", claude_project_root / ".claude" / "skills"))
    if "hermes" in wanted:
        sources.append(NativeSource("hermes", "hermes", _hermes_home() / "skills"))
    if "openclaw" in wanted:
        openclaw_home = _openclaw_home()
        sources.extend(
            [
                NativeSource("openclaw", "openclaw-workspace", _openclaw_workspace(openclaw_home) / "skills"),
                NativeSource("openclaw", "openclaw-plugin", openclaw_home / "plugin-skills"),
                NativeSource("openclaw", "openclaw-plugin", Path("/usr/local/lib/node_modules/openclaw/dist/extensions/browser/skills")),
                NativeSource("openclaw", "openclaw-builtin", Path("/usr/local/lib/node_modules/openclaw/skills")),
            ]
        )
    return sources


def existing_skill_names(library_root: Path, exclude_collection: str = "") -> set[str]:
    if not library_root.is_dir():
        return set()
    names: set[str] = set()
    for path in library_root.rglob("SKILL.md"):
        try:
            collection = path.relative_to(library_root).parts[0]
        except (IndexError, ValueError):
            collection = ""
        if exclude_collection and collection == exclude_collection:
            continue
        names.add(path.parent.name)
    return names


def sync_native_source(
    library_root: Path,
    source: NativeSource,
    *,
    apply: bool = True,
    refresh_collection: bool = True,
    skip_existing_names: bool = True,
    exclude_names: set[str] | None = None,
) -> NativeSyncResult:
    source_root = Path(source.root).expanduser()
    if not source_root.is_dir():
        return NativeSyncResult(
            agent=source.agent,
            collection=source.collection,
            source_root=str(source_root),
            imported_count=0,
            skipped=True,
            reason="source root not found",
        )

    target_skills = library_root / source.collection / "skills"
    existing = existing_skill_names(library_root, exclude_collection=source.collection) if skip_existing_names else set()
    excluded = {ROUTER_NAME, *(exclude_names or set())}
    imported = 0
    for skill_dir in iter_skill_dirs(source_root, exclude_names=excluded):
        if skip_existing_names and skill_dir.name in existing:
            continue
        relative = skill_dir.relative_to(source_root)
        destination = target_skills / relative
        if apply:
            if refresh_collection and destination.exists():
                shutil.rmtree(destination)
            copy_skill_tree(skill_dir, destination)
        existing.add(skill_dir.name)
        imported += 1
    return NativeSyncResult(
        agent=source.agent,
        collection=source.collection,
        source_root=str(source_root),
        imported_count=imported,
    )


def sync_native_sources(
    library_root: Path,
    *,
    agents: list[str] | tuple[str, ...] | None = None,
    apply: bool = True,
    refresh_collection: bool = True,
) -> list[NativeSyncResult]:
    selected = agents or list(DEFAULT_AGENT_ORDER)
    results: list[NativeSyncResult] = []
    for agent in selected:
        for source in native_sources(agent):
            results.append(sync_native_source(library_root, source, apply=apply, refresh_collection=refresh_collection))
    return results
