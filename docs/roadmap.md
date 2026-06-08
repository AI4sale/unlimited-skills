# Roadmap

## Implemented

- Recursive `SKILL.md` discovery.
- Lexical index and search.
- Chroma vector index.
- Hybrid lexical + vector retrieval.
- Codex router skill.
- Agent-driven one-skill adaptation workflow.
- Bundled Superpowers pack adapted into action-memory schema.
- Usage and feedback logging.
- Basic skill drafting command.
- Safe dry-run migration scripts.
- Windows, macOS, and Linux installer/migration scripts.
- Codex installer with router and managed `AGENTS.md` patch.
- OpenClaw installer for workspace/plugin/built-in skill roots.
- Hermes context-reduction installer with rollback manifest.
- Native skill sync for Codex, Claude Code, Hermes, and OpenClaw roots.
- Registered hosted update client with SHA256-verified collection archives.
- Registered team create/join/pending/approve/sync MVP.
- Public repo self-update from GitHub releases or tags.

## In development

### Persistent warm daemon

Goal: make semantic retrieval fast enough for large libraries.

Planned work:

- keep the embedding model loaded;
- keep the embedding model warm;
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

Implemented in v0.1 alpha:

- Codex router installer and migration scripts.
- OpenClaw full installer and migration script.
- Hermes router installer, context-reduction mode, and rollback.
- Claude Code and Vellum AI migration scripts.
- Native skill root mirroring before search/list/view/index commands.

Planned work:

- stronger path detection;
- additional per-agent router templates;
- config merge helpers;
- broader rollback coverage outside Hermes;
- import/export commands;
- smoke-tested packaging for wheel/PyPI distribution.

### Hosted registry hardening

Goal: keep the public MIT core usable offline while hosted services mature behind registration.

Implemented in v0.1 alpha:

- registration state;
- hosted catalog/update client;
- SHA256 archive verification and safe zip extraction;
- local enhancement script download with checksum verification;
- team sync MVP with master approval.

Planned work:

- wider early-access onboarding;
- cryptographic signature verification in the client;
- private encrypted team-pack publishing;
- Enterprise Skill Lock policy enforcement;
- hosted audit and dashboard surfaces.
