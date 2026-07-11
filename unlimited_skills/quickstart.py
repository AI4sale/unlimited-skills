"""One-command golden path for a fresh install: ``unlimited-skills quickstart``.

The sequence (every step is idempotent -- rerunning on a configured system
only reports status and changes nothing):

1. **Library**: non-destructively import missing bundled collections from the
   repo's ``packs/`` directory (the same ``migrate_source`` path the
   installers' ``bundled`` mode uses) and rebuild the lexical index. Existing
   local skills and existing managed collections are left untouched.
2. **First search**: run one lexical search (the user's query or a demo
   query) and show the top 3 hits, proving retrieval works.
3. **MCP context savings**: measure the user's real standing MCP schema cost
   vs the Unlimited Tools gateway (see :mod:`unlimited_skills.mcp.savings`).
4. **Next steps**: the exact commands to wire the MCP servers and finish
   onboarding.

Everything is local: no registration, no hosted calls, no uploads.
"""

from __future__ import annotations

from contextlib import ExitStack
from importlib import resources
from pathlib import Path

DEFAULT_QUERY = "code review checklist"
BUNDLED_PACKS = ("ecc", "superpowers")
QUICKSTART_DOC_URL = "https://github.com/AI4sale/unlimited-skills/blob/main/docs/quickstart.md"
MCP_DOC_URL = "https://github.com/AI4sale/unlimited-skills/blob/main/docs/unlimited-tools.md"


def find_repo_root(start: Path | None = None) -> Path | None:
    """Locate the repo checkout that carries the bundled ``packs/`` assets.

    Walks up from this package (covers ``pip install -e .`` and running from
    a clone). A pip install straight from GitHub does not ship ``packs/``;
    in that case the import step is skipped with a hint instead of failing.
    """
    current = (start or Path(__file__)).resolve()
    for candidate in (current, *current.parents):
        if (candidate / "packs").is_dir() and (candidate / "pyproject.toml").is_file():
            return candidate
    return None


def packaged_packs_root() -> resources.abc.Traversable | None:
    """Return the wheel-bundled packs root when package data is present."""
    root = resources.files("unlimited_skills").joinpath("bundled_packs")
    return root if root.is_dir() else None


def library_skill_count(root: Path) -> int:
    from . import cli

    return sum(1 for _ in cli.load_records(root, fresh=True))


def ensure_bundled_library(root: Path, repo_root: Path | None = None) -> dict:
    """Import missing bundled collections without modifying existing content."""
    from . import cli
    from .installers.common import migrate_source
    from .search_core import index_is_current

    count = library_skill_count(root)
    repo_root = repo_root or find_repo_root()
    with ExitStack() as stack:
        if repo_root:
            packs_root = repo_root / "packs"
        else:
            packaged = packaged_packs_root()
            packs_root = (
                packaged
                if isinstance(packaged, Path)
                else stack.enter_context(resources.as_file(packaged))
                if packaged
                else None
            )
        sources = (
            [(pack, packs_root / pack / "skills") for pack in BUNDLED_PACKS]
            if packs_root
            else []
        )
        sources = [(pack, path) for pack, path in sources if path.is_dir()]
        imported: dict[str, int] = {}
        for pack, source in sources:
            # ``migrate_source`` intentionally permits replacing entries in its
            # own target collection. Quickstart is additive, so explicitly
            # exclude every name already present there before copying.
            target = root / "registry" / pack / "skills"
            existing_target_names = {
                skill_file.parent.name for skill_file in target.rglob("SKILL.md")
            } if target.is_dir() else set()
            result = migrate_source(
                source,
                root,
                pack,
                exclude_names=existing_target_names,
                skip_existing_names=True,
                registry_collection=True,
            )
            if result.migrated_count:
                imported[pack] = result.migrated_count

    missing_packs = [
        pack
        for pack in BUNDLED_PACKS
        if not any((root / "registry" / pack / "skills").rglob("SKILL.md"))
    ]
    if imported:
        cli.save_index(root)
        return {
            "status": "imported" if count == 0 else "augmented",
            "skill_count": library_skill_count(root),
            "imported": imported,
            "index_refreshed": True,
        }

    index_refreshed = bool(count and not index_is_current(root))
    if index_refreshed:
        cli.save_index(root)
    return {
        "status": (
            "empty_no_packs"
            if count == 0
            else "ready_missing_bundled_packs"
            if missing_packs
            else "ready"
        ),
        "skill_count": count,
        "imported": {},
        "missing_packs": missing_packs,
        "index_refreshed": index_refreshed,
    }


