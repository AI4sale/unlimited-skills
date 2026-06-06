# Context reduction model

Unlimited Skills is useful only when the agent keeps real skills out of its always-loaded context.

Different agent runtimes discover skills differently, so Unlimited Skills separates two operations:

| Operation | What it does | Reduces visible-context load? |
| --- | --- | --- |
| `migrate` | Copies skills into the Unlimited Skills library. | No. Source skills remain visible to the agent. |
| `install-router` / `router-only` | Installs the small router skill into the agent-visible directory. | Only if no other real skills remain visible. |
| `evacuate-visible-skills` | Copies skills into the library, moves originals to backup, and leaves only the router visible. | Yes, for agents that load all visible skills at startup. |
| `doctor` | Reports whether the agent can still see too many skills. | Diagnostic only. |
| `rollback` | Restores visible skills from a backup manifest. | Reverses context reduction. |

## Product rule

If an agent runtime loads every `SKILL.md` from a visible skill directory at startup, Unlimited Skills must physically remove real skills from that directory and leave only the router.

Otherwise it becomes one more skill on top of the existing context load.

## Safe adapter pattern

A context-reducing adapter should do the following:

1. detect agent-visible skill roots;
2. count visible `SKILL.md` before install;
3. copy real skills into `~/.unlimited-skills/library/<agent>/skills`;
4. move original visible skill directories into a timestamped backup;
5. install one agent-specific router skill;
6. generate launchers with agent-specific paths;
7. rebuild the lexical index;
8. verify and print the after-count;
9. write a rollback manifest.

The adapter must be dry-run by default and must never treat a missing source root as silent success. Missing roots should be explicit:

```text
No Hermes skills found under ~/.hermes/skills.
Nothing to evacuate.
Router can still be installed.
```

## Acceptance signal

For context reduction, the install report should show:

```text
Before visible SKILL.md count: N
After visible SKILL.md count: 1
Visible skills:
  - unlimited-skills
```

If the after-count is still large, the adapter did not reduce context.
