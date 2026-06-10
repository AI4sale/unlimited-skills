# Organization and Team Status

Registered installations can inspect organization and team governance state without loading private skill bodies.

## Commands

```bash
unlimited-skills org status
unlimited-skills org status --json
unlimited-skills org status --refresh --json
unlimited-skills team status --refresh
```

`org status` is local-first. Without `--refresh`, it reads cached organization status from `UNLIMITED_SKILLS_HOME/org-status.json`, local registration state, and local `team.json`. It does not contact the hosted registry.

`org status --refresh` requires registration. It calls the hosted `/v1/org/status` endpoint with bearer token plus signed device proof, then writes a redacted cache for future offline diagnostics.

`team status --refresh` keeps the existing team endpoint behavior and requires registration for hosted refresh.

## Privacy Boundary

Organization status must not include:

- tokens;
- device private keys;
- proof headers;
- private skill names;
- private skill bodies;
- private pack names by default;
- archive or download URLs;
- local filesystem paths.

The status cache is a diagnostic artifact, not an install plan. Private pack downloads still require explicit private-pack commands and registry-side entitlement checks.
