from __future__ import annotations

import json
import os
import subprocess
import urllib.request
from pathlib import Path
from typing import Any

from . import __version__
from .daemon_endpoint import warm_daemon_url
from .private_pack_diagnostics import private_pack_local_summary
from .registration import DEFAULT_SERVICE_URL, RegistrationError, load_registration, unlimited_skills_home
from .search_core import (
    EXPANSION_REVISION,
    INDEX_MANIFEST_NAME,
    INDEX_SCHEMA_VERSION,
    STOPWORD_REVISION,
    TOKENIZER_REVISION,
    index_is_current,
    vector_sidecar_status,
)


MANAGED_BLOCK_MARKER = "<!-- BEGIN UNLIMITED SKILLS -->"
ROUTER_NAME = "unlimited-skills"
INDEX_NAME = ".unlimited-skills-index.json"
VECTOR_META_NAME = ".unlimited-skills-vector.json"
VECTOR_SIDECAR_NAME = ".unlimited-skills-vectors.json"
CHROMA_DIR_NAME = ".chroma-skills"
DEFAULT_EMBED_MODEL = os.environ.get(
    "UNLIMITED_SKILLS_EMBED_MODEL",
    "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
)
WARM_DAEMON_PROTOCOL = "warm-search-v1"
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
    index_present = (root / INDEX_NAME).is_file()
    index_current = index_is_current(root) if index_present else False
    vector_status = vector_sidecar_status(root, root / VECTOR_SIDECAR_NAME, DEFAULT_EMBED_MODEL)
    return {
        "exists": root.is_dir(),
        "collections": collections,
        "total_skills": sum(collections.values()),
        "index_present": index_present,
        "index_current": index_current,
        "index_schema_version": INDEX_SCHEMA_VERSION if index_current else None,
        "index_manifest": str(root / INDEX_MANIFEST_NAME),
        "tokenizer_revision": TOKENIZER_REVISION,
        "stopword_revision": STOPWORD_REVISION,
        "expansion_revision": EXPANSION_REVISION,
        "vector_index_present": (root / CHROMA_DIR_NAME).is_dir() or (root / VECTOR_META_NAME).is_file(),
        "vector_index_ready": bool(vector_status.get("ready")),
        "vector_status": vector_status,
    }


def _runtime_deps_summary() -> dict[str, Any]:
    """Are the optional extras needed for native-language search installed?

    ``[server]`` (fastapi/uvicorn) runs the warm daemon required for arbitrary
    native-language semantic queries
    (``unlimited-skills serve``); ``[vector]`` (fastembed/chromadb) provides
    native-language embedding retrieval. Without it, the router falls back to
    an explicit English-keyword re-query instruction. Pure ``find_spec`` — imports nothing.
    """
    import importlib.util

    def present(mod: str) -> bool:
        try:
            return importlib.util.find_spec(mod) is not None
        except (ImportError, ValueError):
            return False

    server = present("fastapi") and present("uvicorn")
    vector = present("fastembed") and present("chromadb")
    return {
        "server_extra_present": server,
        "vector_extra_present": vector,
        "multilingual_ready": server and vector,
    }


def _warm_daemon_summary(root: Path) -> dict[str, Any]:
    daemon_url = warm_daemon_url(root, DEFAULT_EMBED_MODEL)
    if not daemon_url:
        return {
            "endpoint": "refused_non_local_or_invalid",
            "required_for_native_semantic_retrieval": True,
            "auto_start_enabled": False,
            "running": False,
            "warming": False,
            "protocol_matches": False,
            "root_matches": False,
            "model_matches": False,
            "ready": False,
        }
    try:
        with urllib.request.urlopen(f"{daemon_url}/health", timeout=0.2) as response:
            payload = json.loads(response.read().decode("utf-8"))
        root_value = str(payload.get("root") or "").strip()
        protocol_matches = (
            payload.get("service") == "unlimited-skills"
            and payload.get("protocol") == WARM_DAEMON_PROTOCOL
        )
        root_matches = bool(root_value) and Path(root_value).expanduser().resolve() == root.expanduser().resolve()
        model_matches = str(payload.get("model") or "") == DEFAULT_EMBED_MODEL
        return {
            "endpoint": daemon_url,
            "required_for_native_semantic_retrieval": True,
            "auto_start_enabled": os.environ.get("UNLIMITED_SKILLS_NO_AUTOSERVE", "").strip().lower() not in {"1", "true", "yes", "on"},
            "running": bool(payload.get("ok")),
            "warming": False,
            "protocol_matches": protocol_matches,
            "root_matches": root_matches,
            "model_matches": model_matches,
            "ready": bool(payload.get("ok")) and protocol_matches and root_matches and model_matches,
        }
    except Exception:
        return {
            "endpoint": daemon_url,
            "required_for_native_semantic_retrieval": True,
            "auto_start_enabled": os.environ.get("UNLIMITED_SKILLS_NO_AUTOSERVE", "").strip().lower() not in {"1", "true", "yes", "on"},
            "running": False,
            "warming": False,
            "protocol_matches": False,
            "root_matches": False,
            "model_matches": False,
            "ready": False,
        }


