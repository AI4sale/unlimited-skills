# Claude Code Plugin

Since v0.3.12 Unlimited Skills ships as a native Claude Code plugin. The plugin is the recommended integration path for Claude Code because it is deterministic: a `SessionStart` hook injects the router contract into every session and a `UserPromptSubmit` hook surfaces a relevant skill hint per prompt, so routing does not depend on `CLAUDE.md` state or on the model noticing the router skill among other entries.

## What the plugin contains

- **Router skill** (`plugin/skills/unlimited-skills/SKILL.md`): the gateway skill built around the fast `suggest` probe — one ~1-second command before any task that matches the trigger taxonomy (coding, review, tests, debugging, git/PRs, prose, research, planning, ops), plus `view`/`search`/`list` for follow-up. Unlike the legacy installer's rendered router, the plugin router has no machine-specific launcher paths; it calls the `unlimited-skills` CLI.
- **SessionStart hook** (`plugin/hooks/session_start.py`): prints the short router contract at session start. The CLI is resolved through a fallback chain — `UNLIMITED_SKILLS_CLI` env override, then `PATH`, then the standard install venv (`~/.unlimited-skills/.venv`), then the rendered launchers under `~/.claude/skills/unlimited-skills/scripts/` — so a working install never gets an install nag just because the entry point is not on `PATH`. Only when no install is found anywhere does it print an install hint. The hook never fails the session, emits no skill bodies, prompts, paths, or private data, and its output is capped to a few lines.
- **UserPromptSubmit hook** (`plugin/hooks/user_prompt_submit.py`): runs the `suggest` probe on each user prompt with a hard ~3 s timeout and injects `additionalContext` in three tiers (F3b ambient injection — at high confidence the right skill arrives by itself instead of being hinted at):
  1. **Silence** — no suggestion clears the score floor: no output at all.
  2. **Hint** (medium confidence) — a one-line `Relevant skill available: <name> (from the <pack> pack) — view it with: unlimited-skills view <name>`. NAME only: never local filesystem paths, never the prompt text.
  3. **Skill card** (high confidence: top score >= the calibrated high threshold AND >= 1.5x the runner-up, both decided by `suggest --card`) — a compact card built from the matched skill's own SKILL.md: name + source header, the frontmatter when-to-use line, the head of the body (hard-capped at ~8,000 chars ≈ 2,000 tokens, with a truncation note when cut), and a `Full skill body: unlimited-skills view <name>` footer. The card intentionally carries that one skill's body — it still never contains local paths, the prompt text, or any other skill's content.

  Set `UNLIMITED_SKILLS_NO_INJECT=1` to switch tier 3 off (cards downgrade to the one-line hint). The hook is fail-open by design: any error, timeout, missing CLI, unreadable SKILL.md, or below-floor result degrades a tier or produces no output, always exit 0. Tier thresholds and the calibration evidence live in [adoption/skill-effectiveness-standard.md](adoption/skill-effectiveness-standard.md). This converts skill invocation from model initiative into deterministic ambient retrieval.

## Install

The plugin needs the CLI for actual retrieval. Install Unlimited Skills first (see [install.md](install.md)). Then, inside Claude Code:

```text
/plugin marketplace add AI4sale/unlimited-skills
/plugin install unlimited-skills@unlimited-skills
```

Restart the session after installing so the SessionStart hook runs.

## Plugin vs legacy installer

| Aspect | Plugin (recommended for Claude Code) | `scripts/install-claude-code.*` |
| --- | --- | --- |
| Router presence in context | Guaranteed via SessionStart hook | Global + project `CLAUDE.md` block AND registered hooks (see below) |
| Per-prompt skill hints | UserPromptSubmit hook | Same hooks registered into `~/.claude/settings.json` |
| Updates | `/plugin` marketplace updates | Re-run installer |
| Machine-specific launchers | Not needed (CLI resolved via fallback chain) | Generated launcher scripts |
| Skill migration into library | Not performed | Migrates `~/.claude/skills` and project skills |

Since the A0 invocation fixes, the legacy installer also registers the same two hooks directly in `~/.claude/settings.json` (copying the hook scripts next to the router under `~/.claude/skills/unlimited-skills/hooks/`). Pass `--no-hooks` to skip that. The registration is idempotent (re-installs replace the unlimited-skills entries, never duplicate them) and fail-soft: an unparseable `settings.json` is left untouched and reported in the install messages. Both install paths therefore converge on deterministic injection; if both are active the duplicate context is equivalent and harmless, but you can remove one source.

Note for library users: native sync (v0.3.10+) discovers skills bundled with installed Claude Code plugins. The Unlimited Skills plugin itself exposes only the router skill, which native sync deliberately excludes, so installing this plugin does not re-import anything into the library.

## Privacy

The hooks and router are local-only. The prompt text is passed only to the local CLI for lexical scoring; nothing is uploaded and the plugin makes no network calls. The injected context never echoes the prompt and never carries local filesystem paths; the tier-3 skill card is the one sanctioned channel that carries a skill body (the matched skill's own SKILL.md head — disable with `UNLIMITED_SKILLS_NO_INJECT=1`). Hosted features remain opt-in through registration as documented in `SECURITY.md`.
