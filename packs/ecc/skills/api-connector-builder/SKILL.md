---
name: api-connector-builder
description: "Build a new API connector or provider by matching the target repo's existing integration pattern exactly. Use when adding one more integration without inventing a second architecture."
version: 1.0.0
category: ecc
tags: "[api-connector-builder, build, new, api, connector, provider, matching, target]"
status: published
confidence: 0.8
source: imported
source_pack: ecc
source_repo: "https://github.com/affaan-m/ECC"
source_path: skills\api-connector-builder\SKILL.md
source_sha256: 0def96c1d6414acdf3fa26d04fa065a105a53719660b8d9dade23ef3acf51fef
unlimited_skills_adapter: odysseus-action-schema-v1
created: "2026-06-06T06:14:53Z"
---

## When to Use

- "Build a Jira connector for this project"
- "Add a Slack provider following the existing pattern"
- "Create a new integration for this API"
- "Build a plugin that matches the repo's connector style"

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

## API Connector Builder

Use this when the job is to add a repo-native integration surface, not just a generic HTTP client.

The point is to match the host repository's pattern:

- connector layout
- config schema
- auth model
- error handling
- test style
- registration/discovery wiring

## Guardrails

- do not invent a new integration architecture when the repo already has one
- do not start from vendor docs alone; start from existing in-repo connectors first
- do not stop at transport code if the repo expects registry wiring, tests, and docs
- do not cargo-cult old connectors if the repo has a newer current pattern

## 1. Learn the house style

Inspect at least 2 existing connectors/providers and map:

- file layout
- abstraction boundaries
- config model
- retry / pagination conventions
- registry hooks
- test fixtures and naming

## 2. Narrow the target integration

Define only the surface the repo actually needs:

- auth flow
- key entities
- core read/write operations
- pagination and rate limits
- webhook or polling model

## 3. Build in repo-native layers

Typical slices:

- config/schema
- client/transport
- mapping layer
- connector/provider entrypoint
- registration
- tests

## 4. Validate against the source pattern

The new connector should look obvious in the codebase, not imported from a different ecosystem.

## Provider-style

```text
providers/
  existing_provider/
    __init__.py
    provider.py
    config.py
```

## Connector-style

```text
integrations/
  existing/
    client.py
    models.py
    connector.py
```

## TypeScript plugin-style

```text
src/integrations/
  existing/
    index.ts
    client.ts
    types.ts
    test.ts
```

## Quality Checklist

- [ ] matches an existing in-repo integration pattern
- [ ] config validation exists
- [ ] auth and error handling are explicit
- [ ] pagination/retry behavior follows repo norms
- [ ] registry/discovery wiring is complete
- [ ] tests mirror the host repo's style
- [ ] docs/examples are updated if expected by the repo

## Related Skills

- `backend-patterns`
- `mcp-server-patterns`
- `github-ops`
