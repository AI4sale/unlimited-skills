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
- warm-runtime guarantee: the hook starts the local warm daemon when no
  compatible instance is listening; ``UNLIMITED_SKILLS_NO_AUTOSERVE=1`` is the
  emergency escape hatch for restricted runtimes;
- privacy: the prompt text goes only to the local CLI; nothing is logged
  here, the injected context never echoes the prompt text, and it carries no
  local filesystem paths (skills are referenced by NAME only; the tier-3
  card carries the matched skill's own body BY DESIGN — the one sanctioned
  body channel, see docs/adoption/skill-effectiveness-standard.md).
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import socket
import subprocess
import sys
import tempfile
import time
import urllib.parse
import urllib.request
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
NO_AUTOSERVE_ENV = "UNLIMITED_SKILLS_NO_AUTOSERVE"
WARM_DAEMON_URL_ENV = "UNLIMITED_SKILLS_WARM_DAEMON_URL"
DEFAULT_WARM_DAEMON_URL = "http://127.0.0.1:8765"
WARM_DAEMON_PROTOCOL = "warm-search-v1"
DEFAULT_EMBED_MODEL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
HASHED_PORT_BASE = 18000
HASHED_PORT_SPAN = 1000
AUTOSERVE_RETRY_SECONDS = 30.0

# Tier-3 fallback (non-English rescue). The lexical engine scores a non-English
# prompt at zero, and a cold multilingual embedding load can exceed the probe
# timeout. In both cases, instead of returning silence, ask the model to do the
# one thing it is uniquely good at across 1000 languages: restate the task as
# English keywords and re-query the router with THAT. No prompt text is echoed.
NON_ENGLISH_INSTRUCTION_PREFIX = (
    "Unlimited Skills — NON-ENGLISH PROMPT, NO IN-BUDGET RESULT. Lexical search "
    "did not produce a result above the delivery threshold. DO THIS NOW: "
    "restate the user's request as 3-8 English retrieval keywords and run "
    '`unlimited-skills suggest "<English keywords>"` (the English query, not the '
    "raw prompt), then use the top skill it returns. "
)


def _timeout() -> float:
    try:
        return float(os.environ.get("UNLIMITED_SKILLS_SUGGEST_TIMEOUT", DEFAULT_TIMEOUT_SECONDS))
    except ValueError:
        return DEFAULT_TIMEOUT_SECONDS


def _kill_switch_active() -> bool:
    return os.environ.get(KILL_SWITCH_ENV, "").strip().lower() in {"1", "true", "yes", "on"}


def _autoserve_disabled() -> bool:
    return os.environ.get(NO_AUTOSERVE_ENV, "").strip().lower() in {"1", "true", "yes", "on"}


def _daemon_endpoint(command: list[str]) -> tuple[str, int, str] | None:
    explicit = os.environ.get(WARM_DAEMON_URL_ENV, "").strip()
    if explicit:
        raw_url = explicit.rstrip("/")
    else:
        root = _expected_library_root(command)
        default_root = (Path.home() / ".unlimited-skills" / "library").resolve()
        if root is None or root == default_root:
            raw_url = DEFAULT_WARM_DAEMON_URL
        else:
            identity = f"{os.path.normcase(str(root))}\0{os.environ.get('UNLIMITED_SKILLS_EMBED_MODEL', DEFAULT_EMBED_MODEL)}"
            port_value = HASHED_PORT_BASE + (
                int(hashlib.sha256(identity.encode("utf-8")).hexdigest()[:8], 16) % HASHED_PORT_SPAN
            )
            raw_url = f"http://127.0.0.1:{port_value}"
    try:
        parsed = urllib.parse.urlparse(raw_url)
        host = str(parsed.hostname or "")
        port = int(parsed.port or (443 if parsed.scheme == "https" else 80))
    except (TypeError, ValueError):
        return None
    if (
        parsed.scheme != "http"
        or host not in {"127.0.0.1", "localhost", "::1"}
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path not in {"", "/"}
        or parsed.params
        or parsed.query
        or parsed.fragment
    ):
        # Autoserve is deliberately local-only. A configured remote/insecurely
        # shaped endpoint can still be diagnosed by the CLI, but the hook never
        # tries to create it.
        return None
    return host, port, raw_url


