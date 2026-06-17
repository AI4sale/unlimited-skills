"""Host lifecycle wrappers for non-Claude agent surfaces.

Claude Code has first-class plugin hooks in this repo. Codex, Hermes, and
OpenClaw do not expose a shared hook file format here, so their host/wrapper
integration gets a small stable CLI surface that records the same Money Saved
event without copying the money logic.
"""

from __future__ import annotations

import argparse

from . import money_saved as money_saved_cmds

SUPPORTED_AGENT_LIFECYCLE_AGENTS = ("codex", "openclaw", "hermes")
EVENT_ALIASES = {
    "session-start": "session_start",
    "session_start": "session_start",
    "pre-compact": "compaction",
    "pre_compact": "compaction",
    "compaction": "compaction",
    "context-rebuild": "context_rebuild",
    "context_rebuild": "context_rebuild",
    "agent-restart": "agent_restart",
    "agent_restart": "agent_restart",
    "manual-reindex-reload": "manual_reindex_reload",
    "manual_reindex_reload": "manual_reindex_reload",
}


def normalize_event_type(value: str) -> str:
    try:
        return EVENT_ALIASES[value]
    except KeyError as exc:
        allowed = ", ".join(sorted(EVENT_ALIASES))
        raise argparse.ArgumentTypeError(f"unsupported lifecycle event {value!r}; expected one of: {allowed}") from exc


def cmd_agent_lifecycle_record(args: argparse.Namespace) -> int:
    """Record one host lifecycle event through the shared Money Saved entrypoint."""
    delegated = argparse.Namespace(**vars(args))
    delegated.event_type = normalize_event_type(getattr(args, "event", "session-start"))
    return money_saved_cmds.cmd_money_saved_record_event(delegated)
