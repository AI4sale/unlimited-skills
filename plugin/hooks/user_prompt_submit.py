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

- never blocks: the probe runs with a hard timeout (default 3 s,
  ``UNLIMITED_SKILLS_SUGGEST_TIMEOUT`` overrides for tests);
- fail-open: ANY error (missing CLI, bad stdin, timeout, bad JSON,
  unreadable SKILL.md) exits 0 with no output or degrades to the hint;
- no below-floor noise: when `suggest` returns nothing, the hook prints
  nothing;
- kill switch: ``UNLIMITED_SKILLS_NO_INJECT=1`` downgrades tier 3 to the
  tier-2 hint while retaining card-mode delivery metadata for floor checks;
- service consent: the hook never starts the optional warm daemon or any other
  persistent background process;
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
HOOK_CANDIDATE_LIMIT = 5
HOOK_CANDIDATE_DISPLAY_LIMIT = 5
DEFAULT_TIMEOUT_SECONDS = 3.0
KILL_SWITCH_ENV = "UNLIMITED_SKILLS_NO_INJECT"

# Tier-3 fallback (non-English rescue). The lexical engine scores a non-English
# prompt at zero, and a cold multilingual embedding load can exceed the probe
# timeout. In both cases, instead of returning silence, ask the model to do the
# one thing it is uniquely good at across 1000 languages: restate the task as
# English keywords and re-query the router with THAT. No prompt text is echoed.
NON_ENGLISH_INSTRUCTION = (
    "Unlimited Skills — NON-ENGLISH PROMPT, NO IN-BUDGET RESULT. Lexical search "
    "did not produce a result above the delivery threshold. DO THIS NOW: "
    "restate the user's request as 3-8 English retrieval keywords and run "
    '`unlimited-skills suggest "<English keywords>"` (the English query, not the '
    "raw prompt), then use the top skill it returns. For repeated native-language "
    "retrieval, ask the user for approval before starting the optional warm daemon "
    "with `unlimited-skills serve`; this hook never starts background services."
)


def _timeout() -> float:
    try:
        return float(os.environ.get("UNLIMITED_SKILLS_SUGGEST_TIMEOUT", DEFAULT_TIMEOUT_SECONDS))
    except ValueError:
        return DEFAULT_TIMEOUT_SECONDS


def _kill_switch_active() -> bool:
    return os.environ.get(KILL_SWITCH_ENV, "").strip().lower() in {"1", "true", "yes", "on"}


def _looks_non_english(text: str) -> bool:
    """Latin-letters heuristic, inlined (the hook is standalone, no package import).

    Used only on the timeout path, where the probe was killed before it could
    report needs_english_query — so the hook decides whether to nudge.
    """
    letters = [c for c in (text or "") if c.isalpha()]
    if not letters:
        return False
    ascii_letters = sum(1 for c in letters if c.isascii())
    return (ascii_letters / len(letters)) < 0.6


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


def _candidate_hint(candidates: list[dict]) -> str:
    items: list[tuple[str, str]] = []
    for candidate in candidates[:HOOK_CANDIDATE_DISPLAY_LIMIT]:
        if not isinstance(candidate, dict):
            continue
        name = str(candidate.get("name") or "").strip()
        source = str(candidate.get("source") or "").strip()
        if not name:
            continue
        items.append((name, source))
    if not items:
        return ""
    if len(items) == 1:
        name, source = items[0]
        origin = f" (from the {source} pack)" if source else ""
        return f"Relevant skill available: {name}{origin} — view it with: unlimited-skills view {name}"
    names = [f"{name} ({source})" if source else name for name, source in items]
    view_commands = ", ".join(f"unlimited-skills view {item.split(' (', 1)[0]}" for item in names[:3])
    return (
        "Relevant skill candidates: "
        + ", ".join(names)
        + ". Review the best fit by name; suggested commands: "
        + view_commands
    )


def main() -> int:
    try:
        payload = json.load(sys.stdin)
        prompt = str(payload.get("prompt") or "")
        prompt = " ".join(prompt.split())
        if len(prompt) < MIN_PROMPT_CHARS:
            return 0
        non_english = _looks_non_english(prompt)
        command = resolve_cli_command()
        if not command:
            return 0
        inject_cards = not _kill_switch_active()
        cmd = [*command, "suggest", prompt[:MAX_PROMPT_CHARS], "--json", "--limit", str(HOOK_CANDIDATE_LIMIT)]
        # Always request tier metadata. The CLI's kill switch suppresses the
        # body-bearing card while preserving floor enforcement.
        cmd.append("--card")
        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                encoding="utf-8",
                errors="replace",
                timeout=_timeout(),
            )
        except subprocess.TimeoutExpired:
            # Slowest path is a cold multilingual embedding load on a non-English
            # prompt; ask for an English re-query rather than block or fall silent.
            # English prompts that time out stay silent (fail-open, no false nag).
            if non_english:
                _emit(NON_ENGLISH_INSTRUCTION)
            return 0
        if proc.returncode != 0 or not proc.stdout.strip():
            return 0
        payload_out = json.loads(proc.stdout)
        if not isinstance(payload_out, dict):
            return 0
        if payload_out.get("delivery_tier") == 1:
            if non_english or payload_out.get("needs_english_query") is True:
                _emit(NON_ENGLISH_INSTRUCTION)
            return 0
        # Tier 3: the CLI decided high confidence + margin and built the card.
        card = payload_out.get("skill_card")
        if inject_cards and isinstance(card, dict):
            card_text = str(card.get("card") or "").strip()
            card_name = str(card.get("name") or "").strip()
            if card_text and card_name:
                candidates = payload_out.get("delivery_candidates")
                hint = _candidate_hint(candidates) if isinstance(candidates, list) and len(candidates) > 1 else ""
                _emit(card_text + ("\n\n" + hint if hint else ""))
                return 0
        # Tier 2: one-line, NAME-only hint. Tier 1: silence.
        candidates = payload_out.get("delivery_candidates")
        if not isinstance(candidates, list) or not candidates:
            # No in-budget result. For a NON-ENGLISH prompt this is the expected
            # outcome without a warm multilingual daemon (lexical scores it ~0), so
            # we ALWAYS kick the model to run the search manually rather than fail
            # silently — regardless of whether the CLI set needs_english_query.
            # English no-match stays silent (no false nag).
            if non_english or payload_out.get("needs_english_query") is True:
                _emit(NON_ENGLISH_INSTRUCTION)
            return 0
        hint = _candidate_hint(candidates)
        if hint:
            rescue = NON_ENGLISH_INSTRUCTION if payload_out.get("needs_english_query") is True else ""
            _emit(hint + ("\n\n" + rescue if rescue else ""))
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