def first_search(root: Path, query: str, limit: int = 3) -> dict:
    """One lexical search; falls back to the demo query when the user's
    query has no hits, so the first-run experience always shows results
    (when the library has any skills at all)."""
    from .suggest import DEFAULT_FLOOR, suggest_hits

    used_query = query or DEFAULT_QUERY
    requested_query = used_query
    hits = suggest_hits(root, used_query, limit=limit, floor=DEFAULT_FLOOR)
    fallback = False
    if not hits and used_query != DEFAULT_QUERY:
        hits = suggest_hits(root, DEFAULT_QUERY, limit=limit, floor=DEFAULT_FLOOR)
        if hits:
            used_query = DEFAULT_QUERY
            fallback = True
    return {
        "requested_query": requested_query,
        "query": used_query,
        "fallback_to_demo_query": fallback,
        "minimum_score": DEFAULT_FLOOR,
        "hits": [
            {
                "name": hit.name,
                "collection": hit.collection,
                "description": hit.description,
                "score": hit.score,
            }
            for hit in hits
        ],
    }


def run_quickstart(
    root: Path,
    *,
    query: str = DEFAULT_QUERY,
    repo_root: Path | None = None,
    claude_config: Path | None = None,
    timeout: float | None = None,
    skip_mcp_check: bool = False,
) -> dict:
    """Run the golden path and return a machine-readable report."""
    from . import cli
    from .mcp.savings import (
        DEFAULT_SERVER_TIMEOUT,
        build_savings_report,
        discover_mcp_servers,
        event_snapshot,
    )

    library = ensure_bundled_library(root, repo_root=repo_root)
    search = first_search(root, query)
    savings: dict | None = None
    savings_error = ""
    if not skip_mcp_check:
        try:
            servers = discover_mcp_servers(claude_config)
            savings = build_savings_report(
                servers, timeout=timeout if timeout is not None else DEFAULT_SERVER_TIMEOUT
            )
        except Exception as exc:  # the wow-step must never break onboarding
            savings_error = type(exc).__name__
    report = {
        "root": "<local-library>",
        "library": library,
        "search": search,
        "savings": savings,
        "savings_error": savings_error,
        "next_steps": [
            "unlimited-skills mcp install --claude-code --dry-run",
            "unlimited-skills setup --local-only",
        ],
    }
    try:
        snapshot = {
            "library_status": library["status"],
            "skill_count": library["skill_count"],
            "search_hits": len(search["hits"]),
        }
        if savings is not None:
            snapshot["savings"] = event_snapshot(savings)
        cli.log_event(root, "quickstart", snapshot)
    except OSError:
        pass
    return report


def format_quickstart_text(report: dict) -> str:
    from .mcp.savings import format_savings_text

    library = report["library"]
    search = report["search"]
    lines = ["Unlimited Skills quickstart", ""]

    lines.append("[1/4] Library")
    if library["status"] in {"imported", "augmented"}:
        packs = ", ".join(f"{pack} ({count})" for pack, count in sorted(library["imported"].items()))
        verb = "Imported" if library["status"] == "imported" else "Added missing"
        lines.append(f"  {verb} bundled packs: {packs}.")
        lines.append(f"  Library ready: {library['skill_count']} skills indexed.")
    elif library["status"] == "ready":
        lines.append(f"  Library already populated: {library['skill_count']} skills (import skipped).")
        if library.get("index_refreshed"):
            lines.append("  Refreshed the stale/incompatible lexical index in place.")
    elif library["status"] == "ready_missing_bundled_packs":
        missing = ", ".join(library.get("missing_packs") or ())
        lines.append(f"  Library has {library['skill_count']} skills; bundled packs unavailable: {missing}.")
    else:
        lines.append("  Library is empty and the bundled packs/ directory was not found.")
        lines.append("  Install packs with: unlimited-skills install-pack ecc")
    lines.append("")

    lines.append(f"[2/4] First search: \"{search['query']}\"")
    if search.get("fallback_to_demo_query"):
        lines.append("  (your query had no hits; showing the demo query instead)")
    if search["hits"]:
        for hit in search["hits"]:
            lines.append(f"  - {hit['name']} [{hit['collection']}]")
            if hit.get("description"):
                lines.append(f"      {hit['description']}")
    else:
        lines.append("  No hits yet -- import skills first, then rerun quickstart.")
    lines.append("")

    lines.append("[3/4] MCP context savings")
    savings = report.get("savings")
    if savings is not None:
        lines.extend("  " + line if line else "" for line in format_savings_text(savings).splitlines())
    elif report.get("savings_error"):
        lines.append(f"  Savings check failed ({report['savings_error']}); rerun: unlimited-skills mcp savings")
    else:
        lines.append("  Skipped (--skip-mcp-check). Run it any time: unlimited-skills mcp savings")
    lines.append("")

    lines.extend(
        [
            "[4/4] Next steps",
            "  - Preview the safe Claude Code gateway change before writing it:",
            "      unlimited-skills mcp install --claude-code --dry-run",
            f"    Gateway guide: {MCP_DOC_URL}",
            "  - Guided setup (router skill, agents, diagnostics):",
            "      unlimited-skills setup --local-only",
            f"  - Docs: {QUICKSTART_DOC_URL}",
        ]
    )
    return "\n".join(lines)
