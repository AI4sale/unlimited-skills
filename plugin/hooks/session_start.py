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

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _cli_resolve import display_command, resolve_cli_command  # noqa: E402

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


def main() -> int:
    try:
        command = resolve_cli_command()
    except Exception:
        command = None
    if command:
        sys.stdout.write(CONTRACT_TEMPLATE.format(cli=display_command(command)))
    else:
        sys.stdout.write(MISSING_CLI)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
