# Agent Skill Adaptation

Unlimited Skills uses an agent-driven adapter. The adapter is not a separate service and it is not a keyword expander.

The installing agent, such as Codex or Claude Code, reads one source `SKILL.md`, rewrites it into the action-memory schema, and then lets the CLI validate and apply the result.

## Why

Skill memory is not ordinary RAG. A RAG document can answer a question. A skill must teach an agent how to act.

Every adapted skill must include:

- `When to Use`
- `When Not to Use`
- `Required Context`
- `Procedure`
- `Tools`
- `Expected Output`
- `Known Traps`
- `Examples of Successful Execution`
- `Regression Tests`

## One-Skill Flow

Prepare an adaptation task:

```bash
unlimited-skills --root ~/.unlimited-skills/library adapt-next --collection codex > /tmp/adapt-task.json
```

The command prints:

- source skill path;
- source hash;
- original skill body;
- required JSON schema;
- rules for the current agent.

The current agent then writes one JSON file matching the schema:

```json
{
  "source_path": "/path/to/SKILL.md",
  "name": "systematic-debugging",
  "description": "Debug technical failures by finding root cause before fixing.",
  "category": "debugging",
  "tags": ["debugging", "root-cause", "tests"],
  "when_to_use": "...",
  "when_not_to_use": "...",
  "required_context": "...",
  "procedure": ["..."],
  "tools": ["..."],
  "expected_output": "...",
  "known_traps": ["..."],
  "examples_of_successful_execution": ["..."],
  "regression_tests": ["..."]
}
```

Apply it:

```bash
unlimited-skills --root ~/.unlimited-skills/library apply-adaptation /tmp/adapted-skill.json
```

Repeat one skill at a time.

## Rules For The Agent

The agent should:

1. Read exactly one source skill.
2. Preserve provenance: source repository, source pack, source path, and source hash.
3. Keep `description` short. It is an index summary, not a retrieval keyword dump.
4. Put routing logic in `When to Use` and `When Not to Use`.
5. Put operational behavior in `Procedure`.
6. Add `Required Context` so future agents know what to inspect before acting.
7. List actual tools/capabilities, or say `Not specified by the source skill.`
8. Write `Known Traps` as failure modes and how to avoid them.
9. Write regression tests as observable checks an agent can run or inspect.
10. Avoid inventing unsupported facts. If the source lacks a field, write `Not specified by the source skill.`

## Repeatability

The CLI stores:

- `source_sha256`
- `unlimited_skills_adapter`
- `unlimited_skills_agent_adapter`

This makes it possible to skip already adapted skills and process a local library incrementally.

## Installation Modes

Mode 1, default:

- install the router skill;
- migrate already installed local skills;
- index them;
- do not adapt them.

Mode 2, bundled:

- install the router skill;
- install already adapted bundled packs from this repo;
- add local installed skills only when they do not duplicate an existing skill name;
- do not adapt local skills because that is token-expensive agent work.

Mode 3, adapt installed:

- install the router skill;
- migrate installed local skills;
- structurally normalize and index them;
- then the current agent can run the one-skill adaptation flow above for smart action-memory conversion.
