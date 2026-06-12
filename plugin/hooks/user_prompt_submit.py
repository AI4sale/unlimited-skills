"""UserPromptSubmit hook: ambient skill retrieval for every user prompt.

Reads the hook payload from stdin, runs the fast `suggest` probe on the
prompt text, and — only when a suggestion clears the score floor — injects a
single-line hint via ``hookSpecificOutput.additionalContext``. This converts
skill invocation from model initiative (unreliable) into deterministic
ambient retrieval.

Hard guarantees:

- never blocks: the probe runs with a hard timeout (default 2 s,
  ``UNLIMITED_SKILLS_SUGGEST_TIMEOUT`` overrides for tests);
- fail-open: ANY error (missing CLI, bad stdin, timeout, bad JSON) exits 0
  with no output;
- no below-floor noise: when `suggest` returns nothing, the hook prints
  nothing;
- privacy: the prompt text goes only to the local CLI; nothing is logged
  here.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _cli_resolve import display_command, resolve_cli_command  # noqa: E402

MIN_PROMPT_CHARS = 12
MAX_PROMPT_CHARS = 300
DEFAULT_TIMEOUT_SECONDS = 2.0


def _timeout() -> float:
    try:
        return float(os.environ.get("UNLIMITED_SKILLS_SUGGEST_TIMEOUT", DEFAULT_TIMEOUT_SECONDS))
    except ValueError:
        return DEFAULT_TIMEOUT_SECONDS


def main() -> int:
    try:
        payload = json.load(sys.stdin)
        prompt = str(payload.get("prompt") or "")
        prompt = " ".join(prompt.split())
        if len(prompt) < MIN_PROMPT_CHARS:
            return 0
        command = resolve_cli_command()
        if not command:
            return 0
        proc = subprocess.run(
            [*command, "suggest", prompt[:MAX_PROMPT_CHARS], "--json", "--limit", "1"],
            capture_output=True,
            text=True,
            timeout=_timeout(),
        )
        if proc.returncode != 0 or not proc.stdout.strip():
            return 0
        hits = json.loads(proc.stdout)
        if not isinstance(hits, list) or not hits:
            return 0
        top = hits[0]
        name = str(top.get("name") or "").strip()
        if not name:
            return 0
        description = " ".join(str(top.get("description") or "").split())
        if len(description) > 120:
            description = description[:117].rstrip() + "..."
        hint = (
            f"Relevant skill available: {name} — {description} "
            f"View it with: {display_command(command)} view {name}"
        )
        print(
            json.dumps(
                {
                    "hookSpecificOutput": {
                        "hookEventName": "UserPromptSubmit",
                        "additionalContext": hint,
                    }
                },
                ensure_ascii=False,
            )
        )
        return 0
    except Exception:
        # Fail open, fail silent: the probe must never break a prompt.
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
