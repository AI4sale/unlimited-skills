"""Stop hook: offer a completed-turn candidate to the local context provider.

The hook never decides that a response is durable knowledge and never blocks a
turn. It sends one bounded, idempotent candidate only when the session has no
in-flight background work. The owner-configured provider applies completion,
evidence, entity, sensitivity, and memory-write policy.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _cli_resolve import resolve_cli_command  # noqa: E402

if hasattr(sys.stdin, "reconfigure"):
    sys.stdin.reconfigure(encoding="utf-8-sig", errors="replace")

MIN_SUMMARY_CHARS = 80
MAX_SUMMARY_CHARS = 16000
DISABLE_ENV = "UNLIMITED_SKILLS_NO_COMPLETION_LEARNING"
PROVIDER_DISABLE_ENV = "UNLIMITED_SKILLS_NO_BUSINESS_CONTEXT"
PROVIDER_CONFIG_ENV = "UNLIMITED_SKILLS_CONTEXT_PROVIDER_CONFIG"
_URL_RE = re.compile(r"https?://[^\s)\]>]+", re.IGNORECASE)
_PR_RE = re.compile(r"(?<!\w)#\d{1,8}\b")
_SHA_RE = re.compile(r"(?<![0-9a-f])[0-9a-f]{7,40}(?![0-9a-f])", re.IGNORECASE)
_VERSION_RE = re.compile(r"\bv?\d+\.\d+\.\d+(?:[a-z0-9.-]+)?\b", re.IGNORECASE)
_TEST_RE = re.compile(r"\b\d+\s+(?:passed|tests? passed|green|skipped)\b", re.IGNORECASE)
_PREFIXED_EVIDENCE_RE = re.compile(r"\b(?:artifact|destination|git|checker|review|ci):[^\s,;]+", re.IGNORECASE)
_RELATIVE_ARTIFACT_RE = re.compile(r"(?<![:/\\])\b(?:[A-Za-z0-9_.-]+[/\\])+[A-Za-z0-9_.-]+\.[A-Za-z0-9]{1,12}(?::\d+)?\b")


def _evidence_refs(text: str) -> list[str]:
    refs: list[str] = []
    for pattern in (_URL_RE, _PR_RE, _SHA_RE, _VERSION_RE, _TEST_RE, _PREFIXED_EVIDENCE_RE, _RELATIVE_ARTIFACT_RE):
        for match in pattern.finditer(text):
            value = match.group(0)
            if value not in refs:
                refs.append(value)
            if len(refs) >= 32:
                return refs
    return refs


def _evidence_is_independently_accepted(refs: list[str]) -> bool:
    artifact = any(
        _URL_RE.fullmatch(ref)
        or _PR_RE.fullmatch(ref)
        or _SHA_RE.fullmatch(ref)
        or _RELATIVE_ARTIFACT_RE.fullmatch(ref)
        or re.match(r"^(?:artifact|destination|git):", ref, re.IGNORECASE)
        for ref in refs
    )
    checker = any(
        _TEST_RE.fullmatch(ref)
        or re.match(r"^(?:checker|review|ci):", ref, re.IGNORECASE)
        for ref in refs
    )
    return artifact and checker and len(set(refs)) >= 2


def _completion_key(payload: dict, summary: str) -> str:
    stable = "\0".join(
        (
            str(payload.get("session_id") or ""),
            str(payload.get("prompt_id") or ""),
            hashlib.sha256(summary.encode("utf-8")).hexdigest(),
        )
    )
    return hashlib.sha256(stable.encode("utf-8")).hexdigest()[:32]


def _truthy(value: str | None) -> bool:
    return str(value or "").strip().casefold() in {"1", "true", "yes", "on"}


def _provider_maybe_configured() -> bool:
    """Avoid spawning a worker on machines that did not opt into a provider."""

    if _truthy(os.environ.get(DISABLE_ENV)) or _truthy(os.environ.get(PROVIDER_DISABLE_ENV)):
        return False
    explicit = str(os.environ.get(PROVIDER_CONFIG_ENV) or "").strip()
    if explicit:
        return Path(explicit).expanduser().is_file()
    home = str(os.environ.get("UNLIMITED_SKILLS_HOME") or "").strip()
    base = Path(home).expanduser() if home else Path.home() / ".unlimited-skills"
    return (base / "business-context-provider.json").is_file()


def _submit_detached(command: list[str], candidate: dict) -> None:
    """Hand a small JSON payload to the CLI without delaying Claude's Stop."""

    kwargs: dict = {
        "stdin": subprocess.PIPE,
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
        "text": True,
        "encoding": "utf-8",
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
        [*command, "context", "completion-candidate", "--json"],
        **kwargs,
    )
    if process.stdin is not None:
        process.stdin.write(json.dumps(candidate, ensure_ascii=False))
        process.stdin.close()


def main() -> int:
    try:
        payload = json.load(sys.stdin)
        if not isinstance(payload, dict) or payload.get("hook_event_name") not in {None, "Stop"}:
            return 0
        if payload.get("stop_hook_active") is True:
            return 0
        if payload.get("background_tasks") or payload.get("session_crons"):
            return 0
        if not _provider_maybe_configured():
            return 0
        summary = str(payload.get("last_assistant_message") or "").strip()[:MAX_SUMMARY_CHARS]
        if len(summary) < MIN_SUMMARY_CHARS:
            return 0
        evidence_refs = _evidence_refs(summary)
        if not _evidence_is_independently_accepted(evidence_refs):
            return 0
        command = resolve_cli_command()
        if not command:
            return 0
        candidate = {
            "completion_key": _completion_key(payload, summary),
            "summary": summary,
            "evidence_refs": evidence_refs,
            "agent": "claude-code",
        }
        _submit_detached(command, candidate)
    except Exception:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
