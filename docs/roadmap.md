# Roadmap

## Implemented

- Recursive `SKILL.md` discovery.
- Lexical index and search.
- Chroma vector index.
- Hybrid lexical + vector retrieval.
- Codex router skill.
- Usage and feedback logging.
- Basic skill drafting command.
- Safe dry-run migration scripts.

## In development

### Persistent warm daemon

Goal: make semantic retrieval fast enough for large libraries.

Planned work:

- keep the embedding model loaded;
- keep the Chroma client warm;
- expose local HTTP endpoints for agent tools;
- add a small health and metrics surface;
- add daemon install scripts for Windows and Unix.

### Learning loop

Goal: make the library improve from actual agent work.

Planned work:

- aggregate accepted and rejected matches;
- detect repeated false positives;
- suggest better skill descriptions;
- propose new query expansions;
- draft new skills from repeated successful workflows;
- add review gates before modifying real `SKILL.md` files.

### Multi-agent adapters

Goal: support Codex, Claude Code, OpenClaw, Hermes, Vellum AI, and other harnesses without changing the library format.

Planned work:

- stronger path detection;
- per-agent router templates;
- config merge helpers;
- rollback manifests;
- import/export commands.
