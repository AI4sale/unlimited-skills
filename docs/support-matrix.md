# Support Matrix

`v0.2.1-alpha` is a developer preview. Install from a GitHub clone, not PyPI, because repo assets are required.

| Agent | Installer | Router | Patch | Native sync | Notes |
| --- | --- | --- | --- | --- | --- |
| Codex | Yes | Yes | `AGENTS.md` patch yes | Yes | Default installer patches `~/.codex/AGENTS.md` and stores the library under `~/.codex/.unlimited-skills`. Project `AGENTS.md` patching is explicit opt-in. |
| Claude Code | Yes | Yes | `CLAUDE.md` patch yes | Yes | Supports personal skills and project `.claude/skills`. |
| Hermes | Yes | Yes | Router-only context reduction yes | Yes | Use `evacuate-visible-skills` when Hermes loads visible skills into startup context; rollback is supported. |
| OpenClaw | Yes | Yes | `AGENTS.md` patch yes | Yes | Workspace/plugin/built-in installer supported. |
| Vellum AI | Migration script | Not full installer yet | Not yet | Migration-only | Full installer is not implemented in v0.2.1-alpha. |

## Operating Systems

- macOS/Linux bash where `.sh` scripts exist.
- Windows PowerShell where `.ps1` scripts exist.
- WSL can use the Linux/macOS bash paths.

## Distribution

The v0.2.x alpha distribution path is:

```bash
git clone https://github.com/AI4sale/unlimited-skills.git
cd unlimited-skills
python -m pip install -e ".[all]"
```

PyPI is not the supported v0.2.x distribution path yet.