def _expected_library_root(command: list[str]) -> Path | None:
    for index, part in enumerate(command):
        if part == "--root" and index + 1 < len(command):
            raw = command[index + 1]
            break
        if part.startswith("--root="):
            raw = part.split("=", 1)[1]
            break
    else:
        raw = os.environ.get("UNLIMITED_SKILLS_ROOT", "").strip()
        if not raw:
            for part in command:
                launcher = Path(str(part))
                if not str(part).lower().endswith((".ps1", ".sh")):
                    continue
                try:
                    text = launcher.read_text(encoding="utf-8", errors="replace")[:65536]
                except OSError:
                    continue
                matches = list(re.finditer(r'--root\s+(?:"([^"]+)"|\'([^\']+)\'|([^\s]+))', text))
                if matches:
                    raw = next(group for group in matches[-1].groups() if group is not None)
                    break
            if not raw and any(str(part).lower().endswith((".ps1", ".sh")) for part in command):
                return None
        if not raw:
            raw = str(Path.home() / ".unlimited-skills" / "library")
    try:
        return Path(raw).expanduser().resolve()
    except (OSError, RuntimeError):
        return None


def _daemon_identity_matches(payload: dict, command: list[str]) -> bool:
    if not (
        payload.get("ok") is True
        and payload.get("service") == "unlimited-skills"
        and payload.get("protocol") == WARM_DAEMON_PROTOCOL
        and str(payload.get("model") or "")
        == os.environ.get("UNLIMITED_SKILLS_EMBED_MODEL", DEFAULT_EMBED_MODEL)
    ):
        return False
    expected_root = _expected_library_root(command)
    if expected_root is None:
        return bool(str(payload.get("root") or "").strip())
    try:
        actual_root = Path(str(payload.get("root") or "")).expanduser().resolve()
    except (OSError, RuntimeError):
        return False
    return actual_root == expected_root


def _daemon_state(command: list[str]) -> str:
    endpoint = _daemon_endpoint(command)
    if endpoint is None:
        return "external_or_invalid"
    host, port, raw_url = endpoint
    try:
        with urllib.request.urlopen(f"{raw_url}/health", timeout=0.2) as response:
            payload = json.loads(response.read().decode("utf-8", errors="replace"))
        if isinstance(payload, dict) and _daemon_identity_matches(payload, command):
            return "ready"
        return "incompatible"
    except Exception:
        try:
            with socket.create_connection((host, port), timeout=0.15):
                return "incompatible"
        except OSError:
            return "missing"


