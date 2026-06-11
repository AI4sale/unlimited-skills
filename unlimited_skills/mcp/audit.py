"""Append-only redacted JSONL audit log for MCP meta-tool calls.

Every gateway meta-tool call is recorded as one JSON line with
``ts``, ``tool``, ``upstream``, ``duration_ms``, and ``ok``.

Redaction rules (enforced by :func:`redact` and :func:`scrub_paths`):

- argument values for keys matching token/secret/key/password/proof/
  authorization (case-insensitive) are never written;
- environment variable values are never written (the gateway never passes
  them to this module in the first place);
- skill bodies and upstream tool results are never written -- only shapes
  and counts;
- local filesystem paths are scrubbed from error strings.
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

SENSITIVE_KEY_PATTERN = re.compile(r"token|secret|key|password|proof|authorization", re.IGNORECASE)
_PATH_PATTERN = re.compile(
    r"(?:[A-Za-z]:[\\/][^\s'\"]+|\\\\[^\s'\"]+|/(?:home|Users|tmp|var|etc|opt)/[^\s'\"]+)"
)


def default_audit_path(root: Path) -> Path:
    """Default audit log location under the skill library root."""
    return root / ".learning" / AUDIT_LOG_NAME


def is_sensitive_key(key: Any) -> bool:
    return isinstance(key, str) and bool(SENSITIVE_KEY_PATTERN.search(key))


def scrub_paths(text: str) -> str:
    """Replace local filesystem paths in free text with a placeholder."""
    return _PATH_PATTERN.sub("[path]", str(text))


def redact(value: Any) -> Any:
    """Pure redaction of an argument payload before it is audited.

    Sensitive keys lose their values entirely; strings are capped and path
    scrubbed; nested containers are processed recursively; opaque objects
    collapse to their type name.
    """
    if isinstance(value, dict):
        return {
            str(key): (REDACTED if is_sensitive_key(key) else redact(item))
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [redact(item) for item in value]
    if isinstance(value, str):
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
