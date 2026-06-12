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
  here, the injected hint never echoes the prompt text, and it carries no
  local filesystem paths (skills are referenced by NAME only).
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _cli_resolve import resolve_cli_command  # noqa: E402

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
        payload_out = json.loads(proc.stdout)
        if not isinstance(payload_out, dict):
            return 0
        candidates = payload_out.get("top_3_skill_candidates")
        if not isinstance(candidates, list) or not candidates:
            return 0
        top = candidates[0]
        if not isinstance(top, dict):
            return 0
        name = str(top.get("name") or "").strip()
        if not name:
            return 0
        source = str(top.get("source") or "").strip()
        origin = f" (from the {source} pack)" if source else ""
        # NAME-only reference: no local paths, no prompt text echo.
        hint = (
            f"Relevant skill available: {name}{origin} — "
            f"view it with: unlimited-skills view {name}"
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
