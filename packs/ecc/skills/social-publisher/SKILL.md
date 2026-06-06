---
name: social-publisher
description: "Agent-driven scheduling and publishing of social media posts across 13 platforms via SocialClaw. Use when the user wants to publish to X, LinkedIn, Instagram, Facebook Pages, TikTok, Discord, Telegram, YouTube, Reddit, WordPress, or Pinterest — or when managing campaigns, uploading media, or monitoring post delivery status."
version: 1.0.0
category: ecc
tags: "[social-publisher, agent-driven, scheduling, publishing, social, media, posts, across]"
status: published
confidence: 0.8
source: imported
source_pack: ecc
source_repo: "https://github.com/affaan-m/ECC"
source_path: skills\social-publisher\SKILL.md
source_sha256: 983ac70f282d9d0eb16bcde793a3b634cb3cfaec4f43597373228557cd1d99c9
unlimited_skills_adapter: odysseus-action-schema-v1
created: "2026-06-06T06:14:59Z"
---

## When to Use

- publish content to X, LinkedIn, Instagram, TikTok, or other platforms
- schedule a post campaign across multiple platforms at once
- upload media for use in social posts
- validate a post schedule before going live
- monitor publishing run status and delivery analytics

## When Not to Use

Not specified by the source skill.

## Required Context

Not specified by the source skill.

## Procedure

1. Read the preserved source skill body below.
2. Apply only the parts relevant to the current task.
3. Verify the result using the regression tests or project-specific checks.

## Tools

Not specified by the source skill.

## Expected Output

Not specified by the source skill.

## Known Traps

Not specified by the source skill.

## Examples of Successful Execution

Not specified by the source skill.

## Regression Tests

Not specified by the source skill.

## Original Skill Body

## Social Publisher (SocialClaw)

Connects Claude Code to [SocialClaw](https://getsocialclaw.com) for agent-driven social media publishing across 13 platforms through a single workspace API key.

## Setup

```bash

## Required: workspace API key from https://getsocialclaw.com/dashboard

export SC_API_KEY="<workspace-key>"

## Verify access

curl -sS -H "Authorization: Bearer $SC_API_KEY" https://getsocialclaw.com/v1/keys/validate

## Install CLI (optional but recommended)

npm install -g socialclaw@0.1.12
socialclaw login --api-key <workspace-key>
```

## 1. List connected accounts

```bash
socialclaw accounts list --json
```

If not connected:
```bash
socialclaw accounts connect --provider x --open
socialclaw accounts connect --provider linkedin --open
```

## 2. Upload media (optional)

```bash
socialclaw assets upload --file ./image.png --json

## → { "asset_id": "..." }

```

## 3. Build schedule.json

```json
{
  "posts": [
    {
      "provider": "x",
      "account_id": "<account-id>",
      "text": "Post text here",
      "scheduled_at": "2026-06-01T10:00:00Z"
    }
  ]
}
```

## 4. Validate before publishing

```bash
socialclaw validate -f schedule.json --json
```

## 5. Publish

```bash
socialclaw apply -f schedule.json --json

## → { "run_id": "..." }

```

## 6. Monitor

```bash
socialclaw status --run-id <run-id> --json
socialclaw posts list --json
```

## Supported Providers

| Provider | Key |
|----------|-----|
| X (Twitter) | `x` |
| LinkedIn profile | `linkedin` |
| LinkedIn page | `linkedin_page` |
| Instagram Business | `instagram_business` |
| Instagram standalone | `instagram` |
| Facebook Page | `facebook` |
| TikTok | `tiktok` |
| YouTube | `youtube` |
| Reddit | `reddit` |
| WordPress | `wordpress` |
| Discord | `discord` |
| Telegram | `telegram` |
| Pinterest | `pinterest` |

## Security

- Outbound requests go to `getsocialclaw.com` only
- Provider OAuth is in the SocialClaw dashboard — no per-provider secrets exposed to the agent
- `SC_API_KEY` is a workspace-scoped key

## Related Skills

- `x-api` — direct X/Twitter API operations
- `social-graph-ranker` — network analysis for outreach targeting

## Source

- npm: `npm install -g socialclaw@0.1.12`
- Dashboard: [SocialClaw dashboard](https://getsocialclaw.com/dashboard)
