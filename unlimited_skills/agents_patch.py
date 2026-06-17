from __future__ import annotations

import argparse
import os
import re
import shutil
from datetime import datetime
from pathlib import Path

UNLIMITED_START = "<!-- BEGIN UNLIMITED SKILLS -->"
UNLIMITED_END = "<!-- END UNLIMITED SKILLS -->"
ECC_START = "<!-- BEGIN ECC -->"
ECC_END = "<!-- END ECC -->"

# Single source of truth for the router-inject contract version, shared by every
# agent surface (CLAUDE.md block, AGENTS.md block, Hermes router SKILL.md). Bump
# this whenever the inject contract changes meaningfully. The version is stamped
# INSIDE each rendered inject so an upgraded package can detect a stale inject
# (one written by an older install) and refresh it via `unlimited-skills
# sync-inject`, instead of silently keeping the old contract because
# `pip install --upgrade` never re-runs the installer.
CONTRACT_VERSION = 2
_CONTRACT_STAMP_RE = re.compile(r"<!--\s*unlimited-skills-contract:\s*(\d+)\s*-->")


def contract_stamp(version: int = CONTRACT_VERSION) -> str:
    return f"<!-- unlimited-skills-contract: {version} -->"


def parse_contract_version(text: str) -> int | None:
    """Return the inject contract version found in agent text.

    Returns the stamped integer, ``1`` for a managed block that predates the
    stamp (legacy contract), or ``None`` when there is no managed block at all.
    """
    if UNLIMITED_START not in text:
        return None
    match = _CONTRACT_STAMP_RE.search(text)
    return int(match.group(1)) if match else 1


def agents_block_lines(launcher: str) -> list[str]:
    """The managed AGENTS.md router block (Codex / OpenClaw).

    Regenerable: re-applying replaces everything between the BEGIN/END markers
    with the current contract. Stamped with ``CONTRACT_VERSION``.
    """
    return [
        UNLIMITED_START,
        contract_stamp(),
        "## Unlimited Skills Library",
        "",
        "A generated inventory of proven skills (checklists, workflows, regression recipes) that is deliberately NOT in the always-loaded skill list. A 1-second lookup often replaces 20 minutes of rediscovery because the library has shipped-and-tested procedures for recurring tasks.",
        "",
        "RUN this single command BEFORE starting every substantive work phase that matches a trigger below. It costs ~1 second and returns at most one compact card, one name hint, or nothing:",
        "",
        "```bash",
        f"\"{launcher}\" suggest \"<3-8 keyword phase summary>\" --json --card --limit 1",
        "```",
        "",
        "TRIGGERS (any one suffices):",
        "",
        "- writing or reviewing code in a named language/framework (React, Python, Go, n8n, ...)",
        "- review, audit, or security check of any artifact",
        "- writing tests, fixing a bug, or debugging a failure",
        "- git/GitHub workflows: branches, PRs, releases, changelogs",
        "- writing prose: docs, posts, outreach, marketing, research reports",
        "- planning, refactoring, migrations, deployments, ops procedures",
        "- the user names a skill, workflow, or asks \"what can you do\"",
        "",
        "PHASE FRESHNESS: a `suggest` result is fresh only for the current substantive phase. Re-query at phase boundaries such as planning -> implementation, backend/API -> frontend/UI, implementation -> testing, testing -> debugging, implementation -> security review, code -> docs, or docs -> release/git workflow. A no-hit result is also scoped only to the current phase.",
        "",
        "ACT on the result: if a suggestion looks relevant, run `view <skill-name>` with the same launcher and follow it. If `suggest` returns nothing, proceed with the current phase; do not search again with synonyms for that same phase. Anti-spam: at most one `suggest` probe per phase unless the user explicitly asks for a broader search. For deeper retrieval use `search \"<query>\" --mode hybrid --limit 8`; for inventory questions use `list --limit 80`.",
        "",
        "TIER BEHAVIOR: silence means no confident match; a name hint means inspect that skill if it looks relevant; a compact card means a high-confidence match for this phase.",
        "",
        "SKIP only when a relevant skill is already active in the current context.",
        UNLIMITED_END,
        "",
    ]


def agents_block(launcher: str) -> str:
    return "\n".join(agents_block_lines(launcher))

UNLIMITED_BLOCK_RE = re.compile(
    rf"(?s){re.escape(UNLIMITED_START)}.*?{re.escape(UNLIMITED_END)}"
)
ECC_BLOCK_RE = re.compile(
    rf"(?s)\ufeff?\s*{re.escape(ECC_START)}.*?{re.escape(ECC_END)}\s*"
)


def patch_agents_text(text: str, unlimited_block: str) -> str:
    block = unlimited_block.strip() + "\n"
    has_unlimited = bool(UNLIMITED_BLOCK_RE.search(text))
    has_ecc = bool(ECC_BLOCK_RE.search(text))

    if has_unlimited:
        text = UNLIMITED_BLOCK_RE.sub(lambda _match: block.rstrip(), text, count=1)
        text = ECC_BLOCK_RE.sub("\n", text)
    elif has_ecc:
        text = ECC_BLOCK_RE.sub(lambda _match: block.rstrip(), text, count=1)
    elif text.strip():
        text = text.rstrip() + "\n\n" + block.rstrip()
    else:
        text = block.rstrip()

    return text.strip() + "\n"


def _backup_path(path: Path, timestamp: str | None = None) -> Path:
    stamp = timestamp or datetime.now().strftime("%Y%m%d_%H%M%S")
    backup = path.with_name(f"Agents_md_{stamp}.back")
    if not backup.exists():
        return backup
    index = 2
    while True:
        candidate = path.with_name(f"Agents_md_{stamp}_{index}.back")
        if not candidate.exists():
            return candidate
        index += 1


def patch_agents_file(path: Path, unlimited_block: str, *, backup: bool = True) -> Path | None:
    path.parent.mkdir(parents=True, exist_ok=True)
    old_text = path.read_text(encoding="utf-8", errors="replace") if path.is_file() else ""
    new_text = patch_agents_text(old_text, unlimited_block)

    backup_file: Path | None = None
    if backup and path.is_file() and old_text != new_text:
        backup_file = _backup_path(path)
        shutil.copy2(path, backup_file)

    path.write_text(new_text, encoding="utf-8")
    return backup_file


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Patch AGENTS.md with the Unlimited Skills managed block.")
    parser.add_argument("agents_file", type=Path)
    parser.add_argument("--no-backup", action="store_true")
    args = parser.parse_args(argv)

    block = os.environ.get("AGENTS_BLOCK", "")
    if not block.strip():
        raise SystemExit("AGENTS_BLOCK environment variable is required.")

    backup_file = patch_agents_file(args.agents_file, block, backup=not args.no_backup)
    if backup_file:
        print(f"Backed up AGENTS.md: {backup_file}")
    print(f"Patched AGENTS.md: {args.agents_file}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
