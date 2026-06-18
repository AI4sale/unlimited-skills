"""SessionStart hook: inject the Unlimited Skills router contract into context.

Prints a short, deterministic contract so every session knows the external
skill library exists, regardless of CLAUDE.md state or model routing mood.
Resolves the CLI through the shared fallback chain (PATH -> install venv ->
rendered launchers), so a working install never gets the "install the CLI"
nag just because the entry point is not on PATH. Never fails the session:
exits 0 on every path and prints nothing heavier than a few lines. No skill
bodies, prompts, or private data are emitted.
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _cli_resolve import display_command, resolve_cli_command  # noqa: E402

# Source-of-truth contract versions live in the package
# (unlimited_skills.launchers.LAUNCHER_CONTRACT_VERSION and
# unlimited_skills.agents_patch.CONTRACT_VERSION). They are inlined here so the
# drift check stays a couple of file reads with no package import on the hot path;
# tests/test_plugin_hooks.py asserts these stay in lock-step with the package.
LAUNCHER_CONTRACT_VERSION = 1
INJECT_CONTRACT_VERSION = 2
_LAUNCHER_STAMP_RE = re.compile(r"unlimited-skills-launcher:\s*(\d+)")
_INJECT_STAMP_RE = re.compile(r"unlimited-skills-contract:\s*(\d+)")
_UNLIMITED_BLOCK_MARKER = "<!-- BEGIN UNLIMITED SKILLS -->"
_HEAL_TIMEOUT_SECONDS = 25.0
_MONEY_EVENT_TIMEOUT_SECONDS = 10.0

CONTRACT_TEMPLATE = """## Unlimited Skills Library (plugin)

A generated inventory of proven skills (checklists, workflows, regression
recipes) that are deliberately NOT in the visible skill list. A 1-second
lookup often replaces 20 minutes of rediscovery.

RUN this single command BEFORE starting every substantive work phase that
matches a trigger below. It costs ~1 second and returns at most one compact
card, one name hint, or nothing:

    {cli} suggest "<3-8 keyword phase summary>" --json --card --limit 1

TRIGGERS (any one suffices): writing or reviewing code in a named
language/framework; review, audit, or security check of any artifact;
writing tests, fixing a bug, or debugging a failure; git/GitHub workflows
(branches, PRs, releases, changelogs); writing prose (docs, posts, outreach,
marketing, research); planning, refactoring, migrations, deployments, ops;
the user names a skill or asks "what can you do".

ACT on the result: if a suggestion looks relevant, run `{cli} view
<skill-name>` and follow it. A `suggest` result is fresh only for the current
phase. Re-query when the work changes domain or deliverable kind: planning ->
implementation, code -> tests/debugging/security/docs, UI -> backend, or docs
-> release/git. If `suggest` returns nothing, proceed with the current phase;
do not search again with synonyms for that same phase. For inventory questions
run `{cli} list --limit 80` before answering.

ANTI-SPAM: at most one `suggest` probe per phase unless the user explicitly
asks for a broader search. Tiers: silence = no confident match; name hint =
inspect if relevant; compact card = high-confidence match for this phase.

SKIP only when a relevant skill is already active in the current context.
"""

MISSING_CLI = """## Unlimited Skills Library (plugin)

The unlimited-skills plugin is installed, but no unlimited-skills CLI was
found on PATH, in ~/.unlimited-skills/.venv, or among the rendered launchers
under ~/.claude/skills/unlimited-skills/scripts/. If the user asks about
skills or the library, tell them to install Unlimited Skills (see the
project README install instructions) so the router can query the library.
"""


def _claude_home() -> Path:
    return Path(os.environ.get("CLAUDE_HOME") or Path.home() / ".claude")


def _stamp_version(text: str, pattern: "re.Pattern[str]") -> int | None:
    match = pattern.search(text)
    return int(match.group(1)) if match else None


def _launcher_is_stale(scripts_dir: Path) -> bool:
    try:
        text = (scripts_dir / "unlimited-skills.sh").read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False
    if "unlimited_skills" not in text:
        return False
    return (_stamp_version(text, _LAUNCHER_STAMP_RE) or 0) < LAUNCHER_CONTRACT_VERSION


def _inject_is_stale(claude_md: Path) -> bool:
    try:
        text = claude_md.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False
    if _UNLIMITED_BLOCK_MARKER not in text:
        return False
    # An UNLIMITED block with no contract stamp is the legacy v1 contract.
    return (_stamp_version(text, _INJECT_STAMP_RE) or 1) < INJECT_CONTRACT_VERSION


def _resolved_is_rendered_launcher(command: list[str]) -> bool:
    """True when the resolved CLI is one of our rendered launcher scripts.

    A stale launcher might itself pin a pre-`sync-inject` package, so we never try
    to heal *through* it — auto-heal only runs when a clean entry point (PATH / venv
    console script / explicit override) is available.
    """
    if not command:
        return True
    return any(str(arg).lower().endswith((".ps1", ".sh")) for arg in command)


def _maybe_autoheal(command: list[str]) -> None:
    """Regenerate a stale launcher / inject once, during session start.

    Cheap by design: two file reads detect drift, and the heal subprocess runs only
    when something is actually stale (the steady state spawns nothing). Never raises
    and never blocks the session beyond a short timeout. Opt out by setting
    ``UNLIMITED_SKILLS_NO_AUTOHEAL``.
    """
    if os.environ.get("UNLIMITED_SKILLS_NO_AUTOHEAL"):
        return
    if not command or _resolved_is_rendered_launcher(command):
        return
    home = _claude_home()
    scripts_dir = home / "skills" / "unlimited-skills" / "scripts"
    if not (_launcher_is_stale(scripts_dir) or _inject_is_stale(home / "CLAUDE.md")):
        return
    try:
        subprocess.run(
            [*command, "sync-inject", "--heal-launchers", "--agent", "claude-code", "--json"],
            capture_output=True,
            timeout=_HEAL_TIMEOUT_SECONDS,
        )
    except Exception:
        return


def _record_money_event(command: list[str], event_type: str) -> None:
    """Best-effort: record one Money Saved context-load event for this session.

    This is the observer half of the meter — the standing skill/MCP context
    re-enters the model here, so we count it. Fast (bytes//4, no API), capped by
    a short timeout, fully guarded: it must NEVER block or break the session.
    Opt out with ``UNLIMITED_SKILLS_NO_MONEY_EVENTS``.
    """
    if os.environ.get("UNLIMITED_SKILLS_NO_MONEY_EVENTS"):
        return
    try:
        subprocess.run(
            [*command, "money-saved", "record-event", event_type, "--agent", "claude-code"],
            capture_output=True,
            timeout=_MONEY_EVENT_TIMEOUT_SECONDS,
        )
    except Exception:
        return


def main() -> int:
    try:
        command = resolve_cli_command()
    except Exception:
        command = None
    if command:
        try:
            _maybe_autoheal(command)
        except Exception:
            pass
        sys.stdout.write(CONTRACT_TEMPLATE.format(cli=display_command(command)))
        try:
            _record_money_event(command, "session_start")
        except Exception:
            pass
    else:
        sys.stdout.write(MISSING_CLI)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
