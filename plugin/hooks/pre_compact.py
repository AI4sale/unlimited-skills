"""PreCompact hook: record a Money Saved 'compaction' context-load event.

On every compaction the standing skill/MCP context is re-written to the model's
cache, so each compaction is a Money Saved event (priced at cache_write_5m).
Resolves the CLI via the shared fallback chain and fires
``money-saved record-event compaction --agent claude-code``. Fast (bytes//4, no API), short timeout,
fully guarded — it must NEVER block or fail the session. Opt out with
``UNLIMITED_SKILLS_NO_MONEY_EVENTS``.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _cli_resolve import resolve_cli_command  # noqa: E402

_MONEY_EVENT_TIMEOUT_SECONDS = 10.0


def main() -> int:
    if os.environ.get("UNLIMITED_SKILLS_NO_MONEY_EVENTS"):
        return 0
    try:
        command = resolve_cli_command()
    except Exception:
        command = None
    if command:
        try:
            subprocess.run(
                [*command, "money-saved", "record-event", "compaction", "--agent", "claude-code"],
                capture_output=True,
                timeout=_MONEY_EVENT_TIMEOUT_SECONDS,
            )
        except Exception:
            pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
