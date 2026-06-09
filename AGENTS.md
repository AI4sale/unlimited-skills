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

Release PR hygiene:

- When a release train reaches release readiness, for example `v0.3.1-alpha`, finish the PR cleanup before starting or requesting the next task batch.
- Confirm explicit user or release-owner approval for the cleanup turn before merging or closing PRs.
- List open PRs across every repo involved in the release train, including public core, private registry, backend, docs, and installer repos.
- Merge approved release PRs into the repository default branch, `main` or `master`, in dependency order after CI, review notes, security checks, and release evidence are verified.
- Close obsolete, duplicate, or superseded PRs with a comment that points to the merged replacement.
- Delete merged topic branches only when repository policy allows it.
- Refresh the local default branch before creating follow-up branches.
- Report merged PR numbers, closed PR numbers, remaining blockers, and the exact default branch commit used for follow-up work.
- Do not ask ChatGPT Pro or another agent for the next task batch while finished release PRs are still open unless they are explicitly blocked.
