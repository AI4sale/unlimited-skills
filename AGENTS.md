# Unlimited Skills Agent Guidance

This is the public MIT repository for the local Unlimited Skills core.

<!-- BEGIN UNLIMITED SKILLS -->
## Unlimited Skills Library

Unlimited Skills is the external skill memory for this agent. Treat `suggest` as the primary entry point for task-specific skills, workflows, checklists, procedures, and regression recipes.

Before every substantive work phase, run:

```text
unlimited-skills suggest "<3-8 keyword phase summary>" --json --card --limit 1
```

A substantive phase boundary is a change in domain or deliverable kind, such as planning -> implementation, backend/API -> frontend/UI, implementation -> testing, testing -> debugging, implementation -> security review, code -> docs, or docs -> release/git workflow. A `suggest` result is fresh only for the current phase. A no-hit result also applies only to the current phase.

Anti-spam rule: do not re-query inside the same phase for trivially similar wording. Bound lookups to at most one `suggest` probe per phase unless the user explicitly asks for a different skill search.

Interpret injected hints as tiers:

- Tier 1: silence means no confident match for this phase.
- Tier 2: a skill name hint means inspect that skill by name if it looks relevant.
- Tier 3: a compact card means a high-confidence match was found; use only the cited skill instructions needed for this phase.

`UNLIMITED_SKILLS_NO_INJECT=1` disables card injection and downgrades hook behavior to the quieter hint path.

Search, `view`, and `where` are secondary tools. Use them when a suggested skill looks relevant, when the user names a skill, or when answering inventory questions.

<!-- BEGIN ROUTER INVENTORY SNAPSHOT -->
- Generated routable skills: `268` (basis: repo SKILL.md inventory; examples excluded; deduped by skill name).
- Drift tolerance: `0`; regenerate with `python scripts/generate-router-inventory.py --write`.
- Collections: `ecc` 253, `local` 1, `superpowers` 14.

| Domain | Routable skills | Availability |
| --- | ---: | --- |
| planning/architecture | 62 | broad |
| code-implementation | 77 | broad |
| code-review | 12 | present |
| testing/QA | 18 | present |
| debugging | 4 | sparse |
| security | 11 | present |
| frontend/UI | 7 | present |
| backend/API | 10 | present |
| data/ML | 14 | present |
| infra/ops/deploy | 10 | present |
| git/release workflow | 2 | sparse |
| docs/writing | 8 | present |
| agents/automation | 33 | broad |
| payments/business | 0 | empty |
| other/uncategorized | 0 | empty |
<!-- END ROUTER INVENTORY SNAPSHOT -->

Privacy: prompt text stays local to the CLI probe. Do not send prompt text, full paths, repo paths, customer names, env vars, tokens, secrets, or private data to hosted calls. Reference skills by NAME, not by body or local absolute path. This is doc-led, model-self-applied guidance; it does not claim a runtime phase-boundary hook exists.
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
