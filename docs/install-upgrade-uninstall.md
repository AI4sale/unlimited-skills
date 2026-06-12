# Install, Upgrade, And Uninstall

Status: `v0.3.0-alpha`.

Unlimited Skills is still distributed from a GitHub clone for this alpha. The repo contains required router skills, shell/PowerShell installers, migration scripts, docs, schemas, and bundled assets that must be present beside the Python package.

## Install From GitHub Clone

```bash
git clone https://github.com/AI4sale/unlimited-skills.git
cd unlimited-skills
python -m pip install -e ".[all]"
unlimited-skills --version
```

Minimal lexical-only install:

```bash
python -m pip install -e .
```

## Agent Installers

Codex:

```bash
./scripts/install-codex.sh
```

Claude Code:

```bash
./scripts/install-claude-code.sh
```

Hermes:

```bash
./scripts/install-hermes.sh --mode evacuate-visible-skills --apply
```

OpenClaw:

```bash
./scripts/install-openclaw.sh
```

PowerShell variants are available with the same names and `.ps1` extension.

Regenerating the router contract: the installers are idempotent for guidance files — re-running them replaces everything between the `<!-- BEGIN UNLIMITED SKILLS -->` / `<!-- END UNLIMITED SKILLS -->` markers in `CLAUDE.md` / `AGENTS.md` with the current router block (the `suggest`-first contract), without touching surrounding content. The Claude Code installer also registers the SessionStart and UserPromptSubmit hooks in `~/.claude/settings.json` (pass `--no-hooks` to skip; the merge is idempotent and never duplicates entries).

Installer hardening rules:

- default installers patch agent guidance files unless the documented opt-out flag is passed;
- installers create an isolated venv under the selected Unlimited Skills install root;
- installers install the router skill plus a private launcher;
- remote-first mode must use `--hub-token-env` where possible;
- raw hub tokens must not be written into visible router instructions;
- native skill migration/sync must not delete pre-existing local library files.

## Upgrade

```bash
git fetch --tags origin
git checkout <target-tag-or-branch>
python -m pip install -e ".[all]"
unlimited-skills reindex
unlimited-skills doctor --json
```

For v0.3.0-alpha release candidates, also run:

```bash
python scripts/verify-v0.3.0-alpha-package-assets.py
python scripts/run-v0.3.0-alpha-packaging-smoke.py
```

## Uninstall

Uninstall the editable Python package from the venv or environment where it was installed:

```bash
python -m pip uninstall unlimited-skills
```

Then remove only the install roots that belong to the agent you intentionally installed:

- Codex default install root: `~/.codex/.unlimited-skills`
- Codex visible router skill: `~/.codex/skills/unlimited-skills`
- Claude Code visible router skill: `~/.claude/skills/unlimited-skills`
- Shared default library: `~/.unlimited-skills/library`

Do not delete arbitrary `local/` skill-library folders during uninstall. If you need to preserve local skills, copy or archive the relevant `local/` directory first.
