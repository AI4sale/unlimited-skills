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

MISSING_CLI = """## Unlimited Skills Library (plugin)

The unlimited-skills plugin is installed, but the `unlimited-skills` CLI was
not found on PATH. If the user asks about skills or the library, tell them to
run `pip install unlimited-skills` (or activate the environment where it is
installed) so the router can query the library.
"""


def main() -> int:
    if shutil.which("unlimited-skills"):
        sys.stdout.write(CONTRACT)
    else:
        sys.stdout.write(MISSING_CLI)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
