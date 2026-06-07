from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from . import __version__
from .registration import DEFAULT_SERVICE_URL, RegistrationError, load_registration, unlimited_skills_home


MANAGED_BLOCK_MARKER = "<!-- BEGIN UNLIMITED SKILLS -->"
ROUTER_NAME = "unlimited-skills"
INDEX_NAME = ".unlimited-skills-index.json"
VECTOR_META_NAME = ".unlimited-skills-vector.json"
CHROMA_DIR_NAME = ".chroma-skills"
SUPPORTED_AGENTS = ("codex", "claude-code", "hermes", "openclaw")


def _home() -> Path:
    return Path.home()


def _env_path(name: str, fallback: Path) -> Path:
    value = os.environ.get(name) or ""
    return Path(value).expanduser() if value else fallback


def _skill_count(root: Path) -> int:
    if not root.is_dir():
        return 0
    return sum(1 for _ in root.rglob("SKILL.md"))


def _router_present(root: Path) -> bool:
    return (root / ROUTER_NAME / "SKILL.md").is_file()


def _has_managed_block(path: Path) -> bool:
    try:
        return path.is_file() and MANAGED_BLOCK_MARKER in path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False


def _library_summary(root: Path) -> dict[str, Any]:
    collections: dict[str, int] = {}
    if root.is_dir():
        for child in sorted(item for item in root.iterdir() if item.is_dir() and not item.name.startswith(".")):
            count = _skill_count(child)
            if count:
                collections[child.name] = count
    return {
        "exists": root.is_dir(),
        "collections": collections,
        "total_skills": sum(collections.values()),
        "index_present": (root / INDEX_NAME).is_file(),
        "vector_index_present": (root / CHROMA_DIR_NAME).is_dir() or (root / VECTOR_META_NAME).is_file(),
    }


def _registration_summary() -> dict[str, Any]:
    try:
        state = load_registration()
        return {
            "registered": state.registered,
            "plan": state.plan or ("registered-community" if state.registered else "community-core"),
            "server_url": state.server_url or DEFAULT_SERVICE_URL,
            "telemetry": state.telemetry or "off",
            "hosted_token": "present" if state.license_token else "missing",
        }
    except RegistrationError:
        return {
            "registered": False,
            "plan": "community-core",
            "server_url": DEFAULT_SERVICE_URL,
            "telemetry": "off",
            "hosted_token": "missing",
        }


def _codex_summary(project_root: Path) -> dict[str, Any]:
    root = _env_path("CODEX_HOME", _home() / ".codex") / "skills"
    router = _router_present(root)
    agents_file = project_root / "AGENTS.md"
    recommendations = []
    status = "ok"
    if router and not _has_managed_block(agents_file):
        status = "warn"
        recommendations.append("Codex router is installed, but the project AGENTS.md managed block is missing.")
    return {
        "status": status,
        "visible_skill_roots": [str(root)],
        "visible_skill_count": _skill_count(root),
        "router_present": router,
        "agents_file": str(agents_file),
        "agents_patch_present": _has_managed_block(agents_file),
        "recommendations": recommendations,
    }


def _claude_project_root(project_root: Path) -> Path:
    value = os.environ.get("UNLIMITED_SKILLS_CLAUDE_PROJECT_ROOT") or os.environ.get("CLAUDE_PROJECT_DIR") or ""
    return Path(value).expanduser() if value else project_root


def _claude_summary(project_root: Path) -> dict[str, Any]:
    root = _env_path("CLAUDE_HOME", _home() / ".claude") / "skills"
    router = _router_present(root)
    claude_file = _claude_project_root(project_root) / "CLAUDE.md"
    recommendations = []
    status = "ok"
    if router and not _has_managed_block(claude_file):
        status = "warn"
        recommendations.append("Claude Code router is installed, but the project CLAUDE.md managed block is missing.")
    return {
        "status": status,
        "visible_skill_roots": [str(root)],
        "visible_skill_count": _skill_count(root),
        "router_present": router,
        "claude_file": str(claude_file),
        "claude_patch_present": _has_managed_block(claude_file),
        "recommendations": recommendations,
    }


