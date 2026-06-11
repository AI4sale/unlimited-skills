"""E10: the gateway ENFORCES the E09 permissioned tool profiles design.

Proves, against a fake subprocess upstream (same fixture pattern as
``tests/test_mcp_gateway.py``), the contract of
docs/mcp-permissioned-tool-profiles.md:

- no-profiles mode is byte-for-byte the open behavior (the default);
- hidden tools are absent from ``tools_search`` (pre-declared and
  live-indexed alike) and refresh never spawns an upstream that cannot
  contribute a visible tool;
- ``tools_schema``/``tools_call`` refuse invisible tools with the
  existence-neutral ``-32011`` BEFORE any existence check or lazy spawn --
  a hidden tool is indistinguishable from a nonexistent one;
- visible-but-not-callable tools are refused by ``tools_call`` with
  ``-32012`` (no spawn) while their schemas stay fetchable;
- missing/invalid profiles fail closed (``-32013``/``-32014``) for every
  operation, never falling back to open behavior;
- ``extends`` is restriction-only intersection; cycles/self-extends/dangling
  parents/over-deep chains/uncovered callable rules are load errors;
- selection precedence is ``--profile`` > ``UNLIMITED_SKILLS_MCP_PROFILE`` >
  ``default_profile``;
- every audit row carries the profile name, a ``profile_loaded`` startup row
  pins the file SHA-256, and the existing redaction floor is untouched.
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pytest

from unlimited_skills.mcp.audit import AuditLog
from unlimited_skills.mcp.gateway import (
    PROFILE_INVALID,
    PROFILE_NOT_FOUND,
    TOOL_NOT_CALLABLE,
    TOOL_NOT_VISIBLE,
    Gateway,
    UpstreamError,
    build_gateway_registry,
    load_gateway_config,
)
from unlimited_skills.mcp.profiles import (
    PROFILE_ENV_VAR,
    ActiveProfile,
    FailClosedProfile,
    ProfileLoadError,
    load_profile_document,
    resolve_profile_state,
)
from unlimited_skills.mcp.protocol import ToolError

FAKE_UPSTREAM = r'''
import json
import sys

with open(sys.argv[1], "a", encoding="utf-8") as fh:
    fh.write("spawned\n")

TOOLS = {
    "echo": {
        "description": "Echo text back",
        "inputSchema": {"type": "object", "properties": {"text": {"type": "string"}}},
    },
    "add": {
        "description": "Add two integers",
        "inputSchema": {"type": "object", "properties": {"a": {"type": "integer"}, "b": {"type": "integer"}}},
    },
    "secret_wipe": {
        "description": "Wipe the secret data storage",
        "inputSchema": {"type": "object", "properties": {"confirm": {"type": "boolean"}}},
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
            "serverInfo": {"name": "fake", "version": "0.0.1"},
        }})
    elif method == "tools/list":
        send({"jsonrpc": "2.0", "id": rid, "result": {
            "tools": [{"name": name, **info} for name, info in TOOLS.items()],
        }})
    elif method == "tools/call":
        params = msg.get("params") or {}
        name = params.get("name")
        args = params.get("arguments") or {}
        if name in TOOLS:
            send({"jsonrpc": "2.0", "id": rid, "result": {
                "content": [{"type": "text", "text": name + ":" + json.dumps(args, sort_keys=True)}],
                "isError": False,
            }})
        else:
            send({"jsonrpc": "2.0", "id": rid, "error": {"code": -32602, "message": "unknown tool"}})
    else:
        send({"jsonrpc": "2.0", "id": rid, "error": {"code": -32601, "message": "unknown method"}})
'''

PROFILE_DOCUMENT = {
    "schema_version": 1,
    "default_profile": "dev",
    "profiles": {
        # Root ceiling: everything on both upstreams.
        "dev": {"visible": ["fake.*", "other.*"], "callable": ["fake.*", "other.*"]},
        # Narrower child: two visible tools on 'fake', only one callable;
        # 'fake.secret_wipe' and all of 'other' are hidden.
        "reviewer": {
            "extends": "dev",
            "visible": ["fake.echo", "fake.add"],
            "callable": ["fake.echo"],
        },
        # Grandchild narrows further.
        "narrow": {"extends": "reviewer", "visible": ["fake.echo"], "callable": ["fake.echo"]},
        # Declares nothing: inherits reviewer's sets unchanged.
        "inheritor": {"extends": "reviewer"},
        # Tries to re-widen under the 'narrow' ceiling: restriction-only
        # intersection must keep it at 'fake.echo' only.
        "wide-child": {"extends": "narrow", "visible": ["fake.*"], "callable": ["fake.*"]},
        # Root profile with no rule fields: default deny has no implicit allow.
        "empty": {},
    },
}


@pytest.fixture()
def fixture_paths(tmp_path: Path) -> dict:
    script = tmp_path / "fake_upstream.py"
    script.write_text(FAKE_UPSTREAM, encoding="utf-8")
    marker = tmp_path / "spawned-fake.marker"
    other_marker = tmp_path / "spawned-other.marker"
    config = {
        "schema_version": 1,
        "upstreams": [
            {
                "name": "fake",
                "command": sys.executable,
                "args": [str(script), str(marker)],
                "tools": [
                    {"name": "echo", "description": "Echo text back"},
                    {"name": "add", "description": "Add two integers"},
                    {"name": "secret_wipe", "description": "Wipe the secret data storage"},
                ],
            },
            {
                "name": "other",
                "command": sys.executable,
                "args": [str(script), str(other_marker)],
                "tools": [{"name": "shred", "description": "Shred documents permanently"}],
            },
        ],
    }
    config_path = tmp_path / "gateway-config.json"
    config_path.write_text(json.dumps(config), encoding="utf-8")
    profile_path = tmp_path / "tool-profiles.json"
    profile_path.write_text(json.dumps(PROFILE_DOCUMENT), encoding="utf-8")
    return {
        "config_path": config_path,
        "profile_path": profile_path,
        "marker": marker,
        "other_marker": other_marker,
        "audit": tmp_path / "mcp-audit.jsonl",
    }


def make_gateway(fixture_paths: dict, profile_name: str | None = None) -> Gateway:
    """Gateway in no-profiles mode (None) or enforcing one named profile."""
    config = load_gateway_config(fixture_paths["config_path"])
    profile = None
    if profile_name is not None:
        profile = resolve_profile_state(
            fixture_paths["profile_path"], cli_name=profile_name, env_name=""
        )
    return Gateway(config, AuditLog(fixture_paths["audit"]), profile=profile)


def audit_rows(fixture_paths: dict) -> list[dict]:
    text = fixture_paths["audit"].read_text(encoding="utf-8")
    return [json.loads(line) for line in text.splitlines() if line.strip()]


def write_profiles(tmp_path: Path, document: dict) -> Path:
    path = tmp_path / "profiles-variant.json"
    path.write_text(json.dumps(document), encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# No-profiles mode: the current open behavior, exactly unchanged.


def test_no_profiles_mode_unchanged(fixture_paths: dict) -> None:
    gateway = make_gateway(fixture_paths)
    registry = build_gateway_registry(gateway)
    try:
        result = registry["tools_search"]["handler"]({"query": "secret wipe"})
        assert [hit["tool"] for hit in result["hits"]] == ["fake.secret_wipe"]
        assert all("callable" not in hit for hit in result["hits"]), (
            "no-profiles hits must keep the exact current shape"
        )
        call = registry["tools_call"]["handler"](
            {"tool": "fake.secret_wipe", "arguments": {"confirm": True}}
        )
        assert call["isError"] is False
        registry["tools_schema"]["handler"]({"tool": "fake.add"})
    finally:
        gateway.shutdown()
    rows = audit_rows(fixture_paths)
    assert rows, "calls are audited"
    assert all("profile" not in row for row in rows), (
        "the absent profile field is the unambiguous marker of open mode"
    )
    assert all(row["tool"] != "profile_loaded" for row in rows)


# ---------------------------------------------------------------------------
# Visibility: search filtering, hidden tools, and refresh spawn policy.


def test_search_hides_invisible_tools_predeclared(fixture_paths: dict) -> None:
    gateway = make_gateway(fixture_paths, "reviewer")
    try:
        assert gateway.tools_search({"query": "secret wipe"})["hits"] == []
        assert gateway.tools_search({"query": "shred documents"})["hits"] == []
        echo_hits = gateway.tools_search({"query": "echo text"})["hits"]
        assert [hit["tool"] for hit in echo_hits] == ["fake.echo"]
        assert echo_hits[0]["callable"] is True
        add_hits = gateway.tools_search({"query": "add integers"})["hits"]
        assert [hit["tool"] for hit in add_hits] == ["fake.add"]
        assert add_hits[0]["callable"] is False, "visible-but-not-callable is marked"
        assert not fixture_paths["marker"].exists(), "plain search never spawns"
    finally:
        gateway.shutdown()


def test_search_refresh_hides_live_indexed_tools_and_skips_invisible_upstreams(
    fixture_paths: dict,
) -> None:
    gateway = make_gateway(fixture_paths, "reviewer")
    try:
        gateway.tools_search({"query": "echo", "refresh": True})
        assert fixture_paths["marker"].exists(), "'fake' has visible tools: refresh may spawn it"
        assert not fixture_paths["other_marker"].exists(), (
            "refresh must never spawn an upstream that cannot contribute a visible tool"
        )
        # The live index now contains secret_wipe; it must stay hidden.
        assert gateway.upstreams["fake"].indexed
        assert "secret_wipe" in gateway.upstreams["fake"].tools
        assert gateway.tools_search({"query": "secret wipe"})["hits"] == []
        assert gateway.tools_search({"query": "shred documents"})["hits"] == []
    finally:
        gateway.shutdown()


def test_schema_hidden_tool_refused_without_spawn(fixture_paths: dict) -> None:
    gateway = make_gateway(fixture_paths, "reviewer")
    try:
        with pytest.raises(UpstreamError) as excinfo:
            gateway.tools_schema({"tool": "fake.secret_wipe"})
        assert excinfo.value.code == TOOL_NOT_VISIBLE
        assert "tool_not_visible" in str(excinfo.value)
        assert not fixture_paths["marker"].exists(), (
            "a hidden tool must never trigger a lazy spawn"
        )
        assert not gateway.upstreams["fake"].started
    finally:
        gateway.shutdown()


def test_hidden_and_nonexistent_are_indistinguishable(fixture_paths: dict) -> None:
    """Existence-neutrality: same code, same message shape, no spawn."""
    gateway = make_gateway(fixture_paths, "reviewer")
    try:
        shapes = {}
        for fq in ("fake.secret_wipe", "fake.does_not_exist", "ghost.anything"):
            for method in (gateway.tools_schema, gateway.tools_call):
                with pytest.raises(UpstreamError) as excinfo:
                    method({"tool": fq})
                assert excinfo.value.code == TOOL_NOT_VISIBLE, (fq, method)
                shapes[(fq, method.__name__)] = str(excinfo.value).replace(fq, "<tool>")
        assert len(set(shapes.values())) == 1, (
            f"hidden vs nonexistent must be byte-identical refusals: {shapes}"
        )
        assert not fixture_paths["marker"].exists()
        assert not fixture_paths["other_marker"].exists()
    finally:
        gateway.shutdown()


# ---------------------------------------------------------------------------
# Callability: -32012 only after visibility passes; schema stays readable.


def test_call_hidden_tool_refused(fixture_paths: dict) -> None:
    gateway = make_gateway(fixture_paths, "reviewer")
    try:
        with pytest.raises(UpstreamError) as excinfo:
            gateway.tools_call({"tool": "fake.secret_wipe", "arguments": {"confirm": True}})
        assert excinfo.value.code == TOOL_NOT_VISIBLE, (
            "an invisible tool is tool_not_visible, never tool_not_callable"
        )
        assert not fixture_paths["marker"].exists()
    finally:
        gateway.shutdown()


def test_call_visible_but_not_callable(fixture_paths: dict) -> None:
    gateway = make_gateway(fixture_paths, "reviewer")
    try:
        with pytest.raises(UpstreamError) as excinfo:
            gateway.tools_call({"tool": "fake.add", "arguments": {"a": 1, "b": 2}})
        assert excinfo.value.code == TOOL_NOT_CALLABLE
        assert "tool_not_callable" in str(excinfo.value)
        assert not fixture_paths["marker"].exists(), (
            "a call refused by the profile must not spawn the upstream"
        )
        # tools_schema is visibility-gated, not callability-gated: the agent
        # can read a view-only tool's schema (this spawn is permitted).
        schema = gateway.tools_schema({"tool": "fake.add"})
        assert schema["tool"] == "fake.add"
        assert fixture_paths["marker"].exists()
        # Still not callable after the spawn.
        with pytest.raises(UpstreamError) as excinfo:
            gateway.tools_call({"tool": "fake.add", "arguments": {"a": 1, "b": 2}})
        assert excinfo.value.code == TOOL_NOT_CALLABLE
        # And the callable tool routes normally.
        result = gateway.tools_call({"tool": "fake.echo", "arguments": {"text": "hi"}})
        assert result["isError"] is False
    finally:
        gateway.shutdown()


# ---------------------------------------------------------------------------
# Fail-closed states: -32013 / -32014 for every operation.


def test_missing_profile_name_fails_closed_for_every_op(fixture_paths: dict) -> None:
    state = resolve_profile_state(fixture_paths["profile_path"], cli_name="ghost", env_name="")
    assert isinstance(state, FailClosedProfile)
    assert state.code == PROFILE_NOT_FOUND
    assert state.requested == "ghost"
    config = load_gateway_config(fixture_paths["config_path"])
    gateway = Gateway(config, AuditLog(fixture_paths["audit"]), profile=state)
    registry = build_gateway_registry(gateway)
    try:
        for meta_tool, arguments in (
            ("tools_search", {"query": "echo"}),
            ("tools_schema", {"tool": "fake.echo"}),
            ("tools_call", {"tool": "fake.echo", "arguments": {}}),
        ):
            with pytest.raises(UpstreamError) as excinfo:
                registry[meta_tool]["handler"](arguments)
            assert excinfo.value.code == PROFILE_NOT_FOUND, meta_tool
            assert "profile_not_found" in str(excinfo.value)
        assert not fixture_paths["marker"].exists(), "fail-closed never spawns"
    finally:
        gateway.shutdown()
    rows = audit_rows(fixture_paths)
    assert len(rows) == 3
    for row in rows:
        assert row["ok"] is False
        assert "profile_not_found" in row["error"]
        assert row["profile"] == "ghost", "fail-closed rows carry the REQUESTED name"
    assert all(row["tool"] != "profile_loaded" for row in rows)


def test_nothing_selected_and_no_default_fails_closed(tmp_path: Path) -> None:
    document = {"schema_version": 1, "profiles": {"dev": {"visible": ["fake.*"]}}}
    state = resolve_profile_state(write_profiles(tmp_path, document), cli_name="", env_name="")
    assert isinstance(state, FailClosedProfile)
    assert state.code == PROFILE_NOT_FOUND
    assert state.requested == ""


def test_invalid_profile_file_fails_closed_for_every_op(fixture_paths: dict, tmp_path: Path) -> None:
    bad_path = write_profiles(
        tmp_path,
        {"schema_version": 1, "profiles": {"dev": {"visible": ["github.create_*"]}}},
    )
    state = resolve_profile_state(bad_path, cli_name="dev", env_name="")
    assert isinstance(state, FailClosedProfile)
    assert state.code == PROFILE_INVALID
    config = load_gateway_config(fixture_paths["config_path"])
    gateway = Gateway(config, AuditLog(fixture_paths["audit"]), profile=state)
    try:
        for method, arguments in (
            (gateway.tools_search, {"query": "echo"}),
            (gateway.tools_schema, {"tool": "fake.echo"}),
            (gateway.tools_call, {"tool": "fake.echo", "arguments": {}}),
        ):
            with pytest.raises(UpstreamError) as excinfo:
                method(arguments)
            assert excinfo.value.code == PROFILE_INVALID
            assert "profile_invalid" in str(excinfo.value)
        assert not fixture_paths["marker"].exists()
    finally:
        gateway.shutdown()
    # A missing file is also profile_invalid, never open behavior.
    state = resolve_profile_state(tmp_path / "no-such-profiles.json", cli_name="dev", env_name="")
    assert isinstance(state, FailClosedProfile)
    assert state.code == PROFILE_INVALID


# ---------------------------------------------------------------------------
# Loading: extends resolution, cycles, depth, coverage.


def test_extends_chain_is_restriction_only(fixture_paths: dict) -> None:
    # 'narrow' hides fake.add even though its parent 'reviewer' shows it.
    gateway = make_gateway(fixture_paths, "narrow")
    try:
        assert gateway.tools_search({"query": "add integers"})["hits"] == []
        with pytest.raises(UpstreamError) as excinfo:
            gateway.tools_schema({"tool": "fake.add"})
        assert excinfo.value.code == TOOL_NOT_VISIBLE
        result = gateway.tools_call({"tool": "fake.echo", "arguments": {"text": "ok"}})
        assert result["isError"] is False
    finally:
        gateway.shutdown()
    # 'wide-child' declares 'fake.*' but can never widen beyond its ceiling.
    gateway = make_gateway(fixture_paths, "wide-child")
    try:
        for hidden in ("fake.add", "fake.secret_wipe", "other.shred"):
            with pytest.raises(UpstreamError) as excinfo:
                gateway.tools_schema({"tool": hidden})
            assert excinfo.value.code == TOOL_NOT_VISIBLE, hidden
        hits = gateway.tools_search({"query": "echo text"})["hits"]
        assert [hit["tool"] for hit in hits] == ["fake.echo"]
        assert hits[0]["callable"] is True
    finally:
        gateway.shutdown()


def test_omitted_fields_inherit_parent_sets(fixture_paths: dict) -> None:
    gateway = make_gateway(fixture_paths, "inheritor")
    try:
        assert gateway.tools_search({"query": "secret wipe"})["hits"] == []
        add_hits = gateway.tools_search({"query": "add integers"})["hits"]
        assert add_hits and add_hits[0]["callable"] is False
        result = gateway.tools_call({"tool": "fake.echo", "arguments": {"text": "x"}})
        assert result["isError"] is False
    finally:
        gateway.shutdown()


def test_empty_root_profile_denies_everything(fixture_paths: dict) -> None:
    gateway = make_gateway(fixture_paths, "empty")
    try:
        assert gateway.tools_search({"query": "echo text"})["hits"] == []
        for fq in ("fake.echo", "other.shred"):
            with pytest.raises(UpstreamError) as excinfo:
                gateway.tools_call({"tool": fq})
            assert excinfo.value.code == TOOL_NOT_VISIBLE, fq
        assert not fixture_paths["marker"].exists()
    finally:
        gateway.shutdown()


def test_cycle_self_extends_dangling_and_depth_are_load_errors(tmp_path: Path) -> None:
    base = {"visible": ["a.*"], "callable": ["a.*"]}
    cases = {
        "self-extends": {"p": {"extends": "p", **base}},
        "cycle": {"p": {"extends": "q", **base}, "q": {"extends": "p", **base}},
        "dangling": {"p": {"extends": "ghost", **base}},
        "depth": {
            f"p{i}": ({"extends": f"p{i + 1}", **base} if i < 9 else dict(base))
            for i in range(10)
        },
    }
    for label, profiles in cases.items():
        path = write_profiles(tmp_path, {"schema_version": 1, "profiles": profiles})
        with pytest.raises(ProfileLoadError):
            load_profile_document(path)
        state = resolve_profile_state(path, cli_name="p", env_name="")
        assert isinstance(state, FailClosedProfile), label
        assert state.code == PROFILE_INVALID, label


def test_uncovered_callable_and_unknown_keys_are_load_errors(tmp_path: Path) -> None:
    uncovered = {
        "schema_version": 1,
        "profiles": {"p": {"visible": ["a.read"], "callable": ["a.write"]}},
    }
    with pytest.raises(ProfileLoadError) as excinfo:
        load_profile_document(write_profiles(tmp_path, uncovered))
    assert "not covered by visible" in str(excinfo.value)
    typo = {"schema_version": 1, "profiles": {"p": {"visble": ["a.*"]}}}
    with pytest.raises(ProfileLoadError) as excinfo:
        load_profile_document(write_profiles(tmp_path, typo))
    assert "visble" in str(excinfo.value), "a typo must fail loudly, never silently deny"


# ---------------------------------------------------------------------------
# Selection precedence: --profile > env var > default_profile.


def test_selection_precedence(fixture_paths: dict, monkeypatch: pytest.MonkeyPatch) -> None:
    path = fixture_paths["profile_path"]
    cli_beats_env = resolve_profile_state(path, cli_name="narrow", env_name="reviewer")
    assert isinstance(cli_beats_env, ActiveProfile) and cli_beats_env.name == "narrow"
    env_beats_default = resolve_profile_state(path, cli_name="", env_name="reviewer")
    assert isinstance(env_beats_default, ActiveProfile) and env_beats_default.name == "reviewer"
    file_default = resolve_profile_state(path, cli_name="", env_name="")
    assert isinstance(file_default, ActiveProfile) and file_default.name == "dev"
    # env_name=None reads the real environment variable.
    monkeypatch.setenv(PROFILE_ENV_VAR, "reviewer")
    from_env = resolve_profile_state(path, cli_name="")
    assert isinstance(from_env, ActiveProfile) and from_env.name == "reviewer"
    # A selected name that does not exist NEVER falls back to default_profile.
    monkeypatch.setenv(PROFILE_ENV_VAR, "ghost")
    missing = resolve_profile_state(path, cli_name="")
    assert isinstance(missing, FailClosedProfile) and missing.code == PROFILE_NOT_FOUND


# ---------------------------------------------------------------------------
# Audit: profile stamping, profile_loaded row, redaction untouched.


def test_audit_rows_carry_profile_and_profile_loaded_sha256(fixture_paths: dict) -> None:
    gateway = make_gateway(fixture_paths, "reviewer")
    registry = build_gateway_registry(gateway)
    try:
        registry["tools_search"]["handler"]({"query": "echo text"})
        registry["tools_call"]["handler"]({"tool": "fake.echo", "arguments": {"text": "hello"}})
        with pytest.raises(UpstreamError):
            registry["tools_call"]["handler"]({"tool": "fake.add", "arguments": {}})
        with pytest.raises(UpstreamError):
            registry["tools_schema"]["handler"]({"tool": "fake.secret_wipe"})
    finally:
        gateway.shutdown()
    rows = audit_rows(fixture_paths)
    loaded = rows[0]
    assert loaded["tool"] == "profile_loaded"
    assert loaded["ok"] is True
    assert loaded["profile"] == "reviewer"
    expected_sha = hashlib.sha256(fixture_paths["profile_path"].read_bytes()).hexdigest()
    assert loaded["profile_sha256"] == expected_sha
    assert loaded["visible_rules"] == 4 and loaded["callable_rules"] == 3, (
        "rule counts are numbers only (declared rules along the extends chain)"
    )
    assert all(row["profile"] == "reviewer" for row in rows), (
        "every row carries the profile name while profiles are active"
    )
    refusals = [row for row in rows if row["ok"] is False]
    assert len(refusals) == 2
    assert any("tool_not_callable" in row["error"] for row in refusals)
    assert any("tool_not_visible" in row["error"] for row in refusals)


def test_audit_redaction_untouched_with_profiles_active(fixture_paths: dict) -> None:
    gateway = make_gateway(fixture_paths, "reviewer")
    registry = build_gateway_registry(gateway)
    try:
        registry["tools_call"]["handler"](
            {
                "tool": "fake.echo",
                "arguments": {
                    "text": "PLAINTEXT user text",
                    "api_token": "tok-PLAINTEXT-TOKEN",
                    "note": r"see C:\Users\someone\private\notes.txt",
                },
            }
        )
    finally:
        gateway.shutdown()
    audit_text = fixture_paths["audit"].read_text(encoding="utf-8")
    assert "PLAINTEXT" not in audit_text, "the existing redaction floor stays in force"
    assert "someone" not in audit_text, "local paths stay scrubbed"
    assert "[redacted]" in audit_text
    assert '"profile": "reviewer"' in audit_text


def test_unqualified_tool_stays_a_domain_error(fixture_paths: dict) -> None:
    """A malformed address is a caller mistake in every mode, not a refusal."""
    gateway = make_gateway(fixture_paths, "reviewer")
    try:
        with pytest.raises(ToolError):
            gateway.tools_call({"tool": "not-qualified"})
        with pytest.raises(ToolError):
            gateway.tools_schema({"tool": ""})
    finally:
        gateway.shutdown()
