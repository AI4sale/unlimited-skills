"""SessionStart hook: inject the Unlimited Skills router contract into context.

Prints a short, deterministic contract so every session knows the external
skill library exists, regardless of CLAUDE.md state or model routing mood.
Never fails the session: exits 0 on every path and prints nothing heavier
than a few lines. No skill bodies, prompts, or private data are emitted.
"""
from __future__ import annotations

import shutil
import sys

CONTRACT = """## Unlimited Skills Library (plugin)

Unlimited Skills is the external skill memory for this session. The visible
skill list is NOT the full inventory: the library intentionally keeps skills
out of context until needed.

- Before substantive work (coding, review, writing, research, ops, planning),
  check the library: `unlimited-skills search "<task>" --mode hybrid --limit 8`
- For inventory questions ("what skills do you have?"), query the library
  before answering: `unlimited-skills list --limit 80`
- Load a skill body only after selecting it: `unlimited-skills view <name>`
- Never conclude a skill is missing without querying the library first.
"""

# A3-PYPI-FLIP: the `unlimited-skills` package is NOT published on PyPI yet,
# so every user-facing install hint must point at the Git install below. When
# the v0.5 PyPI publication gate (A3) lands, flip every site carrying the
# A3-PYPI-FLIP marker back to `pip install unlimited-skills`. Greppable
# inventory of touched sites (search the repo for "A3-PYPI-FLIP"):
#   README.md (Claude Code Option A), docs/claude-code-plugin.md,
#   plugin/skills/unlimited-skills/SKILL.md, plugin/hooks/session_start.py,
#   unlimited_skills/cli.py, unlimited_skills/hub.py,
#   unlimited_skills/commands/library.py,
#   .claude-plugin/marketplace.json (JSON cannot carry comments — update the
#   plugin description string there manually), and the guard test
#   tests/test_install_path_docs.py.
MISSING_CLI = """## Unlimited Skills Library (plugin)

The unlimited-skills plugin is installed, but the `unlimited-skills` CLI was
not found on PATH. If the user asks about skills or the library, tell them to
run `pip install "git+https://github.com/AI4sale/unlimited-skills.git"` (or
activate the environment where it is installed) so the router can query the
library.
"""


def main() -> int:
    if shutil.which("unlimited-skills"):
        sys.stdout.write(CONTRACT)
    else:
        sys.stdout.write(MISSING_CLI)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
