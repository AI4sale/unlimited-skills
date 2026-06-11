"""Append-only redacted JSONL audit log for MCP meta-tool calls.

Every gateway meta-tool call is recorded as one JSON line with
``ts``, ``tool``, ``upstream``, ``duration_ms``, and ``ok``.

Redaction rules (enforced by :func:`redact`, :func:`looks_secret`, and
:func:`scrub_paths`):

- argument values for keys matching token/secret/key/password/proof/auth/
  credential/cookie/session/signature/cert/private/prompt/env/body/content/
  query/text
  (case-insensitive) are never written, recursively into nested dicts/lists;
- string VALUES that look like secrets are redacted even under harmless
  keys: ``Bearer ...``/``Basic ...`` headers, JWTs, PEM blocks, long hex
  or base64-like blobs;
- environment variable values are never written (the gateway never passes
  them to this module in the first place, and env-shaped keys are redacted
  as a second line of defense);
- skill bodies and upstream tool results are never written -- only shapes
  and counts;
- local filesystem paths (drive, UNC, POSIX home/tmp, ``~/...``) are
  scrubbed from every audited string, including error strings.
"""

from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any

AUDIT_LOG_NAME = "mcp-audit.jsonl"
REDACTED = "[redacted]"
MAX_STRING_CHARS = 120
MAX_ERROR_CHARS = 200

SENSITIVE_KEY_PATTERN = re.compile(
    r"token|secret|key|password|passwd|proof|auth|credential|bearer|cookie|"
    r"session|signature|cert|private|prompt|env\b|environ|body|content|query|text",
    re.IGNORECASE,
)
_PATH_PATTERN = re.compile(
    r"(?:[A-Za-z]:[\\/][^\s'\"]+|\\\\[^\s'\"]+|~[\\/][^\s'\"]+"
    r"|/(?:home|Users|tmp|var|etc|opt)/[^\s'\"]+)"
)

# Obvious secret-shaped VALUES, redacted even when the key looks harmless.
_SECRET_VALUE_PATTERNS = (
    re.compile(r"^\s*(?:bearer|basic|token)\s+\S+", re.IGNORECASE),  # auth header values
    re.compile(r"\beyJ[A-Za-z0-9_-]{8,}"),  # JWT
    re.compile(r"-----BEGIN [A-Z ]*(?:PRIVATE KEY|CERTIFICATE)-----"),  # PEM block
    re.compile(r"[0-9a-fA-F]{32,}"),  # long hex blob
    re.compile(r"[A-Za-z0-9+/_=-]{40,}"),  # long base64-like blob
)


def default_audit_path(root: Path) -> Path:
    """Default audit log location under the skill library root."""
    return root / ".learning" / AUDIT_LOG_NAME


def is_sensitive_key(key: Any) -> bool:
    return isinstance(key, str) and bool(SENSITIVE_KEY_PATTERN.search(key))


def scrub_paths(text: str) -> str:
    """Replace local filesystem paths in free text with a placeholder."""
    return _PATH_PATTERN.sub("[path]", str(text))


def looks_secret(text: str) -> bool:
    """True when a string VALUE is secret-shaped regardless of its key."""
    return any(pattern.search(text) for pattern in _SECRET_VALUE_PATTERNS)


def redact(value: Any) -> Any:
    """Pure redaction of an argument payload before it is audited.

    Sensitive keys lose their values entirely; secret-shaped string values
    are redacted even under harmless keys; remaining strings are capped and
    path scrubbed; nested containers are processed recursively; opaque
    objects collapse to their type name.
    """
    if isinstance(value, dict):
        return {
            str(key): (REDACTED if is_sensitive_key(key) else redact(item))
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [redact(item) for item in value]
    if isinstance(value, str):
        if looks_secret(value):
            return REDACTED
        return scrub_paths(value)[:MAX_STRING_CHARS]
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    return type(value).__name__


class AuditLog:
    """Append-only JSONL audit log with built-in redaction."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)

    def record(
        self,
        tool: str,
        upstream: str = "",
        duration_ms: float = 0.0,
        ok: bool = True,
        arguments: dict | None = None,
        error: str = "",
    ) -> dict:
        row: dict[str, Any] = {
            "ts": time.time(),
            "tool": str(tool),
            "upstream": str(upstream),
            "duration_ms": round(float(duration_ms), 3),
            "ok": bool(ok),
        }
        if arguments is not None:
            row["args"] = redact(arguments)
        if error:
            row["error"] = scrub_paths(error)[:MAX_ERROR_CHARS]
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
        return row