# Concrete contents of the [all] extra (mirror pyproject.toml [project.optional-dependencies]).
# We install the dep packages directly so repair works regardless of how
# unlimited-skills itself was installed (pip / editable / git) and never touches
# or downgrades the core package.
RUNTIME_EXTRA_PACKAGES = ("fastapi>=0.115", "uvicorn>=0.30", "fastembed>=0.4", "chromadb>=1.0,<2")


def repair_runtime_deps(*, dry_run: bool = False, python_executable: str | None = None, timeout: float = 600.0) -> dict[str, Any]:
    """Deliver the optional native-language search extras ([server]+[vector]).

    Best-effort and idempotent: a no-op when already present, otherwise it
    ``pip install``s the concrete extra packages into the current venv. NEVER
    raises — a pip failure is reported, not propagated — so callers (upgrade,
    ``doctor --fix``) can run it unconditionally without risking the flow.
    """
    import sys

    before = _runtime_deps_summary()
    if before["multilingual_ready"]:
        return {"action": "noop", "reason": "already_present", "multilingual_ready": True}
    command = [python_executable or sys.executable, "-m", "pip", "install", *RUNTIME_EXTRA_PACKAGES]
    if dry_run:
        return {"action": "dry_run", "command": command, "multilingual_ready": False}
    try:
        proc = subprocess.run(command, capture_output=True, text=True, timeout=timeout)
        ok = proc.returncode == 0
    except Exception as exc:  # never propagate — repair must not break the caller
        return {"action": "failed", "error": exc.__class__.__name__, "multilingual_ready": False}
    after = _runtime_deps_summary()
    return {
        "action": "installed" if ok else "failed",
        "returncode": proc.returncode,
        "multilingual_ready": after["multilingual_ready"],
        "stderr_tail": (proc.stderr or "")[-400:] if not ok else "",
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
    block = _managed_block_status(agents_file)
    launcher = _launcher_status(root)
    recommendations = []
    status = "ok"
    if router and not block["present"]:
        status = "warn"
        recommendations.append("Codex router is installed, but the project AGENTS.md managed block is missing.")
    if router and block["stale"]:
        status = "warn"
        recommendations.append(
            f"Project AGENTS.md inject is stale (contract v{block['contract_version']} < "
            f"v{block['current_contract_version']}). Run `unlimited-skills sync-inject` to refresh it."
        )
    if router and launcher["stale"]:
        status = "warn"
        recommendations.append(
            f"Codex launcher is stale (contract v{launcher['contract_version']} < "
            f"v{launcher['current_contract_version']}); it may run a pre-upgrade package. {_HEAL_LAUNCHER_HINT}"
        )
    return {
        "status": status,
        "visible_skill_roots": [str(root)],
        "visible_skill_count": _skill_count(root),
        "router_present": router,
        "agents_file": str(agents_file),
        "agents_patch_present": block["present"],
        "agents_contract_version": block["contract_version"],
        "current_contract_version": block["current_contract_version"],
        "launcher_present": launcher["present"],
        "launcher_contract_version": launcher["contract_version"],
        "launcher_stale": launcher["stale"],
        "recommendations": recommendations,
    }


def _claude_project_root(project_root: Path) -> Path:
    value = os.environ.get("UNLIMITED_SKILLS_CLAUDE_PROJECT_ROOT") or os.environ.get("CLAUDE_PROJECT_DIR") or ""
    return Path(value).expanduser() if value else project_root


def _launcher_status(skills_root: Path) -> dict[str, Any]:
    """Presence + contract freshness of an agent's ``unlimited-skills.sh`` launcher.

    Detects a launcher left behind by an older install — the legacy
    ``PYTHONPATH=<repo checkout>`` form that SHADOWED the pip-installed package and
    pinned the router to the version present at first install. Such launchers parse
    as contract 0 (pre-stamp) and read as stale.
    """
    from .launchers import LAUNCHER_CONTRACT_VERSION, parse_launcher_contract

    launcher = skills_root / ROUTER_NAME / "scripts" / "unlimited-skills.sh"
    present = launcher.is_file()
    version: int | None = None
    if present:
        try:
            version = parse_launcher_contract(launcher.read_text(encoding="utf-8", errors="replace"))
        except OSError:
            version = None
    return {
        "present": present,
        "launcher_path": str(launcher),
        "contract_version": version,
        "current_contract_version": LAUNCHER_CONTRACT_VERSION,
        "stale": bool(present and version is not None and version < LAUNCHER_CONTRACT_VERSION),
    }


_HEAL_LAUNCHER_HINT = (
    "Run `unlimited-skills sync-inject --heal-launchers` to regenerate it against the installed package."
)


def _managed_block_status(path: Path) -> dict[str, Any]:
    """Presence + contract-version freshness of a CLAUDE.md managed block.

    Detects the case where the block exists but carries an OLDER contract than
    the installed package ships — the exact state left behind when a package is
    upgraded without re-running the installer.
    """
    from .installers.claude_code import CLAUDE_CONTRACT_VERSION, parse_claude_contract_version

    present = _has_managed_block(path)
    version: int | None = None
    if present:
        try:
            version = parse_claude_contract_version(path.read_text(encoding="utf-8", errors="replace"))
        except OSError:
            version = None
    return {
        "present": present,
        "contract_version": version,
        "current_contract_version": CLAUDE_CONTRACT_VERSION,
        "stale": bool(present and version is not None and version < CLAUDE_CONTRACT_VERSION),
    }


def _claude_summary(project_root: Path) -> dict[str, Any]:
    home = _env_path("CLAUDE_HOME", _home() / ".claude")
    root = home / "skills"
    router = _router_present(root)
    claude_file = _claude_project_root(project_root) / "CLAUDE.md"
    global_claude_file = home / "CLAUDE.md"
    project_block = _managed_block_status(claude_file)
    global_block = _managed_block_status(global_claude_file)
    launcher = _launcher_status(root)
    recommendations = []
    status = "ok"
    if router and not project_block["present"]:
        status = "warn"
        recommendations.append("Claude Code router is installed, but the project CLAUDE.md managed block is missing.")
    if router and project_block["stale"]:
        status = "warn"
        recommendations.append(
            f"Project CLAUDE.md inject is stale (contract v{project_block['contract_version']} < "
            f"v{project_block['current_contract_version']}). Run `unlimited-skills sync-inject` to refresh it."
        )
    if router and global_block["stale"]:
        status = "warn"
        recommendations.append(
            f"Global CLAUDE.md inject is stale (contract v{global_block['contract_version']} < "
            f"v{global_block['current_contract_version']}). Run `unlimited-skills sync-inject` to refresh it."
        )
    if router and launcher["stale"]:
        status = "warn"
        recommendations.append(
            f"Claude Code launcher is stale (contract v{launcher['contract_version']} < "
            f"v{launcher['current_contract_version']}); it may run a pre-upgrade package. {_HEAL_LAUNCHER_HINT}"
        )
    return {
        "status": status,
        "visible_skill_roots": [str(root)],
        "visible_skill_count": _skill_count(root),
        "router_present": router,
        "claude_file": str(claude_file),
        "claude_patch_present": project_block["present"],
        "claude_contract_version": project_block["contract_version"],
        "global_claude_file": str(global_claude_file),
        "global_patch_present": global_block["present"],
        "global_contract_version": global_block["contract_version"],
        "current_contract_version": project_block["current_contract_version"],
        "launcher_present": launcher["present"],
        "launcher_contract_version": launcher["contract_version"],
        "launcher_stale": launcher["stale"],
        "recommendations": recommendations,
    }


def _hermes_summary() -> dict[str, Any]:
    root = _env_path("HERMES_HOME", _home() / ".hermes") / "skills"
    count = _skill_count(root)
    router = _router_present(root)
    skill_file = root / ROUTER_NAME / "SKILL.md"
    block = _managed_block_status(skill_file)
    launcher = _launcher_status(root)
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
    if router and block["stale"]:
        status = "warn"
        recommendations.append(
            f"Hermes router SKILL.md inject is stale (contract v{block['contract_version']} < "
            f"v{block['current_contract_version']}). Run `unlimited-skills sync-inject` to refresh it."
        )
    if router and launcher["stale"]:
        status = "warn"
        recommendations.append(
            f"Hermes launcher is stale (contract v{launcher['contract_version']} < "
            f"v{launcher['current_contract_version']}); it may run a pre-upgrade package. {_HEAL_LAUNCHER_HINT}"
        )
    return {
        "status": status,
        "visible_skill_roots": [str(root)],
        "visible_skill_count": count,
        "router_present": router,
        "context_reduction_status": context_status,
        "router_contract_version": block["contract_version"],
        "current_contract_version": block["current_contract_version"],
        "launcher_present": launcher["present"],
        "launcher_contract_version": launcher["contract_version"],
        "launcher_stale": launcher["stale"],
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
    block = _managed_block_status(agents_file)
    launcher = _launcher_status(root)
    recommendations = []
    status = "ok"
    if router and not block["present"]:
        status = "warn"
        recommendations.append("OpenClaw router is installed, but the workspace AGENTS.md managed block is missing.")
    if router and block["stale"]:
        status = "warn"
        recommendations.append(
            f"Workspace AGENTS.md inject is stale (contract v{block['contract_version']} < "
            f"v{block['current_contract_version']}). Run `unlimited-skills sync-inject` to refresh it."
        )
    if router and launcher["stale"]:
        status = "warn"
        recommendations.append(
            f"OpenClaw launcher is stale (contract v{launcher['contract_version']} < "
            f"v{launcher['current_contract_version']}); it may run a pre-upgrade package. {_HEAL_LAUNCHER_HINT}"
        )
    return {
        "status": status,
        "visible_skill_roots": [str(root)],
        "visible_skill_count": _skill_count(root),
        "router_present": router,
        "agents_file": str(agents_file),
        "agents_patch_present": block["present"],
        "agents_contract_version": block["contract_version"],
        "current_contract_version": block["current_contract_version"],
        "launcher_present": launcher["present"],
        "launcher_contract_version": launcher["contract_version"],
        "launcher_stale": launcher["stale"],
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
        recommendations.append(
            "Local library root is missing. Run `unlimited-skills quickstart --skip-mcp-check` "
            "to import bundled skills and build the lexical index."
        )
    elif not library["index_present"]:
        recommendations.append("Lexical index is missing. Run `unlimited-skills reindex`.")
    elif not library["index_current"]:
        recommendations.append("Lexical index is stale or incompatible. Run `unlimited-skills reindex`.")
    for info in agents.values():
        recommendations.extend(info.get("recommendations") or [])
    runtime_deps = _runtime_deps_summary()
    runtime_deps["native_language_search_ready"] = bool(
        runtime_deps["vector_extra_present"] and library["vector_index_ready"]
    )
    runtime_deps["warm_daemon"] = _warm_daemon_summary(root)
    runtime_deps["warm_daemon_ready"] = bool(
        runtime_deps["native_language_search_ready"]
        and runtime_deps["server_extra_present"]
        and runtime_deps["warm_daemon"]["ready"]
    )
    if not runtime_deps["vector_extra_present"]:
        recommendations.append(
            "Native-language vector retrieval is not installed; the safe English-keyword fallback "
            "remains active. For direct native-language matches, install `pip install "
            "\"unlimited-skills[vector]\"`, then run `unlimited-skills vector-reindex`."
        )
    elif not library["vector_index_ready"]:
        recommendations.append(
            "Vector dependencies are installed but the local sidecar is missing, stale, or incompatible. Run "
            "`unlimited-skills vector-reindex` to enable native-language retrieval."
        )
    if not runtime_deps["server_extra_present"]:
        recommendations.append(
            "The required warm runtime for native semantic retrieval is unavailable "
            "([server]: fastapi/uvicorn). Install `pip install \"unlimited-skills[all]\"`; "
            "the Claude Code hooks will then start it automatically."
        )
    from .search_core import read_router_metrics

    router_metrics = read_router_metrics(root)
    return {
        "version": __version__,
        "root": str(root),
        "registration": _registration_summary(),
        "library": library,
        "runtime_deps": runtime_deps,
        "private_packs": private_pack_local_summary(root),
        "router": {
            "total_invocations": router_metrics.get("total_invocations", 0),
            "last_call": router_metrics.get("last_call", {}),
        },
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
        f"Private packs: {report.get('private_packs', {}).get('installed_count', 0)}",
        "Lexical index: " + ("current" if library["index_current"] else ("stale/incompatible" if library["index_present"] else "missing")),
        "Vector index: " + ("ready" if library["vector_index_ready"] else str(library.get("vector_status", {}).get("reason") or "missing")),
        "Native-language search: " + (
            "ready"
            if report.get("runtime_deps", {}).get("native_language_search_ready")
            else "English-keyword fallback active; add `unlimited-skills[vector]` + run `unlimited-skills vector-reindex` for direct matches"
        ),
        "Warm daemon: " + (
            "ready"
            if report.get("runtime_deps", {}).get("warm_daemon_ready")
            else "required for native semantic retrieval; auto-start enabled but not ready"
        ),
    ]
    router = report.get("router", {})
    last_call = router.get("last_call", {})
    lines.append(f"Router invocations: {router.get('total_invocations', 0)}")
    if last_call:
        lines.append(
            f"  last call: {last_call.get('iso', '?')} "
            f"[{last_call.get('path', '?')}, {last_call.get('elapsed_ms', '?')}ms, {last_call.get('reason_code', '?')}]"
        )
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
