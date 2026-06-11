"""E12B warm tool-index cache tests (``mcp gateway --index-cache``).

Covers the persistent tool-index cache implemented from candidate 1 of the
warm-start plan in docs/mcp-performance.md: strict default-off, cache write
on first live spawn, cache hits serving tools_search/tools_schema without
any spawn, config-hash invalidation, serverInfo version overwrite at spawn,
``refresh: true`` rewrites, corrupt-file tolerance, oversized cached schema
re-validation (refuse, never truncate), atomic writes, and schema-free
audit events. Reuses the fake stdio upstream pattern from
tests/test_mcp_gateway.py with the spawn marker file as the spawn proof.
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

import pytest

from unlimited_skills.mcp.audit import AuditLog
from unlimited_skills.mcp.gateway import (
    SCHEMA_TOO_LARGE,
    Gateway,
    UpstreamError,
    load_gateway_config,
)
from unlimited_skills.mcp.index_cache import (
    CACHE_FILE_NAME,
    CACHE_SCHEMA_VERSION,
    DEFAULT_MAX_AGE_SECONDS,
    IndexCache,
    default_index_cache_path,
    upstream_config_hash,
)

# Fake upstream: appends to the marker file on every spawn and reads its
# serverInfo version from a version file, so the version can change WITHOUT
# changing the config (command/args stay identical -> same config hash).
FAKE_UPSTREAM = r'''
import json
import sys
from pathlib import Path

with open(sys.argv[1], "a", encoding="utf-8") as fh:
    fh.write("spawned\n")

VERSION = Path(sys.argv[2]).read_text(encoding="utf-8").strip()

TOOLS = {
    "echo": {
        "description": "Echo text back",
        "inputSchema": {"type": "object", "properties": {"text": {"type": "string"}}},
    },
    "add": {
        "description": "Add two integers",
        "inputSchema": {"type": "object", "properties": {"a": {"type": "integer"}, "b": {"type": "integer"}}},
    },
}


def send(message):
    sys.stdout.write(json.dumps(message) + "\n")
    sys.stdout.flush()


while True:
    line = sys.stdin.readline()
    if not line:
        break
    line = line.strip()
    if not line:
        continue
    msg = json.loads(line)
    if "id" not in msg:
        continue
    rid = msg["id"]
    method = msg.get("method")
    if method == "initialize":
        send({"jsonrpc": "2.0", "id": rid, "result": {
            "protocolVersion": "2024-11-05",
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "fake", "version": VERSION},
        }})
    elif method == "tools/list":
        send({"jsonrpc": "2.0", "id": rid, "result": {
            "tools": [{"name": name, **info} for name, info in TOOLS.items()],
        }})
    elif method == "tools/call":
        params = msg.get("params") or {}
        name = params.get("name")
        args = params.get("arguments") or {}
        if name == "echo":
            send({"jsonrpc": "2.0", "id": rid, "result": {
                "content": [{"type": "text", "text": "echo:" + str(args.get("text", ""))}],
                "isError": False,
            }})
        elif name == "add":
            send({"jsonrpc": "2.0", "id": rid, "result": {
                "content": [{"type": "text", "text": str(int(args.get("a", 0)) + int(args.get("b", 0)))}],
                "isError": False,
            }})
        else:
            send({"jsonrpc": "2.0", "id": rid, "error": {"code": -32602, "message": "unknown tool"}})
    else:
        send({"jsonrpc": "2.0", "id": rid, "error": {"code": -32601, "message": "unknown method"}})
'''


@pytest.fixture()
def paths(tmp_path: Path) -> dict:
    script = tmp_path / "fake_upstream.py"
    script.write_text(FAKE_UPSTREAM, encoding="utf-8")
    marker = tmp_path / "spawned.marker"
    version_file = tmp_path / "upstream-version.txt"
    version_file.write_text("1.0.0", encoding="utf-8")
    config = {
        "schema_version": 1,
        "upstreams": [
            {
                "name": "fake",
                "command": sys.executable,
                "args": [str(script), str(marker), str(version_file)],
                # Only "echo" is pre-declared: "add" becoming searchable
                # without a spawn proves the cache (not the config) served it.
                "tools": [{"name": "echo", "description": "Echo text back"}],
            }
        ],
    }
    config_path = tmp_path / "gateway-config.json"
    config_path.write_text(json.dumps(config), encoding="utf-8")
    return {
        "tmp": tmp_path,
        "config": config,
        "config_path": config_path,
        "marker": marker,
        "version_file": version_file,
        "audit": tmp_path / "mcp-audit.jsonl",
        "cache_path": tmp_path / "cache" / CACHE_FILE_NAME,
    }


def make_cache(paths: dict) -> IndexCache:
    cache = IndexCache(paths["cache_path"])
    cache.load()
    return cache


def make_gateway(paths: dict, cache: IndexCache | None = None) -> Gateway:
    config = load_gateway_config(paths["config_path"])
    return Gateway(config, AuditLog(paths["audit"]), index_cache=cache)


def spawn_count(paths: dict) -> int:
    if not paths["marker"].exists():
        return 0
    return paths["marker"].read_text(encoding="utf-8").count("spawned")


def config_hash(paths: dict) -> str:
    return upstream_config_hash(load_gateway_config(paths["config_path"])["upstreams"][0])


def cache_doc(paths: dict) -> dict:
    return json.loads(paths["cache_path"].read_text(encoding="utf-8"))


def audit_rows(paths: dict) -> list[dict]:
    text = paths["audit"].read_text(encoding="utf-8")
    return [json.loads(line) for line in text.splitlines() if line.strip()]


def seed_cache(paths: dict) -> None:
    """First gateway run with the cache on: spawn once, write the entry."""
    gateway = make_gateway(paths, make_cache(paths))
    try:
        gateway.tools_schema({"tool": "fake.add"})
    finally:
        gateway.shutdown()
    assert paths["cache_path"].is_file(), "seeding must write the cache file"
    paths["marker"].unlink()  # reset the spawn proof for the next gateway


def test_default_off_no_cache_file_touched(paths: dict) -> None:
    """Without --index-cache nothing cache-shaped is ever read or written."""
    gateway = make_gateway(paths)  # index_cache=None: the default
    try:
        gateway.tools_search({"query": "echo text"})
        gateway.tools_schema({"tool": "fake.add"})
        gateway.tools_call({"tool": "fake.echo", "arguments": {"text": "hi"}})
        assert gateway.upstreams["fake"].on_indexed is None
        assert gateway.upstreams["fake"].config_hash == ""
    finally:
        gateway.shutdown()
    leftovers = [
        p for p in paths["tmp"].rglob("*") if CACHE_FILE_NAME in p.name or ".tmp-" in p.name
    ]
    assert leftovers == [], "default-off must never create cache or temp files"
    # Direct Gateway calls bypass the audited registry handlers, so without
    # the cache no audit file is written at all here -- and with it absent,
    # no cache_loaded/cache_refresh rows can exist either.
    audit_text = paths["audit"].read_text(encoding="utf-8") if paths["audit"].exists() else ""
    assert "cache_loaded" not in audit_text and "cache_refresh" not in audit_text


def test_first_spawn_writes_cache_entry(paths: dict) -> None:
    cache = make_cache(paths)
    gateway = make_gateway(paths, cache)
    try:
        result = gateway.tools_schema({"tool": "fake.add"})
        assert result["inputSchema"]["properties"]["a"]["type"] == "integer"
        assert spawn_count(paths) == 1, "an unseeded cache must not prevent the lazy spawn"
    finally:
        gateway.shutdown()
    doc = cache_doc(paths)
    assert doc["schema_version"] == CACHE_SCHEMA_VERSION
    entry = doc["entries"][config_hash(paths)]
    assert entry["server_info"] == {"name": "fake", "version": "1.0.0"}
    assert set(entry["tools"]) == {"echo", "add"}
    assert entry["tools"]["add"]["inputSchema"]["properties"]["b"]["type"] == "integer"
    assert entry["tools"]["echo"]["description"] == "Echo text back"
    assert isinstance(entry["indexed_at"], float)


def test_cache_hit_serves_search_and_schema_without_spawn(paths: dict) -> None:
    seed_cache(paths)
    gateway = make_gateway(paths, make_cache(paths))
    client = gateway.upstreams["fake"]
    try:
        assert client.indexed_from_cache is True
        assert set(client.tools) == {"echo", "add"}
        # "add" is NOT pre-declared in the config: this hit comes from cache.
        hits = gateway.tools_search({"query": "add integers"})["hits"]
        assert any(hit["tool"] == "fake.add" for hit in hits)
        schema = gateway.tools_schema({"tool": "fake.add"})
        assert schema["inputSchema"]["properties"]["a"]["type"] == "integer"
        assert not paths["marker"].exists(), "a cache hit must not spawn the upstream"
        assert not client.started
        assert client.spawn_count == 0
    finally:
        gateway.shutdown()


def test_tools_call_still_spawns_lazily_and_refreshes(paths: dict) -> None:
    seed_cache(paths)
    gateway = make_gateway(paths, make_cache(paths))
    client = gateway.upstreams["fake"]
    try:
        result = gateway.tools_call({"tool": "fake.add", "arguments": {"a": 2, "b": 3}})
        assert result["content"][0]["text"] == "5"
        assert spawn_count(paths) == 1, "tools_call lazily spawns exactly as before"
        assert client.indexed_from_cache is False, "a live spawn replaces the cached index"
    finally:
        gateway.shutdown()


def test_config_hash_mismatch_invalidates_entry(paths: dict) -> None:
    seed_cache(paths)
    old_hash = config_hash(paths)
    changed = json.loads(json.dumps(paths["config"]))
    changed["upstreams"][0]["env_allowlist"] = ["EXTRA_FAKE_VAR"]
    paths["config_path"].write_text(json.dumps(changed), encoding="utf-8")
    assert config_hash(paths) != old_hash
    gateway = make_gateway(paths, make_cache(paths))
    client = gateway.upstreams["fake"]
    try:
        assert client.indexed_from_cache is False, "a config-hash mismatch must be a miss"
        assert client.tools == {}
        gateway.tools_schema({"tool": "fake.add"})
        assert spawn_count(paths) == 1, "an invalidated entry must force a live spawn"
    finally:
        gateway.shutdown()
    doc = cache_doc(paths)
    assert config_hash(paths) in doc["entries"], "the live spawn writes the new-hash entry"
    assert old_hash in doc["entries"], "old entries are ignored, not destroyed"


def test_server_version_change_overwritten_at_spawn(paths: dict) -> None:
    seed_cache(paths)
    paths["version_file"].write_text("2.0.0", encoding="utf-8")  # config unchanged
    gateway = make_gateway(paths, make_cache(paths))
    try:
        # The cached (now version-stale) entry still serves schema reads...
        gateway.tools_schema({"tool": "fake.add"})
        assert not paths["marker"].exists()
        assert cache_doc(paths)["entries"][config_hash(paths)]["server_info"]["version"] == "1.0.0"
        # ...but the first live spawn discovers the new serverInfo version
        # and overwrites the entry from the real tools/list.
        gateway.tools_call({"tool": "fake.echo", "arguments": {"text": "x"}})
        assert spawn_count(paths) == 1
    finally:
        gateway.shutdown()
    entry = cache_doc(paths)["entries"][config_hash(paths)]
    assert entry["server_info"]["version"] == "2.0.0"


def test_refresh_true_rewrites_cache_entries(paths: dict) -> None:
    seed_cache(paths)
    paths["version_file"].write_text("3.0.0", encoding="utf-8")
    gateway = make_gateway(paths, make_cache(paths))
    client = gateway.upstreams["fake"]
    try:
        assert client.indexed_from_cache is True
        gateway.tools_search({"query": "echo", "refresh": True})
        assert spawn_count(paths) == 1, "refresh:true bypasses the cache and spawns"
        assert client.indexed_from_cache is False
    finally:
        gateway.shutdown()
    entry = cache_doc(paths)["entries"][config_hash(paths)]
    assert entry["server_info"]["version"] == "3.0.0", "refresh must rewrite the entry"


def test_corrupt_cache_file_ignored_and_counted(paths: dict) -> None:
    paths["cache_path"].parent.mkdir(parents=True, exist_ok=True)
    paths["cache_path"].write_text("{{{ this is not json", encoding="utf-8")
    cache = make_cache(paths)
    assert cache.corrupt_discarded == 1
    gateway = make_gateway(paths, cache)  # never crashes
    try:
        rows = [row for row in audit_rows(paths) if row["tool"] == "cache_loaded"]
        assert rows and rows[-1]["entries_corrupt"] == 1
        gateway.tools_schema({"tool": "fake.add"})
        assert spawn_count(paths) == 1
    finally:
        gateway.shutdown()
    assert cache_doc(paths)["schema_version"] == CACHE_SCHEMA_VERSION, (
        "the next live index rewrites a healthy cache file"
    )


def test_unknown_schema_version_and_expired_entries_discarded(paths: dict) -> None:
    paths["cache_path"].parent.mkdir(parents=True, exist_ok=True)
    paths["cache_path"].write_text(
        json.dumps({"schema_version": 99, "entries": {}}), encoding="utf-8"
    )
    cache = make_cache(paths)
    assert cache.corrupt_discarded == 1, "unknown versions are discarded, never migrated"
    stale_entry = {
        "server_info": {"name": "fake", "version": "1.0.0"},
        "indexed_at": time.time() - DEFAULT_MAX_AGE_SECONDS - 60,
        "tools": {"add": {"description": "Add two integers", "inputSchema": {"type": "object"}}},
    }
    paths["cache_path"].write_text(
        json.dumps(
            {"schema_version": CACHE_SCHEMA_VERSION, "entries": {config_hash(paths): stale_entry}}
        ),
        encoding="utf-8",
    )
    cache = make_cache(paths)
    assert cache.expired_discarded == 1
    assert cache.get(config_hash(paths)) is None, "max-age bounds silent drift"


def test_oversized_cached_schema_dropped_to_name_only(paths: dict) -> None:
    # Tighten the upstream's schema cap to the minimum, then plant a cached
    # schema over that cap: load must drop it to a name-only oversized marker.
    changed = json.loads(json.dumps(paths["config"]))
    changed["upstreams"][0]["max_schema_bytes"] = 1024
    paths["config_path"].write_text(json.dumps(changed), encoding="utf-8")
    big_schema = {
        "type": "object",
        "properties": {"blob": {"type": "string", "description": "x" * 5000}},
    }
    entry = {
        "server_info": {"name": "fake", "version": "1.0.0"},
        "indexed_at": time.time(),
        "tools": {
            "bigtool": {"description": "A big cached tool", "inputSchema": big_schema},
            "add": {
                "description": "Add two integers",
                "inputSchema": {"type": "object", "properties": {"a": {"type": "integer"}}},
            },
        },
    }
    paths["cache_path"].parent.mkdir(parents=True, exist_ok=True)
    paths["cache_path"].write_text(
        json.dumps(
            {"schema_version": CACHE_SCHEMA_VERSION, "entries": {config_hash(paths): entry}}
        ),
        encoding="utf-8",
    )
    gateway = make_gateway(paths, make_cache(paths))
    try:
        info = gateway.upstreams["fake"].tools["bigtool"]
        assert info.get("schema_oversized") is True and "inputSchema" not in info
        hits = gateway.tools_search({"query": "bigtool cached"})["hits"]
        assert any(hit["tool"] == "fake.bigtool" for hit in hits), "name-only stays searchable"
        with pytest.raises(UpstreamError) as excinfo:
            gateway.tools_schema({"tool": "fake.bigtool"})
        assert excinfo.value.code == SCHEMA_TOO_LARGE
        assert "never truncated" in str(excinfo.value)
        assert not paths["marker"].exists(), "the refusal must not spawn the upstream"
        # The small cached schema next to it is unaffected.
        assert gateway.tools_schema({"tool": "fake.add"})["inputSchema"]["type"] == "object"
        assert not paths["marker"].exists()
    finally:
        gateway.shutdown()


def test_cache_write_is_atomic(paths: dict, monkeypatch: pytest.MonkeyPatch) -> None:
    replaced: list[tuple[Path, Path]] = []
    real_replace = os.replace

    def spy(src, dst):
        source, destination = Path(src), Path(dst)
        assert source.exists(), "the temp file must be fully written before replace"
        assert source != destination
        replaced.append((source, destination))
        real_replace(src, dst)

    monkeypatch.setattr(os, "replace", spy)
    cache = make_cache(paths)
    assert cache.store(
        "a" * 64,
        {"name": "fake", "version": "1.0.0"},
        {"echo": {"description": "Echo text back", "inputSchema": {"type": "object"}}},
    )
    assert replaced and replaced[-1][1] == paths["cache_path"]
    siblings = list(paths["cache_path"].parent.iterdir())
    assert siblings == [paths["cache_path"]], "no temp files may be left behind"
    assert cache_doc(paths)["entries"]["a" * 64]["tools"]["echo"]["description"] == "Echo text back"


def test_audit_cache_events_present_and_schema_free(paths: dict) -> None:
    seed_cache(paths)
    expected_sha = IndexCache(paths["cache_path"]).file_sha256()
    gateway = make_gateway(paths, make_cache(paths))
    try:
        gateway.tools_schema({"tool": "fake.add"})  # cache hit, no spawn
        gateway.tools_call({"tool": "fake.echo", "arguments": {"text": "x"}})  # spawn + refresh
    finally:
        gateway.shutdown()
    rows = audit_rows(paths)
    loaded = [row for row in rows if row["tool"] == "cache_loaded"]
    refreshed = [row for row in rows if row["tool"] == "cache_refresh"]
    assert loaded and refreshed
    hit_row = loaded[-1]
    assert hit_row["ok"] is True
    assert hit_row["upstreams_loaded"] == ["fake"]
    assert hit_row["tools_loaded"] == 2
    assert hit_row["entries_corrupt"] == 0 and hit_row["entries_expired"] == 0
    assert hit_row["cache_sha256"] == expected_sha
    refresh_row = refreshed[-1]
    assert refresh_row["upstream"] == "fake"
    assert refresh_row["tool_count"] == 2
    assert refresh_row["server_version"] == "1.0.0"
    assert len(refresh_row["cache_sha256"]) == 64
    audit_text = paths["audit"].read_text(encoding="utf-8")
    assert "inputSchema" not in audit_text, "audit rows must never carry schema bodies"
    assert '"properties"' not in audit_text
    assert str(paths["tmp"]) not in audit_text, "audit rows must never carry local paths"
    for row in loaded + refreshed:
        cache_file = row["cache_file"]
        assert cache_file == CACHE_FILE_NAME
        assert "\\" not in cache_file and "/" not in cache_file, "basenames only"


def test_default_index_cache_path(tmp_path: Path) -> None:
    assert default_index_cache_path(tmp_path) == tmp_path / ".learning" / CACHE_FILE_NAME
