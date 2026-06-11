"""The Unlimited Skills MCP server: 3 read-only tools over the skill library.

Tools:

- ``skills_search`` -- metadata-only search hits (name, collection,
  description, score, library-relative path). Never returns skill bodies
  or absolute local paths.
- ``skills_view`` -- frontmatter metadata plus the body of ONE skill,
  capped at 16000 characters with an explicit truncation marker.
- ``skills_use`` -- same as ``skills_view`` plus a local learning-loop
  use event. It only reads SKILL.md text; it never executes scripts.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, BinaryIO

from .protocol import StdioServer, ToolError

VIEW_CHAR_CAP = 16000
TRUNCATION_MARKER = "\n\n[truncated: skill body exceeds the {cap} character MCP view cap]"
MAX_SEARCH_LIMIT = 20
DEFAULT_SEARCH_LIMIT = 8

SERVER_NAME = "unlimited-skills"


def _cli():
    from .. import cli

    return cli


def _library_relative(root: Path, path_text: str) -> str:
    """Library-relative POSIX path, or empty when outside the library root."""
    try:
        return Path(path_text).resolve().relative_to(Path(root).resolve()).as_posix()
    except (ValueError, OSError):
        return ""


def _clamp_limit(raw: Any) -> int:
    try:
        limit = int(raw)
    except (TypeError, ValueError) as exc:
        raise ToolError("limit must be an integer.") from exc
    return max(1, min(limit, MAX_SEARCH_LIMIT))


def skills_search_handler(root: Path, arguments: dict) -> dict:
    cli = _cli()
    query = str(arguments.get("query") or "").strip()
    if not query:
        raise ToolError("query is required.")
    limit = _clamp_limit(arguments.get("limit", DEFAULT_SEARCH_LIMIT))
    mode = str(arguments.get("mode") or "lexical")
    if mode not in {"lexical", "hybrid"}:
        raise ToolError("mode must be 'lexical' or 'hybrid'.")
    if mode == "hybrid":
        hits = cli.hybrid_search(root, query, limit=limit, model=cli.DEFAULT_EMBED_MODEL)
    else:
        hits = cli.lexical_search(root, query, limit=limit)
    return {
        "query": query,
        "mode": mode,
        "hits": [
            {
                "name": hit.name,
                "collection": hit.collection,
                "description": hit.description,
                "score": round(float(hit.score), 3),
                "library_path": _library_relative(root, hit.path),
            }
            for hit in hits
        ],
    }


def _load_skill(root: Path, arguments: dict) -> dict:
    cli = _cli()
    name = str(arguments.get("name") or "").strip()
    if not name:
        raise ToolError("name is required.")
    path = cli.find_by_name(root, name)
    if not path:
        raise ToolError(f"Skill not found: {name}")
    meta, body = cli.split_frontmatter(cli.read_text(path))
    truncated = len(body) > VIEW_CHAR_CAP
    if truncated:
        body = body[:VIEW_CHAR_CAP] + TRUNCATION_MARKER.format(cap=VIEW_CHAR_CAP)
    return {
        "name": meta.get("name") or path.parent.name,
        "collection": cli.collection_for(root, path),
        "metadata": {str(key): str(value) for key, value in meta.items()},
        "library_path": _library_relative(root, str(path)),
        "truncated": truncated,
        "body": body,
        "_abs_path": str(path),
    }


def skills_view_handler(root: Path, arguments: dict) -> dict:
    result = _load_skill(root, arguments)
    result.pop("_abs_path", None)
    return result


def skills_use_handler(root: Path, arguments: dict) -> dict:
    cli = _cli()
    result = _load_skill(root, arguments)
    abs_path = result.pop("_abs_path", "")
    cli.log_event(
        root,
        "skill_used",
        {
            "name": result["name"],
            "query": str(arguments.get("query") or ""),
            "task": str(arguments.get("task") or ""),
            "path": abs_path,
            "source": "mcp",
        },
    )
    result["use_logged"] = True
    return result


def build_skills_registry(root: Path) -> dict[str, dict]:
    """Tool registry for :class:`~unlimited_skills.mcp.protocol.StdioServer`."""
    root = Path(root)
    return {
        "skills_search": {
            "description": (
                "Search the local Unlimited Skills library. Returns metadata-only hits "
                "(name, collection, description, score, library-relative path). "
                "Never returns skill bodies; call skills_view for one skill's content."
            ),
            "inputSchema": {
                "type": "object",
                "required": ["query"],
                "properties": {
                    "query": {"type": "string", "description": "Search query."},
                    "limit": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": MAX_SEARCH_LIMIT,
                        "default": DEFAULT_SEARCH_LIMIT,
                        "description": "Maximum hits (capped at 20).",
                    },
                    "mode": {
                        "type": "string",
                        "enum": ["lexical", "hybrid"],
                        "default": "lexical",
                        "description": "lexical needs no extra deps; hybrid adds the local vector index when available.",
                    },
                },
            },
            "handler": lambda arguments: skills_search_handler(root, arguments),
        },
        "skills_view": {
            "description": (
                "Return frontmatter metadata and the body of ONE skill by name, "
                f"capped at {VIEW_CHAR_CAP} characters with a truncation marker."
            ),
            "inputSchema": {
                "type": "object",
                "required": ["name"],
                "properties": {
                    "name": {"type": "string", "description": "Skill name from skills_search."},
                },
            },
            "handler": lambda arguments: skills_view_handler(root, arguments),
        },
        "skills_use": {
            "description": (
                "Same as skills_view, plus records a local learning-loop use event. "
                "This tool only READS SKILL.md text. It never executes scripts, shell "
                "commands, or any code referenced by the skill."
            ),
            "inputSchema": {
                "type": "object",
                "required": ["name"],
                "properties": {
                    "name": {"type": "string", "description": "Skill name from skills_search."},
                    "query": {"type": "string", "description": "Optional query that led to this skill."},
                    "task": {"type": "string", "description": "Optional short task label."},
                },
            },
            "handler": lambda arguments: skills_use_handler(root, arguments),
        },
    }


def run_skills_server(root: Path, reader: BinaryIO | None = None, writer: BinaryIO | None = None) -> None:
    """Run the skills MCP server loop over stdio (blocking until EOF)."""
    server = StdioServer(
        build_skills_registry(root),
        server_name=SERVER_NAME,
        reader=reader,
        writer=writer,
    )
    server.serve_forever()
