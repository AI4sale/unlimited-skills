# Remote Agent Router

Agent visible context should contain a tiny router only. The router asks for relevant skills when a task starts and loads only selected skill bodies.

The router can query a configured Local Skill Hub. This keeps Hermes, OpenClaw, Codex, Claude Code, and Vellum AI from loading a large skill library into startup context.

Remote hub requests must send the configured hub client token as:

```text
Authorization: Bearer <hub_client_token>
```

or the compatibility header:

```text
X-ULS-Hub-Token: <hub_client_token>
```

The token is a local hub token, not the hosted registration token.

## Client Commands

Configure with an environment-backed token when possible:

```bash
export ULS_HUB_TOKEN="<hub_client_token>"
unlimited-skills remote configure --url http://127.0.0.1:8766 --token-env ULS_HUB_TOKEN --fallback local_allowed
```

For quick local testing, `--token <hub_client_token>` is allowed. That stores the raw token in `~/.unlimited-skills/remote.json` with private file permissions where the platform supports them. The CLI never prints the token.

## Remote-First Installer Mode

Codex, Claude Code, Hermes, and OpenClaw installers accept remote-first Local Skill Hub options:

```bash
--remote-first
--remote-hub-url http://127.0.0.1:8766
--hub-token-env ULS_HUB_TOKEN
--remote-fallback local_allowed
```

`--hub-token-env` is preferred because visible router files can reference the environment variable name without storing the raw token. `--hub-token <token>` is allowed only as a convenience path; installers write it to private `remote.json` and do not write it into visible `SKILL.md`, `AGENTS.md`, `CLAUDE.md`, or text reports.

Remote-first router instructions prefer:

```bash
unlimited-skills remote resolve "<task or skill name>" --agent <agent> --max-skills 2 --max-chars 12000
```

If the selected skill is metadata-only or requires a local install plan, the router must surface the missing capability warning instead of treating the skill as ready.

Check the configured hub:

```bash
unlimited-skills remote status
unlimited-skills remote status --json
```

Retrieve selected skills:

```bash
unlimited-skills remote search "security review" --limit 8
unlimited-skills remote resolve "security review" --agent codex --max-skills 2 --max-chars 12000
unlimited-skills remote view security-review
```

`remote resolve` sends local client capabilities so the hub can distinguish pure text skills from metadata-only local install plan skills. Capabilities include agent type, OS, architecture, Python version, Node version when cheap to detect, available tool names, and environment variable names only. Environment values are never sent.

## Fallback Order

1. Use the remote hub if configured and reachable.
2. Use local Unlimited Skills if fallback is allowed.
3. Return a clear failure if policy requires the hub.

Fallback is controlled by `remote configure --fallback local_allowed|hub_required`.

`local_allowed` prints:

```text
Remote hub unavailable; using local fallback.
```

`hub_required` fails clearly:

```text
Remote hub is required by policy but unavailable.
```

Authentication errors such as invalid or revoked hub tokens do not fall back to local search. They fail as hub errors so misconfiguration is visible.

## Context Budget

Routers should enforce:

- maximum skills per task;
- maximum skill body characters;
- confidence threshold;
- selected skill bodies only.

Suggested defaults:

- `max_skills`: 2
- `max_chars`: 12000
- `confidence_threshold`: 0.65

Hosted registry search-query forwarding is off by default. Local task/search queries should stay between the client and the configured local hub unless the user explicitly enables another policy.

For Hermes and OpenClaw, the visible startup context should still contain only the router skill. The router should call `remote search` or `remote resolve`, then load only the selected returned skill body.
