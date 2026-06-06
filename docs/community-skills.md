# Community Skills

Status: planned registry feature.

The `community-skills` catalog is a hosted registry surface for shared community skill packs and individual community skill submissions.

Registration is required to:

- browse or sync the official `community-skills` catalog;
- install official community skill updates through the registry;
- submit or push skills into the community catalog.

Without registration, the MIT core still works locally:

- local search;
- local view/list;
- local indexing;
- local daemon mode;
- local imports;
- bundled bootstrap skills;
- manual skill edits.

## Publishing Model

Pushing to `community-skills` is different from telemetry or update checks.

Telemetry and update checks must not upload local skill contents. A community publish request intentionally uploads only the skill or pack selected by the user for publication.

Planned flow:

1. User registers the instance.
2. User selects a skill or pack to submit.
3. Client shows what will be uploaded.
4. User confirms the submission.
5. Client uploads the selected skill/package to the registry.
6. Registry stores it as a pending community submission.
7. Maintainer review, automated checks, and policy checks run before publication.
8. Approved submissions become available in the official `community-skills` catalog.

## Planned Commands

```bash
unlimited-skills community list
unlimited-skills community install <skill-or-pack>
unlimited-skills community submit <path>
unlimited-skills community status
```

The exact command names may change during implementation.