def _hermes_summary() -> dict[str, Any]:
    root = _env_path("HERMES_HOME", _home() / ".hermes") / "skills"
    count = _skill_count(root)
    router = _router_present(root)
    recommendations = []
    status = "unknown"
    context_status = "unknown"
    if root.is_dir():
        if count > 1:
            status = "warn"
            context_status = "risk"
            recommendations.append("Hermes may load visible skills into startup context. Run router-only context reduction installer or evacuate visible skills.")
        elif router:
            status = "ok"
            context_status = "ok"
        else:
            status = "warn"
            recommendations.append("Hermes skill root exists, but the Unlimited Skills router is not visible.")
    return {
        "status": status,
        "visible_skill_roots": [str(root)],
        "visible_skill_count": count,
        "router_present": router,
        "context_reduction_status": context_status,
        "recommendations": recommendations,
    }


def _openclaw_workspace() -> Path:
    openclaw_home = _env_path("OPENCLAW_HOME", _home() / ".openclaw")
    return _env_path("OPENCLAW_WORKSPACE", openclaw_home / "workspace")


def _openclaw_summary() -> dict[str, Any]:
    workspace = _openclaw_workspace()
    root = workspace / "skills"
    router = _router_present(root)
    agents_file = workspace / "AGENTS.md"
    recommendations = []
    status = "ok"
    if router and not _has_managed_block(agents_file):
        status = "warn"
        recommendations.append("OpenClaw router is installed, but the workspace AGENTS.md managed block is missing.")
    return {
        "status": status,
        "visible_skill_roots": [str(root)],
        "visible_skill_count": _skill_count(root),
        "router_present": router,
        "agents_file": str(agents_file),
        "agents_patch_present": _has_managed_block(agents_file),
        "recommendations": recommendations,
    }


def build_doctor_report(root: Path, *, agent: str = "all", project_root: Path | None = None) -> dict[str, Any]:
    selected = SUPPORTED_AGENTS if agent in {"", "all"} else (agent,)
    if any(item not in SUPPORTED_AGENTS for item in selected):
        raise RuntimeError(f"Unsupported doctor agent: {agent}")
    project = project_root or Path.cwd()
    agents: dict[str, Any] = {}
    if "codex" in selected:
        agents["codex"] = _codex_summary(project)
    if "claude-code" in selected:
        agents["claude-code"] = _claude_summary(project)
    if "hermes" in selected:
        agents["hermes"] = _hermes_summary()
    if "openclaw" in selected:
        agents["openclaw"] = _openclaw_summary()
    recommendations = []
    library = _library_summary(root)
    if not library["exists"]:
        recommendations.append("Local library root is missing. Run an installer, migration script, or `unlimited-skills reindex` after adding skills.")
    elif not library["index_present"]:
        recommendations.append("Lexical index is missing. Run `unlimited-skills reindex`.")
    for info in agents.values():
        recommendations.extend(info.get("recommendations") or [])
    return {
        "version": __version__,
        "root": str(root),
        "registration": _registration_summary(),
        "library": library,
        "agents": agents,
        "recommendations": recommendations,
    }


def format_doctor_text(report: dict[str, Any]) -> str:
    registration = report["registration"]
    library = report["library"]
    lines = [
        "Unlimited Skills doctor",
        f"Version: {report['version']}",
        f"Root: {report['root']}",
        "Registered: " + ("yes" if registration["registered"] else "no"),
        f"Plan: {registration['plan']}",
        f"Server: {registration['server_url']}",
        f"Telemetry: {registration['telemetry']}",
        f"Hosted token: {registration['hosted_token']}",
        f"Local skills: {library['total_skills']}",
        "Lexical index: " + ("present" if library["index_present"] else "missing"),
        "Vector index: " + ("present" if library["vector_index_present"] else "missing"),
    ]
    for agent, info in report["agents"].items():
        lines.append(f"{agent}: {info.get('status', 'unknown')}")
        lines.append(f"  visible skills: {info.get('visible_skill_count', 0)}")
        lines.append("  router: " + ("present" if info.get("router_present") else "missing"))
        if agent == "hermes":
            lines.append(f"  context reduction: {info.get('context_reduction_status', 'unknown')}")
    lines.append("Recommendations:")
    if report["recommendations"]:
        lines.extend(f"  - {item}" for item in report["recommendations"])
    else:
        lines.append("  - none")
    return "\n".join(lines)


def doctor_json(report: dict[str, Any]) -> str:
    return json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True)


def default_library_root() -> Path:
    return unlimited_skills_home() / "library"
