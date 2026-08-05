# Support Matrix

`v0.6.9` is a pre-1.0 release. Install the user package from PyPI; use a
GitHub clone when you need repository-only installer scripts or contributor
assets.

| Agent | Installer | Router | Native sync | Enterprise Fleet adapter | Notes |
| --- | --- | --- | --- | --- | --- |
| Codex | Yes | Yes | Yes | Implemented, production-pilot verified | Default local installer patches `~/.codex/AGENTS.md`. Fleet instead uses an isolated `CODEX_HOME`, workspace `.agents/skills`, and trusted `SessionStart` evidence. |
| Claude Code | Yes | Yes | Yes | Implemented, pilot paused | Fleet uses an isolated `CLAUDE_CONFIG_DIR` and `SessionStart` evidence. Claude agents are intentionally outside the current AI4SALE rollout. |
| Hermes | Yes | Yes | Yes | Implemented, production-pilot verified | Router context reduction, managed Fleet activation, runtime attestation, and installer rollback are supported. |
| OpenClaw | Yes | Yes | Yes | Implemented, production-pilot verified | Fleet binds one configured `agentId` and workspace, with `agent:bootstrap` evidence. |
| Vellum AI | Migration script | Not full installer yet | Migration-only | Not implemented | Full installer and Fleet adapter are not implemented. |

## Operating Systems

- macOS/Linux bash where `.sh` scripts exist.
- Windows PowerShell where `.ps1` scripts exist.
- WSL can use the Linux/macOS bash paths.

## Distribution

The supported user distribution path is:

```bash
python -m pip install --upgrade "unlimited-skills>=0.6.9"
```

Use `unlimited-skills[all]>=0.6.9` for multilingual vector retrieval and the
warm daemon. Agent installer scripts remain available from the GitHub checkout.
