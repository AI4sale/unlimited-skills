"""Unlimited Tools: zero-dependency local MCP servers over stdio.

This package implements minimal JSON-RPC 2.0 / MCP plumbing without any
external MCP SDK:

- :mod:`unlimited_skills.mcp.protocol` -- framing, lifecycle, ``StdioServer``.
- :mod:`unlimited_skills.mcp.server` -- the skills MCP server
  (``skills_search`` / ``skills_view`` / ``skills_use``).
- :mod:`unlimited_skills.mcp.gateway` -- the gateway MCP server fronting
  upstream MCP servers with 3 meta-tools
  (``tools_search`` / ``tools_schema`` / ``tools_call``).
- :mod:`unlimited_skills.mcp.audit` -- append-only redacted JSONL audit log.

Everything is stdio-only and local-only: no network listeners, no OAuth
upstreams, no resources/prompts capabilities in v1.
"""

from __future__ import annotations

__all__ = ["protocol", "server", "gateway", "audit"]
