# Changelog

## Unreleased

### Added

- Local-only `unlimited-skills doctor` command with JSON output and agent-specific checks for Codex, Claude Code, Hermes, and OpenClaw.
- Product editions, public core boundary, support matrix, release process, and known limitations docs for public alpha review.

### Changed

- Hardened public alpha documentation for the v0.1.2-alpha release boundary.
- Aligned `SECURITY.md` supported-version wording with v0.1.2-alpha.
- Clarified that hosted catalog/update access is registration-gated early access and already populated without publishing private registered skill bodies in the MIT repo.
- Clarified that hosted collection archives are SHA256-verified today; cryptographic signature verification is planned, not currently enforced.

## v0.1.2-alpha

### Added

- Full Claude Code installer for personal skills, project skills, router launchers, `CLAUDE.md` patching, bundled/adapt-installed modes, and optional vector reindexing.
- Claude Code router skill with shell and PowerShell launcher placeholders.
- Claude Code router launchers now remember the installed project root so later project `.claude/skills` additions are mirrored on the next router CLI call.

### Changed

- Raised package version to `0.1.2`.
- README now documents Claude Code as a full installer target instead of migration-only.

## v0.1.0-alpha

Developer preview for a local-first skill router and context reducer.

### Added

- Local recursive `SKILL.md` discovery, lexical index, Chroma vector index, hybrid search, `view`, `where`, `list`, and `use`.
- Codex router skill and installer with managed `AGENTS.md` patch.
- OpenClaw installer for workspace, plugin, and built-in skill roots.
- Hermes installer with native skill mirroring, context-reduction mode, and rollback manifest.
- Migration scripts for Codex, Claude Code, OpenClaw, Hermes, and Vellum AI.
- Native skill sync for Codex, Claude Code, Hermes, and OpenClaw roots before common retrieval commands.
- Registered hosted update client with SHA256 archive verification and safe zip extraction.
- Registered local enhancement-script download with checksum verification.
- Team sync MVP: create, join request, pending list, master approval, temporary auto-approval, and sync.
- Public repo self-update from GitHub releases or tags.

### Known Limitations

- Hosted registry access is early-access and requires registration.
- Enterprise Skill Lock is planned, not implemented in v0.1.0-alpha.
- Hosted archive signature metadata exists, but the current client enforces SHA256 verification only. Cryptographic signature verification is planned.
- Install from a GitHub clone for now. PyPI packaging should wait until repo assets such as scripts, router skills, docs, and packs are included and tested in wheels.
- OpenClaw installer modifies the selected workspace and patches `AGENTS.md` unless `--no-agents-patch` is passed.
- Warm daemon mode is experimental and not yet the default retrieval path.

### Suggested Smoke Tests

- Windows PowerShell: `install-codex.ps1`, `install-hermes.ps1 -Mode evacuate-visible-skills` dry-run.
- Linux/macOS: `pip install -e ".[all]"`, `reindex`, `search`, `view`, `serve`.
- Hermes sandbox: fake `.hermes/skills`, apply context reduction, verify only router remains visible, then rollback.
- OpenClaw sandbox: fake workspace, run installer, verify `AGENTS.md` patch and search.
- Unregistered instance: verify local `search` works and hosted `updates check` fails with registration-required wording.
