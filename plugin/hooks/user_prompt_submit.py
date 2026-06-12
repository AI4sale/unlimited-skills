"""UserPromptSubmit hook: ambient skill retrieval for every user prompt.

Reads the hook payload from stdin, runs the fast `suggest` probe on the
prompt text, and injects ``hookSpecificOutput.additionalContext`` in THREE
tiers (F3b «ambient skill injection»: when confidence is high, bring the
skill TO the model instead of hinting the model to fetch it):

1. below the score floor — silence;
2. medium confidence — a single-line hint naming the skill (view command by
   NAME, no paths);
3. high confidence (top score >= the calibrated high threshold AND a clear
   margin over the runner-up, both decided by ``suggest --card``) — a compact
   skill card built from the matched SKILL.md (head of the body, hard-capped,
   with a view-command footer).

Hard guarantees:

- never blocks: the probe runs with a hard timeout (default 2 s,
  ``UNLIMITED_SKILLS_SUGGEST_TIMEOUT`` overrides for tests);
- fail-open: ANY error (missing CLI, bad stdin, timeout, bad JSON,
  unreadable SKILL.md) exits 0 with no output or degrades to the hint;
- no below-floor noise: when `suggest` returns nothing, the hook prints
  nothing;
- kill switch: ``UNLIMITED_SKILLS_NO_INJECT=1`` downgrades tier 3 to the
  tier-2 hint (``--card`` is never requested);
- privacy: the prompt text goes only to the local CLI; nothing is logged
  here, the injected context never echoes the prompt text, and it carries no
  local filesystem paths (skills are referenced by NAME only; the tier-3
  card carries the matched skill's own body BY DESIGN — the one sanctioned
  body channel, see docs/adoption/skill-effectiveness-standard.md).
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _cli_resolve import resolve_cli_command  # noqa: E402

# The suggest CLI emits UTF-8 (it reconfigures its own stdout); the card text
# may carry non-ASCII (em dashes, non-English skill bodies), so the hook pins
# UTF-8 on its whole pipe instead of trusting the Windows locale codepage.
# stdin uses utf-8-sig: some shells (e.g. Windows PowerShell pipes) prepend a
# BOM that json.load would reject; utf-8-sig handles both BOM and no-BOM.
if hasattr(sys.stdin, "reconfigure"):
    sys.stdin.reconfigure(encoding="utf-8-sig", errors="replace")
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

MIN_PROMPT_CHARS = 12
MAX_PROMPT_CHARS = 300
DEFAULT_TIMEOUT_SECONDS = 2.0
KILL_SWITCH_ENV = "UNLIMITED_SKILLS_NO_INJECT"


def _timeout() -> float:
    try:
        return float(os.environ.get("UNLIMITED_SKILLS_SUGGEST_TIMEOUT", DEFAULT_TIMEOUT_SECONDS))
    except ValueError:
        return DEFAULT_TIMEOUT_SECONDS


def _kill_switch_active() -> bool:
    return os.environ.get(KILL_SWITCH_ENV, "").strip().lower() in {"1", "true", "yes", "on"}


def _emit(context: str) -> None:
    print(
        json.dumps(
            {
                "hookSpecificOutput": {
                    "hookEventName": "UserPromptSubmit",
                    "additionalContext": context,
                }
            },
            ensure_ascii=False,
        )
    )


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
        inject_cards = not _kill_switch_active()
        cmd = [*command, "suggest", prompt[:MAX_PROMPT_CHARS], "--json", "--limit", "1"]
        if inject_cards:
            cmd.append("--card")
        proc = subprocess.run(
            cmd,
            capture_output=True,
            encoding="utf-8",
            errors="replace",
            timeout=_timeout(),
        )
        if proc.returncode != 0 or not proc.stdout.strip():
            return 0
        payload_out = json.loads(proc.stdout)
        if not isinstance(payload_out, dict):
            return 0
        # Tier 3: the CLI decided high confidence + margin and built the card.
        card = payload_out.get("skill_card")
        if inject_cards and isinstance(card, dict):
            card_text = str(card.get("card") or "").strip()
            card_name = str(card.get("name") or "").strip()
            if card_text and card_name:
                _emit(card_text)
                return 0
        # Tier 2: one-line, NAME-only hint. Tier 1: silence.
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
        _emit(
            f"Relevant skill available: {name}{origin} — "
            f"view it with: unlimited-skills view {name}"
        )
        return 0
    except Exception:
        # Fail open, fail silent: the probe must never break a prompt.
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
