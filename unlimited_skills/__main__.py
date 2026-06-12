"""Package entry point with a fast path for the `suggest` probe.

`python -m unlimited_skills suggest "<task>"` must answer in well under
1.5 s cold, so the dispatcher routes `suggest` to the import-cheap
:mod:`unlimited_skills.suggest` module BEFORE importing the full CLI
(which pulls hub, registration, billing, MCP, and friends). Every other
command falls through to :func:`unlimited_skills.cli.main` unchanged.

The console script `unlimited-skills` and the rendered launchers both go
through this dispatcher.
"""
from __future__ import annotations

import sys

# Global options (with a value) that may legally appear before the
# subcommand on the classic CLI. Only --root matters for `suggest`.
_GLOBAL_VALUE_FLAGS = {"--root"}


def _fast_suggest_argv(argv: list[str]) -> list[str] | None:
    """Return suggest-module argv when the command is `suggest`, else None."""
    passthrough: list[str] = []
    index = 0
    while index < len(argv):
        token = argv[index]
        if token in _GLOBAL_VALUE_FLAGS and index + 1 < len(argv):
            passthrough.extend([token, argv[index + 1]])
            index += 2
            continue
        if token.startswith("--"):
            # Unknown global flag (e.g. --version): not a plain suggest call.
            return None
        if token == "suggest":
            return argv[index + 1 :] + passthrough
        return None
    return None


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    suggest_argv = _fast_suggest_argv(argv)
    if suggest_argv is not None:
        from . import suggest

        return suggest.main(suggest_argv)
    from . import cli

    return cli.main(argv)


if __name__ == "__main__":
    raise SystemExit(main())
