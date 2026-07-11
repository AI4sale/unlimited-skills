# Support Matrix

`v0.6.7` is a pre-1.0 release. Install the user package from PyPI; use a
GitHub clone when you need repository-only installer scripts or contributor
assets.

| Agent | Installer | Router | Patch | Native sync | Notes |
| --- | --- | --- | --- | --- | --- |
| Codex | Yes | Yes | `AGENTS.md` patch yes | Yes | Default installer patches `~/.codex/AGENTS.md` and stores the library under `~/.codex/.unlimited-skills`. Project `AGENTS.md` patching is explicit opt-in. |
| Claude Code | Yes | Yes | `CLAUDE.md` patch yes | Yes | Supports personal skills and project `.claude/skills`. |
| Hermes | Yes | Yes | Router-only context reduction yes | Yes | Use `evacuate-visible-skills` when Hermes loads visible skills into startup context; rollback is supported. |
| OpenClaw | Yes | Yes | `AGENTS.md` patch yes | Yes | Workspace/plugin/built-in installer supported. |
| Vellum AI | Migration script | Not full installer yet | Not yet | Migration-only | Full installer is not implemented in v0.3.0-alpha. |

## Operating Systems

- macOS/Linux bash where `.sh` scripts exist.
- Windows PowerShell where `.ps1` scripts exist.
- WSL can use the Linux/macOS bash paths.

## Distribution

The supported user distribution path is:

```bash
python -m pip install --upgrade "unlimited-skills>=0.6.7"
```

Use `unlimited-skills[all]>=0.6.7` for multilingual vector retrieval and the
warm daemon. Agent installer scripts remain available from the GitHub checkout.
