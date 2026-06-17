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
import socket
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

# Warm multilingual search daemon (`unlimited-skills serve`). A non-English prompt
# IS the signal that this user needs native-language search, so the hook starts the
# daemon in the background — for everyone — so the NEXT native-language lookups are
# fast (~0.3s) instead of a ~14-20s cold load. Idempotent (skips if the port already
# listens), detached, best-effort. Escape hatch for restricted envs: NO_AUTOSERVE.
DAEMON_HOST = "127.0.0.1"
DAEMON_PORT = 8765
NO_AUTOSERVE_ENV = "UNLIMITED_SKILLS_NO_AUTOSERVE"

# Tier-3 fallback (non-English rescue). The lexical engine scores a non-English
# prompt at zero, and a cold multilingual embedding load can exceed the probe
# timeout. In both cases, instead of returning silence, ask the model to do the
# one thing it is uniquely good at across 1000 languages: restate the task as
# English keywords and re-query the router with THAT. No prompt text is echoed.
NON_ENGLISH_INSTRUCTION = (
    "Unlimited Skills — NON-ENGLISH PROMPT, NO IN-BUDGET RESULT. Lexical search "
    "scores non-English at ~0, and without a WARM multilingual daemon every "
    "non-English lookup returns NOTHING inside the hook's short time budget — "
    "that is exactly why no skill was suggested here. DO THIS NOW, do not skip: "
    "restate the user's request as 3-8 English retrieval keywords and run "
    '`unlimited-skills suggest "<English keywords>"` (the English query, not the '
    "raw prompt). Expect ~14-20 seconds the first time (cold embedding-model "
    "load) — that delay is EXPECTED, wait for it — then use the top skill it "
    "returns. The hook has already triggered best-effort background daemon "
    "warming (`unlimited-skills serve`) for future native-language searches; "
    "set UNLIMITED_SKILLS_NO_AUTOSERVE=1 to disable that behavior."
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


def _daemon_listening(host: str = DAEMON_HOST, port: int = DAEMON_PORT) -> bool:
    try:
        with socket.create_connection((host, port), timeout=0.2):
            return True
    except OSError:
        return False


def _start_daemon_warming(command: list[str]) -> None:
    """Start the warm search daemon in the background for non-English users.

    Fire-and-forget: detached, idempotent (no-op if the port already listens),
    best-effort (a missing server extra just dies silently). NEVER blocks or
    raises — the hook returns immediately and the daemon warms for the NEXT prompt.
    """
    if os.environ.get(NO_AUTOSERVE_ENV):
        return
    if _daemon_listening():
        return
    try:
        kwargs: dict = {
            "stdin": subprocess.DEVNULL,
            "stdout": subprocess.DEVNULL,
            "stderr": subprocess.DEVNULL,
        }
        if os.name == "nt":
            # DETACHED_PROCESS (no console at all) | CREATE_NEW_PROCESS_GROUP — survives
            # the hook exit and shows NO window (the scary blank window comes from
            # CREATE_NEW_CONSOLE, which we never use). STARTUPINFO + SW_HIDE is
            # belt-and-suspenders so nothing flashes even via a powershell launcher.
            kwargs["creationflags"] = 0x00000008 | 0x00000200
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            startupinfo.wShowWindow = 0  # SW_HIDE
            kwargs["startupinfo"] = startupinfo
        else:
            kwargs["start_new_session"] = True
        subprocess.Popen([*command, "serve"], **kwargs)
    except Exception:
        return


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
        non_english = _looks_non_english(prompt)
        command = resolve_cli_command()
        if not command:
            return 0
        # A non-English prompt means this user needs native-language search — warm
        # the daemon in the background now (for everyone) so the NEXT lookups are fast.
        if non_english:
            _start_daemon_warming(command)
        inject_cards = not _kill_switch_active()
        cmd = [*command, "suggest", prompt[:MAX_PROMPT_CHARS], "--json", "--limit", "1"]
        if inject_cards:
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
            # No in-budget result. For a NON-ENGLISH prompt this is the expected
            # outcome without a warm multilingual daemon (lexical scores it ~0), so
            # we ALWAYS kick the model to run the search manually rather than fail
            # silently — regardless of whether the CLI set needs_english_query.
            # English no-match stays silent (no false nag).
            if non_english or payload_out.get("needs_english_query") is True:
                _emit(NON_ENGLISH_INSTRUCTION)
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
