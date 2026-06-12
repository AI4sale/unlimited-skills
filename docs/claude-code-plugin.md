# Claude Code Plugin

Since v0.3.12 Unlimited Skills ships as a native Claude Code plugin. The plugin is the recommended integration path for Claude Code because it is deterministic: a `SessionStart` hook injects the router contract into every session, so routing does not depend on `CLAUDE.md` state or on the model noticing the router skill among other entries.

## What the plugin contains

- **Router skill** (`plugin/skills/unlimited-skills/SKILL.md`): the gateway skill that tells Claude Code to query the library before substantive work and before answering skill-inventory questions. Unlike the pip installer's rendered router, the plugin router has no machine-specific launcher paths; it calls the `unlimited-skills` CLI from `PATH`.
- **SessionStart hook** (`plugin/hooks/session_start.py`): prints a short router contract at session start. If the CLI is missing from `PATH`, it prints an install hint instead. The hook never fails the session, emits no skill bodies, prompts, paths, or private data, and its output is capped to a few lines.

## Install

The plugin needs the CLI for actual retrieval. The package is not published on PyPI yet, so install it straight from GitHub:

<!-- A3-PYPI-FLIP: switch this back to `pip install unlimited-skills` when the v0.5 PyPI publication gate (A3) lands. -->

```bash
pip install "git+https://github.com/AI4sale/unlimited-skills.git"
unlimited-skills setup --local-only
```

This is the light lexical-only core. For vector/hybrid search, clone the repo and install `python -m pip install -e ".[all]"` instead (see `docs/install.md`).

Then, inside Claude Code:

```text
/plugin marketplace add AI4sale/unlimited-skills
/plugin install unlimited-skills@unlimited-skills
```

Restart the session after installing so the SessionStart hook runs.

## Plugin vs pip installer

| Aspect | Plugin (recommended for Claude Code) | `scripts/install-claude-code.*` |
| --- | --- | --- |
| Router presence in context | Guaranteed via SessionStart hook | Via global + project `CLAUDE.md` block (v0.3.11+) |
| Updates | `/plugin` marketplace updates | Re-run installer |
| Machine-specific launchers | Not needed (CLI from PATH) | Generated launcher scripts |
| Skill migration into library | Not performed | Migrates `~/.claude/skills` and project skills |

The two paths are compatible: the plugin only adds the router contract and the router skill. If both are installed, instructions are equivalent and idempotent in effect; remove the legacy router from `~/.claude/skills/unlimited-skills` if you want a single source.

Note for library users: native sync (v0.3.10+) discovers skills bundled with installed Claude Code plugins. The Unlimited Skills plugin itself exposes only the router skill, which native sync deliberately excludes, so installing this plugin does not re-import anything into the library.

## Privacy

The hook and router are local-only. Nothing is uploaded; the plugin makes no network calls. Hosted features remain opt-in through registration as documented in `SECURITY.md`.
