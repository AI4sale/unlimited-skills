from __future__ import annotations

import json
import os
import re
import shutil
from dataclasses import asdict, dataclass
from pathlib import Path

from .installers.common import IGNORED_DIR_NAMES, iter_skill_dirs


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
    duplicate_count: int = 0


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


def _plugin_sync_disabled() -> bool:
    value = os.environ.get("UNLIMITED_SKILLS_DISABLE_PLUGIN_SYNC", "").strip().lower()
    return value in {"1", "true", "yes", "on"}


def _load_json_object(path: Path) -> dict:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _plugin_collection_slug(marketplace: str, plugin: str) -> str:
    raw = f"claude-code-plugin-{marketplace}-{plugin}".lower()
    slug = re.sub(r"[^a-z0-9._-]+", "-", raw).strip("-.")
    return slug[:128] or "claude-code-plugin"


def _plugin_skill_roots(plugin_root: Path) -> list[Path]:
    """Return skill roots shipped with a Claude Code plugin located at *plugin_root*.

    Order of precedence: paths declared in ``.claude-plugin/plugin.json`` under
    ``skills``, then the conventional ``skills/`` and ``.claude/skills/`` folders.
    Declared paths may not escape the plugin root.
    """
    declared: list[str] = []
    manifest = _load_json_object(plugin_root / ".claude-plugin" / "plugin.json")
    raw = manifest.get("skills")
    if isinstance(raw, str):
        declared = [raw]
    elif isinstance(raw, list):
        declared = [item for item in raw if isinstance(item, str)]

    candidates = [plugin_root / rel for rel in declared]
    candidates.extend([plugin_root / "skills", plugin_root / ".claude" / "skills"])

    try:
        root_resolved = plugin_root.resolve()
    except OSError:
        return []
    roots: list[Path] = []
    seen: set[Path] = set()
    for candidate in candidates:
        try:
            resolved = candidate.resolve()
        except OSError:
            continue
        if resolved in seen or not resolved.is_dir():
            continue
        if resolved != root_resolved and root_resolved not in resolved.parents:
            continue
        seen.add(resolved)
        roots.append(candidate)
    return roots


def _marketplace_plugin_root(plugins_root: Path, marketplace: str, plugin: str) -> Path | None:
    """Resolve a plugin root from the marketplace clone when the cache snapshot is gone."""
    known = _load_json_object(plugins_root / "known_marketplaces.json")
    entry = known.get(marketplace)
    location = entry.get("installLocation") if isinstance(entry, dict) else None
    if isinstance(location, str) and location:
        base = Path(location).expanduser()
    else:
        base = plugins_root / "marketplaces" / marketplace
    if not base.is_dir():
        return None
    manifest = _load_json_object(base / ".claude-plugin" / "marketplace.json")
    plugins = manifest.get("plugins")
    if isinstance(plugins, list):
        for item in plugins:
            if not isinstance(item, dict) or item.get("name") != plugin:
                continue
            source = item.get("source")
            if isinstance(source, str) and source:
                candidate = base / source
                try:
                    resolved = candidate.resolve()
                    base_resolved = base.resolve()
                except OSError:
                    return None
                if resolved != base_resolved and base_resolved not in resolved.parents:
                    return None
                return candidate if resolved.is_dir() else None
            break
    return base


