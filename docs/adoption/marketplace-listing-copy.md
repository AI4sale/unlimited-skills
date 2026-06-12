# Marketplace listing copy — Claude Code plugin (v0.5 public alpha)

Draft copy for the Claude Code plugin marketplace listing. Everything below
is written to be pasted into listing fields; bracketed notes are for the
release owner, not for publication.

Ground rules baked into this copy: free public alpha, nothing for sale, no
telemetry, only measured numbers that already exist in the repo.

---

## Short description (1–2 sentences)

> Keep thousands of skills out of your context window. Unlimited Skills is a
> local, search-first skill library: one tiny router stays in context, the
> right skill is retrieved only when a task needs it.

## Long description

> Loading every skill into the model context makes agents slower, not
> smarter: the context gets noisy, unrelated instructions compete with the
> task, and tokens are spent carrying procedures that will never run.
>
> Unlimited Skills treats skills as a local library instead. A 1-second
> `suggest` probe checks each task against your indexed `SKILL.md` files
> (lexical, vector, or hybrid search — all local) and the agent loads only
> the skill it actually needs. The plugin wires this into Claude Code
> deterministically: a SessionStart hook injects the router contract into
> every session, and a UserPromptSubmit hook delivers suggestions in three
> tiers — silence when nothing clears the score floor, a one-line hint at
> medium confidence, and a compact skill card injected directly at high
> confidence. Wrong-but-confident is treated as the worst outcome: on the
> frozen 42-scenario eval set against the bundled 267-skill library, the
> measured run shows top-1 0.933, top-3 0.967, and a 0.000 false-positive
> rate.
>
> The same retrieval model extends to MCP: the Unlimited Tools gateway
> replaces every upstream tool schema in your context with 3 small
> meta-tools, fetching full schemas lazily one at a time.
>
> Everything runs on your machine. No telemetry, no auto-upload: prompts,
> skill bodies, and local paths never leave your computer, and the injected
> context itself is built to carry no local paths and never echo your
> prompt.
>
> This is a free public alpha. Nothing in this plugin or its CLI is for
> sale.

## Key features (bullets)

- **Search-first skills** — thousands of `SKILL.md` files stay on disk,
  indexed locally; only the selected skill enters the context. Lexical
  search works offline with zero extra dependencies; vector/hybrid is an
  optional extra.
- **Tiered ambient injection with a kill switch** — silence below the score
  floor, a name-only hint at medium confidence, a full skill card only at
  high confidence (calibrated threshold + margin over the runner-up). Set
  `UNLIMITED_SKILLS_NO_INJECT=1` to downgrade cards to hints. Hooks are
  fail-open: any error means less injection, never a broken session.
- **MCP gateway context savings, measured** — in the repo's lab benchmark
  (40 realistic tools), the full schema dump is 90,420 bytes versus a 1,268
  byte standing cost behind the gateway's 3 meta-tools: a 98.6% reduction.
  Get **your** numbers from your real Claude Code MCP config with
  `unlimited-skills mcp savings` — measured locally, nothing uploaded.
- **One-command golden path** — `unlimited-skills quickstart` imports the
  bundled packs when the library is empty, proves retrieval with a first
  search, and measures your MCP savings. Idempotent and local-only.
- **Privacy by construction** — the suggestion probe's output carries skill
  names, sources, and scores only: never your prompt text, never local
  filesystem paths, never skill bodies outside the one sanctioned
  high-confidence card channel. Verified per measured run, not assumed.
- **Bring your own skills** — import from local directories or GitHub repos
  (`import-dir`, `import-github`), mirror native Claude Code
  personal/project/plugin skills automatically, deduplicated by content.

## Install

The plugin needs the `unlimited-skills` CLI for retrieval. Install the CLI
first:

```bash
pip install unlimited-skills
unlimited-skills quickstart
unlimited-skills mcp install --claude-code --dry-run
unlimited-skills mcp install --claude-code
```

Then, inside Claude Code:

```text
/plugin marketplace add AI4sale/unlimited-skills
/plugin install unlimited-skills@unlimited-skills
```

Restart the session so the SessionStart hook runs. Full details:
[docs/claude-code-plugin.md](../claude-code-plugin.md).

Optional check:

```bash
unlimited-skills mcp install status
unlimited-skills mcp savings
```

## Feedback and support

This is a community-supported free alpha. Bug reports, install friction,
wrong/missing suggestions, and your measured savings numbers are all
welcome through GitHub issues:

- <https://github.com/AI4sale/unlimited-skills/issues/new/choose>
- Feedback guide: [docs/feedback.md](../feedback.md) — feedback is manual
  and voluntary; the product itself uploads nothing.

## Known limitations

Honest alpha limitations (interfaces may change before 0.6, Windows-first
testing, optional model download for vector search, MCP gateway v1
boundaries, and more) are listed in
[docs/releases/v0.5.0-alpha-known-issues.md](../releases/v0.5.0-alpha-known-issues.md).

## Nothing for sale

Unlimited Skills v0.5 is a free public alpha under the MIT license (local
core). There are no paid tiers on offer, no checkout, and no purchase path
in this listing or in the product.