def _launch_marker(command: list[str], raw_url: str) -> Path:
    digest = hashlib.sha256(
        json.dumps([*command, raw_url], ensure_ascii=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()[:16]
    root = _expected_library_root(command)
    home = os.environ.get("UNLIMITED_SKILLS_HOME", "").strip()
    runtime_dir = Path(home).expanduser() / "runtime" if home else (
        root.parent / "runtime" if root is not None else Path(tempfile.gettempdir()) / "unlimited-skills-autoserve"
    )
    return runtime_dir / f"daemon-{digest}.launch"


def _write_daemon_state(command: list[str], raw_url: str, status: str, pid: int | None = None) -> None:
    path = _launch_marker(command, raw_url).with_suffix(".json")
    if pid is None:
        try:
            previous = json.loads(path.read_text(encoding="utf-8"))
            previous_pid = previous.get("pid") if isinstance(previous, dict) else None
            pid = int(previous_pid) if previous_pid else None
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            pid = None
    payload = {
        "schema_version": 1,
        "status": status,
        "pid": pid,
        "endpoint": raw_url,
        "updated_at": time.time(),
    }
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
        os.replace(temporary, path)
    except OSError:
        pass


def _claim_daemon_launch(command: list[str], raw_url: str) -> tuple[bool, Path | None]:
    """Cross-process cooldown against prompt-hook spawn storms."""

    marker = _launch_marker(command, raw_url)
    try:
        marker.parent.mkdir(parents=True, exist_ok=True)
        if marker.exists():
            age = max(0.0, time.time() - marker.stat().st_mtime)
            if age < AUTOSERVE_RETRY_SECONDS:
                return False, marker
            marker.unlink(missing_ok=True)
        fd = os.open(marker, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        try:
            os.write(fd, str(time.time()).encode("ascii"))
        finally:
            os.close(fd)
        return True, marker
    except FileExistsError:
        return False, marker
    except OSError:
        # A read-only temp directory must not disable the owner-required daemon
        # launch. We lose the cooldown but retain best-effort availability.
        return True, None


def _ensure_warm_daemon(command: list[str]) -> str:
    """Start the local daemon when absent; never block the prompt on warming."""

    if _autoserve_disabled():
        return "disabled"
    state = _daemon_state(command)
    if state == "ready":
        endpoint = _daemon_endpoint(command)
        if endpoint is not None:
            try:
                _launch_marker(command, endpoint[2]).unlink(missing_ok=True)
            except OSError:
                pass
            _write_daemon_state(command, endpoint[2], "running")
        return state
    if state != "missing":
        return state
    endpoint = _daemon_endpoint(command)
    if endpoint is None:
        return "external_or_invalid"
    host, port, raw_url = endpoint
    claimed, marker = _claim_daemon_launch(command, raw_url)
    if not claimed:
        return "warming"
    try:
        kwargs: dict = {
            "stdin": subprocess.DEVNULL,
            "stdout": subprocess.DEVNULL,
            "stderr": subprocess.DEVNULL,
        }
        if os.name == "nt":
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            startupinfo.wShowWindow = 0
            kwargs["startupinfo"] = startupinfo
            kwargs["creationflags"] = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
        else:
            kwargs["start_new_session"] = True
        process = subprocess.Popen(
            [*command, "serve", "--host", host, "--port", str(port), "--log-level", "warning"],
            **kwargs,
        )
        _write_daemon_state(command, raw_url, "starting", getattr(process, "pid", None))
        return "starting"
    except Exception:
        if marker is not None:
            try:
                marker.unlink(missing_ok=True)
            except OSError:
                pass
        _write_daemon_state(command, raw_url, "failed")
        return "failed"


def _non_english_instruction(daemon_state: str) -> str:
    """Return truthful, path-free daemon guidance for the current prompt."""

    if daemon_state == "ready":
        runtime = "The local warm daemon is running and compatible."
    elif daemon_state in {"starting", "warming"}:
        runtime = (
            "The hook has requested the local warm daemon start; this request may still use "
            "lexical fallback while the embedding runtime warms."
        )
    elif daemon_state == "disabled":
        runtime = (
            "Automatic daemon startup is disabled by UNLIMITED_SKILLS_NO_AUTOSERVE; "
            "remove that emergency override to restore warm retrieval."
        )
    elif daemon_state == "incompatible":
        runtime = (
            "The configured local port is occupied by an incompatible service; run "
            "`unlimited-skills doctor` before retrying."
        )
    elif daemon_state == "external_or_invalid":
        runtime = (
            "Automatic startup refused a non-local or malformed daemon endpoint; run "
            "`unlimited-skills doctor` to restore the local endpoint."
        )
    elif daemon_state == "failed":
        runtime = (
            "The automatic daemon launch failed; run `unlimited-skills doctor --fix` "
            "to repair the optional server/vector runtime."
        )
    else:
        runtime = "The hook will retry the local warm daemon on the next eligible prompt."
    return NON_ENGLISH_INSTRUCTION_PREFIX + runtime


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
        daemon_state = _ensure_warm_daemon(command)
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
                _emit(_non_english_instruction(daemon_state))
            return 0
        if proc.returncode != 0 or not proc.stdout.strip():
            return 0
        payload_out = json.loads(proc.stdout)
        if not isinstance(payload_out, dict):
            return 0
        if payload_out.get("delivery_tier") == 1:
            if non_english or payload_out.get("needs_english_query") is True:
                _emit(_non_english_instruction(daemon_state))
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
                _emit(_non_english_instruction(daemon_state))
            return 0
        hint = _candidate_hint(candidates)
        if hint:
            rescue = _non_english_instruction(daemon_state) if payload_out.get("needs_english_query") is True else ""
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
