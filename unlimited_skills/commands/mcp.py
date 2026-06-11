"""Local MCP server commands: skills server and Unlimited Tools gateway."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


def cmd_mcp_serve(args: argparse.Namespace) -> int:
    from .. import cli
    from ..mcp.server import run_skills_server

    root = Path(args.root).expanduser()
    cli.enforce_local_root(root, action="mcp serve library root")
    print(f"unlimited-skills MCP skills server: stdio, library root {root}", file=sys.stderr)
    run_skills_server(root)
    return 0


def cmd_mcp_audit_report(args: argparse.Namespace) -> int:
    import json

    from ..mcp import audit_inspector
    from ..mcp.audit import default_audit_path

    root = Path(args.root).expanduser()
    audit_path = Path(args.audit_log).expanduser() if args.audit_log else default_audit_path(root)
    try:
        report = audit_inspector.build_report(audit_path)
    except FileNotFoundError:
        print(
            f"Audit log not found: {audit_path} (no active file, no rotated generations). "
            "Run the gateway first, or pass --audit-log.",
            file=sys.stderr,
        )
        return 1
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print(audit_inspector.render_text(report, section=args.section))
    return 0


def cmd_mcp_gateway(args: argparse.Namespace) -> int:
    from ..mcp.audit import AuditLog, default_audit_path
    from ..mcp.gateway import GatewayConfigError, load_gateway_config, run_gateway
    from ..mcp.index_cache import CACHE_FILE_NAME, IndexCache, default_index_cache_path
    from ..mcp.profiles import FailClosedProfile, resolve_profile_state

    root = Path(args.root).expanduser()
    config = load_gateway_config(Path(args.config).expanduser())
    audit_path = Path(args.audit_log).expanduser() if args.audit_log else default_audit_path(root)
    profiles_path = getattr(args, "profiles", "") or ""
    profile_name = getattr(args, "profile", "") or ""
    profile = None
    if profiles_path:
        # Loaded exactly once, here at startup: no hot reload by design
        # (docs/mcp-permissioned-tool-profiles.md "Audit requirements").
        profile = resolve_profile_state(Path(profiles_path).expanduser(), cli_name=profile_name)
        if isinstance(profile, FailClosedProfile):
            # Fail-closed refuse-all: the gateway still starts and serves the
            # meta-tools (hosts often swallow startup stderr), refusing every
            # call -- but an interactive start also reports the condition.
            print(f"GatewayConfigError: {profile.message}", file=sys.stderr)
            profile_note = "tool profile FAIL-CLOSED (every call refused)"
        else:
            profile_note = f"tool profile '{profile.name}' enforced"
    elif profile_name:
        raise GatewayConfigError(
            "--profile requires --profiles (the tool-profile file path); "
            "see docs/mcp-permissioned-tool-profiles.md."
        )
    else:
        profile_note = "no tool profiles (open mode)"
    # Warm tool-index cache: strictly opt-in (docs/mcp-performance.md
    # candidate 1). args.index_cache is None when the flag is absent --
    # default OFF, behavior byte-for-byte unchanged.
    index_cache = None
    cache_note = ""
    index_cache_arg = getattr(args, "index_cache", None)
    if index_cache_arg is not None:
        if str(index_cache_arg).strip():
            cache_path = Path(index_cache_arg).expanduser() / CACHE_FILE_NAME
        else:
            cache_path = default_index_cache_path(root)
        index_cache = IndexCache(cache_path)
        index_cache.load()
        cache_note = ", index cache enabled"
    upstream_count = len(config.get("upstreams", []))
    print(
        f"unlimited-tools MCP gateway: stdio, {upstream_count} upstream(s), lazy spawn, "
        f"audit log enabled, {profile_note}{cache_note}",
        file=sys.stderr,
    )
    run_gateway(config, AuditLog(audit_path), profile=profile, index_cache=index_cache)
    return 0
