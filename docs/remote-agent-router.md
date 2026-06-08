# Remote Agent Router

Agent visible context should contain a tiny router only. The router asks for relevant skills when a task starts and loads only selected skill bodies.

The router can query a configured Local Skill Hub. This keeps Hermes, OpenClaw, Codex, Claude Code, and Vellum AI from loading a large skill library into startup context.

## Fallback Order

1. Use the remote hub if configured and reachable.
2. Use local Unlimited Skills if fallback is allowed.
3. Return a clear failure if policy requires the hub.

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
