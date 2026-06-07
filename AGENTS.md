# Unlimited Skills Agent Guidance

This is the public MIT repository for the local Unlimited Skills core.

<!-- BEGIN UNLIMITED SKILLS -->
## Unlimited Skills Library

Unlimited Skills is the external skill memory for this agent. Treat it as the first place to ask for task-specific skills, workflows, checklists, procedures, and regression recipes.

Before doing substantive work, check whether Unlimited Skills has a relevant skill. This includes writing, editing, coding, review, debugging, research, documentation, operations, planning, and design tasks. Skip this check only when a relevant skill is already active in the current context and it is clear why that skill applies.

Before saying a skill is unavailable, query the library:

```bash
unlimited-skills search "<task or skill name>" --mode hybrid --limit 8
unlimited-skills where <skill-name>
unlimited-skills view <skill-name>
```

For inventory questions, query the library before answering:

```bash
unlimited-skills list --limit 80
```

Do not rely only on `.agents/skills`, `.codex/skills`, or the visible skill list. The library may contain skills that are intentionally not loaded into context.
<!-- END UNLIMITED SKILLS -->

Review rules:

- Do not require registration for local MIT commands.
- Do not upload skill contents, prompts, source code, full paths, repo paths, customer names, env vars, tokens, secrets, or device private keys in hosted metadata calls.
- Do not claim implemented security features that are only planned.
- Current hosted archive enforcement is SHA256 verification plus safe zip extraction. Cryptographic signature verification is planned until client enforcement exists.
- Keep hosted registry backend code out of this public MIT repo.
- Public repo self-update remains unregistered because it updates the MIT public core from GitHub.
- Hosted skill updates, hosted catalog, local enhancer downloads, and team sync require registration.
