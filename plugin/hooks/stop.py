"""Non-blocking Stop handoff for host-supplied signed receipts only.

Assistant prose, URLs, hashes, test counts, cwd scans, and tool logs are never
examined.  The private provider authenticates Ed25519 and owns every write.
"""
from __future__ import annotations

import json
import os
import stat
import subprocess
import sys
from pathlib import Path
from typing import Any

from _cli_resolve import resolve_cli_command


DISABLE_ENV = "UNLIMITED_SKILLS_NO_COMPLETION_MEMORY"
INBOX_ENV = "UNLIMITED_SKILLS_COMPLETION_RECEIPT_INBOX"
MAX_EVENT_BYTES = 262_144
MAX_RECEIPT_BYTES = 32_768
SUBMIT_TIMEOUT_SECONDS = 2.0


def _truthy(value: str | None) -> bool:
    return str(value or "").strip().casefold() in {"1", "true", "yes", "on"}


def _strict_object(raw: bytes, maximum: int) -> dict[str, Any] | None:
    if not raw or len(raw) > maximum:
        return None

    def unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        value: dict[str, Any] = {}
        for key, item in pairs:
            if key in value:
                raise ValueError("duplicate JSON property")
            value[key] = item
        return value

    try:
        parsed = json.loads(raw.decode("utf-8"), object_pairs_hook=unique_object)
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError):
        return None
    return parsed if isinstance(parsed, dict) else None


def _inbox_receipt(name: Any) -> dict[str, Any] | None:
    if not isinstance(name, str) or not name or len(name) > 240 or "\x00" in name:
        return None
    inbox_raw = os.environ.get(INBOX_ENV, "").strip()
    if not inbox_raw:
        return None
    requested = Path(name)
    if requested.is_absolute() or any(part in {"", ".", ".."} for part in requested.parts):
        return None
    descriptor: int | None = None
    try:
        inbox = Path(inbox_raw).expanduser().resolve(strict=True)
        candidate = inbox / requested
        attributes = getattr(os.lstat(candidate), "st_file_attributes", 0)
        if attributes & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0):
            return None
        flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(candidate, flags)
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            return None
        if os.name == "nt":
            import ctypes
            import msvcrt

            handle = msvcrt.get_osfhandle(descriptor)
            buffer = ctypes.create_unicode_buffer(32_768)
            length = ctypes.windll.kernel32.GetFinalPathNameByHandleW(handle, buffer, len(buffer), 0)
            if not length or length >= len(buffer):
                return None
            final_name = buffer.value
            if final_name.startswith("\\\\?\\UNC\\"):
                final_name = "\\\\" + final_name[8:]
            elif final_name.startswith("\\\\?\\"):
                final_name = final_name[4:]
            opened_path = Path(final_name).resolve(strict=True)
        else:
            proc_path = Path(f"/proc/self/fd/{descriptor}")
            opened_path = proc_path.resolve(strict=True) if proc_path.exists() else candidate.resolve(strict=True)
        opened_path.relative_to(inbox)
        chunks: list[bytes] = []
        remaining = MAX_RECEIPT_BYTES + 1
        while remaining:
            chunk = os.read(descriptor, remaining)
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        return _strict_object(b"".join(chunks), MAX_RECEIPT_BYTES)
    except (OSError, ValueError):
        return None
    finally:
        if descriptor is not None:
            try:
                os.close(descriptor)
            except OSError:
                pass


def _trusted_receipt(event: dict[str, Any]) -> dict[str, Any] | None:
    inline = event.get("trusted_completion_receipt")
    if isinstance(inline, dict):
        try:
            raw = json.dumps(inline, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        except (TypeError, ValueError):
            return None
        return _strict_object(raw, MAX_RECEIPT_BYTES)
    return _inbox_receipt(event.get("trusted_completion_receipt_file"))


def main() -> int:
    if _truthy(os.environ.get(DISABLE_ENV)):
        return 0
    try:
        raw_event = sys.stdin.buffer.read(MAX_EVENT_BYTES + 1)
    except OSError:
        return 0
    event = _strict_object(raw_event, MAX_EVENT_BYTES)
    if event is None:
        return 0
    receipt = _trusted_receipt(event)
    if receipt is None:
        return 0
    command = resolve_cli_command()
    if not command:
        return 0
    kwargs: dict[str, Any] = {
        "input": json.dumps(receipt, ensure_ascii=False, separators=(",", ":")),
        "stdin": subprocess.PIPE,
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
        "text": True,
        "encoding": "utf-8",
        "timeout": SUBMIT_TIMEOUT_SECONDS,
        "check": False,
    }
    # ``input`` already supplies stdin; keep the explicit key out of the final
    # kwargs to avoid subprocess.run's duplicate-stdin guard.
    kwargs.pop("stdin")
    if os.name == "nt":
        kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
    try:
        subprocess.run(
            [*command, "context", "completion-receipt", "--stdin", "--json"],
            **kwargs,
        )
    except (OSError, subprocess.TimeoutExpired):
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
