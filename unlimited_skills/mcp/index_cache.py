"""Persistent MCP tool-index cache for the Unlimited Tools gateway (opt-in).

Implements candidate 1 of the warm-start optimization plan in
docs/mcp-performance.md: serialize each upstream's indexed tool entries
(name, description, ``inputSchema`` or the oversized marker) to one local
JSON cache file so a restarted gateway can answer ``tools_schema`` (and
richer ``tools_search``) without spawning the upstream at all.

Strictly default-off: nothing in this module runs unless the operator passes
``mcp gateway --index-cache``. Without the flag the gateway behaves
byte-for-byte as before.

Keying and invalidation (the plan's rules):

- each entry is keyed by the SHA-256 of the upstream's canonical spec --
  the fields that affect what the upstream serves and how it is indexed
  (name, command, args, env_allowlist names, cwd, trust level, enabled,
  size limits). Any config change yields a different hash, so the old
  entry is simply never matched again;
- the upstream's ``serverInfo`` name+version captured at index time is
  stored in the entry; a live spawn always re-indexes and overwrites the
  entry, so a version change discovered at spawn never lingers;
- entries older than ``max_age_seconds`` (default 7 days) are ignored at
  load, bounding silent drift;
- a corrupt or malformed cache file (or entry) is ignored and counted,
  never a crash; unknown ``schema_version`` values are discarded, never
  migrated silently.

Loaded entries are treated as untrusted input: the gateway re-validates
cached schemas against the same ``max_schema_bytes`` ceilings as a live
index (refuse, never truncate). Cache files contain only what the gateway
already had in memory -- tool names, descriptions, and input schemas from
upstreams -- never environment values, credentials, or call arguments.
Writes are atomic (temp file + ``os.replace``) and best-effort: a cache
write failure never breaks a live call.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from pathlib import Path
from typing import Any

CACHE_FILE_NAME = "mcp-tool-index-cache.json"
CACHE_SCHEMA_VERSION = 1
DEFAULT_MAX_AGE_SECONDS = 7 * 24 * 60 * 60  # 7 days, per the warm-start plan

# Upstream spec fields that affect what the upstream serves / how the gateway
# indexes it. Fixed in code: timeouts and audit settings deliberately excluded
# (they change behavior, not the served tool set).
_HASHED_SPEC_FIELDS = (
    "name",
    "command",
    "args",
    "env_allowlist",
    "cwd",
    "trust_level",
    "enabled",
    "max_schema_bytes",
    "max_response_bytes",
)


def default_index_cache_path(root: Path) -> Path:
    """Default cache file location: next to the audit log under the library."""
    return Path(root) / ".learning" / CACHE_FILE_NAME


def upstream_config_hash(spec: dict) -> str:
    """SHA-256 of the canonical upstream spec (the cache entry key)."""
    canonical = {key: spec.get(key) for key in _HASHED_SPEC_FIELDS if key in spec}
    payload = json.dumps(canonical, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _valid_tools_map(tools: Any) -> bool:
    if not isinstance(tools, dict) or not tools:
        return False
    for name, info in tools.items():
        if not isinstance(name, str) or not name or not isinstance(info, dict):
            return False
        if not isinstance(info.get("description", ""), str):
            return False
    return True


def _valid_entry(entry: Any) -> bool:
    if not isinstance(entry, dict):
        return False
    server_info = entry.get("server_info")
    indexed_at = entry.get("indexed_at")
    if not isinstance(server_info, dict):
        return False
    if isinstance(indexed_at, bool) or not isinstance(indexed_at, (int, float)):
        return False
    return _valid_tools_map(entry.get("tools"))


class IndexCache:
    """One JSON document mapping config-hash -> serialized tool index.

    ``load()`` never raises on bad input: corrupt files and malformed
    entries are dropped and counted in ``corrupt_discarded``; entries past
    ``max_age_seconds`` are dropped and counted in ``expired_discarded``.
    ``store()`` is atomic and best-effort.
    """

    def __init__(self, path: Path, max_age_seconds: float = DEFAULT_MAX_AGE_SECONDS) -> None:
        self.path = Path(path)
        self.max_age_seconds = float(max_age_seconds)
        self._entries: dict[str, dict] = {}
        self.corrupt_discarded = 0
        self.expired_discarded = 0

    def load(self) -> None:
        self._entries = {}
        self.corrupt_discarded = 0
        self.expired_discarded = 0
        try:
            raw = self.path.read_text(encoding="utf-8")
        except OSError:
            return  # no cache file yet: a clean miss, never an error
        try:
            data = json.loads(raw)
        except (json.JSONDecodeError, ValueError):
            self.corrupt_discarded += 1
            return
        if not isinstance(data, dict) or data.get("schema_version") != CACHE_SCHEMA_VERSION:
            # Unknown versions/shapes are discarded, never migrated silently.
            self.corrupt_discarded += 1
            return
        entries = data.get("entries")
        if not isinstance(entries, dict):
            self.corrupt_discarded += 1
            return
        now = time.time()
        for config_hash, entry in entries.items():
            if not isinstance(config_hash, str) or not _valid_entry(entry):
                self.corrupt_discarded += 1
                continue
            if now - float(entry["indexed_at"]) > self.max_age_seconds:
                self.expired_discarded += 1
                continue
            self._entries[config_hash] = entry

    def get(self, config_hash: str) -> dict | None:
        return self._entries.get(config_hash)

    def store(self, config_hash: str, server_info: dict, tools: dict) -> bool:
        """Overwrite one entry from a live index and rewrite the file.

        The tools map is deep-copied via JSON so later in-memory mutation of
        the gateway's live index can never alter the stored entry. Returns
        True when the file was written; False on any (swallowed) failure --
        a cache write failure must never break a live call.
        """
        try:
            entry = {
                "server_info": {
                    "name": str(server_info.get("name") or ""),
                    "version": str(server_info.get("version") or ""),
                },
                "indexed_at": time.time(),
                "tools": json.loads(json.dumps(tools, ensure_ascii=False)),
            }
        except (TypeError, ValueError):
            return False
        self._entries[str(config_hash)] = entry
        return self._write()

    def _write(self) -> bool:
        document = {"schema_version": CACHE_SCHEMA_VERSION, "entries": self._entries}
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temp = self.path.with_name(f"{self.path.name}.tmp-{os.getpid()}")
            temp.write_text(
                json.dumps(document, ensure_ascii=False, sort_keys=True), encoding="utf-8"
            )
            os.replace(temp, self.path)  # atomic on POSIX and Windows
        except OSError:
            return False
        return True

    def file_sha256(self) -> str:
        """SHA-256 of the cache file as it exists on disk ('' when absent)."""
        try:
            return hashlib.sha256(self.path.read_bytes()).hexdigest()
        except OSError:
            return ""
