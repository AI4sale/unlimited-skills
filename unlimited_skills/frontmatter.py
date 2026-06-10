"""Shared SKILL.md frontmatter parsing.

A single source of truth for reading the YAML frontmatter block at the top of a
SKILL.md file. Uses PyYAML when available (correctly handling multi-line scalars,
lists, nested maps, and colons inside values) and falls back to a dependency-free
line parser so the core stays installable with only `cryptography`.

Two entry points:

- `load_frontmatter(text)` -> `(dict[str, Any], body)`: rich values (lists/maps
  preserved). Use when you need structured fields.
- `split_frontmatter(text)` -> `(dict[str, str], body)`: backward-compatible flat
  view where every value is a string. Scalars are stringified, lists are joined
  with ", ", and nested maps are dropped (matching the historical line parser).
"""
from __future__ import annotations

from typing import Any

try:  # PyYAML is an optional dependency; the fallback keeps the core zero-extra-dep.
    import yaml  # type: ignore
except Exception:  # pragma: no cover - exercised only when PyYAML is absent
    yaml = None


def _frontmatter_block(text: str) -> tuple[str | None, str]:
    """Return (raw_yaml_block, body). raw_yaml_block is None when there is no frontmatter."""
    text = text.lstrip("﻿")
    if not text.startswith("---"):
        return None, text
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return None, text
    end = None
    for idx in range(1, len(lines)):
        if lines[idx].strip() == "---":
            end = idx
            break
    if end is None:
        return None, text
    block = "\n".join(lines[1:end])
    body = "\n".join(lines[end + 1 :]).lstrip("\n")
    return block, body


def _parse_block_lines(block: str) -> dict[str, str]:
    """Dependency-free fallback parser (legacy behavior, value at first colon)."""
    meta: dict[str, str] = {}
    for line in block.splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key:
            meta[key] = value
    return meta


def load_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    """Parse frontmatter into rich values. Lists and nested maps are preserved."""
    block, body = _frontmatter_block(text)
    if block is None:
        return {}, body
    if yaml is not None:
        try:
            parsed = yaml.safe_load(block)
        except Exception:
            parsed = None
        if isinstance(parsed, dict):
            return {str(k): v for k, v in parsed.items()}, body
        if parsed is None:
            return {}, body
        # Non-mapping YAML (e.g. a bare list) is not valid frontmatter; fall back.
    return dict(_parse_block_lines(block)), body


def _flatten_value(value: Any) -> str | None:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, (list, tuple)):
        parts = [_flatten_value(item) for item in value]
        return ", ".join(part for part in parts if part)
    # Nested maps have no flat representation; historical parsers dropped them.
    return None


def split_frontmatter(text: str, *, lower_keys: bool = False) -> tuple[dict[str, str], str]:
    """Backward-compatible flat string view of the frontmatter.

    Set ``lower_keys`` to lowercase every key (the historical behavior of the
    cli and community parsers).
    """
    meta, body = load_frontmatter(text)
    flat: dict[str, str] = {}
    for key, value in meta.items():
        flattened = _flatten_value(value)
        if flattened is not None:
            flat[key.lower() if lower_keys else key] = flattened
    return flat, body
