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


def cmd_mcp_gateway(args: argparse.Namespace) -> int:
    from ..mcp.audit import AuditLog, default_audit_path
    from ..mcp.gateway import load_gateway_config, run_gateway

    root = Path(args.root).expanduser()
    config = load_gateway_config(Path(args.config).expanduser())
    audit_path = Path(args.audit_log).expanduser() if args.audit_log else default_audit_path(root)
    upstream_count = len(config.get("upstreams", []))
    print(
        f"unlimited-tools MCP gateway: stdio, {upstream_count} upstream(s), lazy spawn, audit log enabled",
        file=sys.stderr,
    )
    run_gateway(config, AuditLog(audit_path))
    return 0