def claude_plugin_sources(claude_home: Path | None = None) -> list[NativeSource]:
    """Discover skill roots bundled with installed Claude Code plugins.

    Claude Code keeps plugin state under ``<claude_home>/plugins``:
    ``installed_plugins.json`` (installed plugins with their cache ``installPath``),
    ``known_marketplaces.json`` (marketplace clones), and per-plugin
    ``.claude-plugin/plugin.json`` manifests. When a cache snapshot is missing
    (plugin disabled or cache pruned) the marketplace clone is used instead.
    Set ``UNLIMITED_SKILLS_DISABLE_PLUGIN_SYNC=1`` to opt out.
    """
    if _plugin_sync_disabled():
        return []
    home = claude_home if claude_home is not None else _claude_home()
    plugins_root = home / "plugins"
    installed = _load_json_object(plugins_root / "installed_plugins.json").get("plugins")
    if not isinstance(installed, dict):
        return []
    sources: list[NativeSource] = []
    seen_roots: set[Path] = set()
    for key, entries in sorted(installed.items()):
        plugin, _, marketplace = key.partition("@")
        if not plugin:
            continue
        marketplace = marketplace or "local"
        plugin_root: Path | None = None
        if isinstance(entries, list):
            for entry in entries:
                if not isinstance(entry, dict):
                    continue
                install_path = entry.get("installPath")
                if isinstance(install_path, str) and install_path and Path(install_path).is_dir():
                    plugin_root = Path(install_path)
                    break
        if plugin_root is None:
            plugin_root = _marketplace_plugin_root(plugins_root, marketplace, plugin)
        if plugin_root is None:
            continue
        collection = _plugin_collection_slug(marketplace, plugin)
        for skills_root in _plugin_skill_roots(plugin_root):
            try:
                resolved = skills_root.resolve()
            except OSError:
                continue
            if resolved in seen_roots:
                continue
            seen_roots.add(resolved)
            sources.append(NativeSource("claude-code", collection, skills_root))
    return sources


def native_sources(agent: str = "") -> list[NativeSource]:
    """Return native agent skill roots that Unlimited Skills can mirror into the library."""
    wanted = {agent} if agent else set(DEFAULT_AGENT_ORDER)
    sources: list[NativeSource] = []
    if "codex" in wanted:
        sources.append(NativeSource("codex", "local", _codex_home() / "skills"))
    if "claude-code" in wanted or "claude" in wanted:
        sources.append(NativeSource("claude-code", "claude-code", _claude_home() / "skills"))
        claude_project_root = _claude_project_root()
        if claude_project_root is not None:
            sources.append(NativeSource("claude-code", "claude-code-project", claude_project_root / ".claude" / "skills"))
        sources.extend(claude_plugin_sources())
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


def overlay_skill_tree(source: Path, destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    shutil.copytree(
        source,
        destination,
        dirs_exist_ok=True,
        ignore=shutil.ignore_patterns(*IGNORED_DIR_NAMES),
    )


def local_target_roots(library_root: Path, source: NativeSource) -> tuple[Path, Path, Path]:
    local_root = library_root / "local"
    if source.collection == "local":
        return local_root, local_root / "skills", local_root / "duplicates"
    collection_root = local_root / source.collection
    return collection_root, collection_root / "skills", collection_root / "duplicates"


def existing_skill_names(library_root: Path, exclude_root: Path | None = None) -> set[str]:
    if not library_root.is_dir():
        return set()
    names: set[str] = set()
    exclude_resolved = exclude_root.resolve() if exclude_root else None
    for path in library_root.rglob("SKILL.md"):
        rel_parts = path.relative_to(library_root).parts
        if "duplicates" in rel_parts:
            continue
        if exclude_resolved:
            try:
                resolved = path.resolve()
            except OSError:
                resolved = path
            if resolved == exclude_resolved or exclude_resolved in resolved.parents:
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

    target_root, target_skills, target_duplicates = local_target_roots(library_root, source)
    existing = existing_skill_names(library_root, exclude_root=target_root) if skip_existing_names else set()
    excluded = {ROUTER_NAME, "skill-library", *(exclude_names or set())}
    imported = 0
    duplicates = 0
    for skill_dir in iter_skill_dirs(source_root, exclude_names=excluded):
        relative = skill_dir.relative_to(source_root)
        is_duplicate = skip_existing_names and skill_dir.name in existing
        destination = (target_duplicates if is_duplicate else target_skills) / relative
        if apply:
            overlay_skill_tree(skill_dir, destination)
        if is_duplicate:
            duplicates += 1
        else:
            existing.add(skill_dir.name)
            imported += 1
    return NativeSyncResult(
        agent=source.agent,
        collection=source.collection,
        source_root=str(source_root),
        imported_count=imported,
        duplicate_count=duplicates,
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
