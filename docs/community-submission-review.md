# Community Submission Review

Community submission is an explicit publishing workflow. It uploads selected user content for maintainer review only after local preview and confirmation.

## Submitter Flow

1. Select a single skill, skill directory, pack, or collection directory.
2. Run `unlimited-skills community submit <path> --dry-run`.
3. Register the installation before uploading to the hosted service.
4. Review the generated preview file and terminal output.
5. Fix warnings before upload when possible.
6. Run `unlimited-skills community submit <path> --yes` to upload in non-interactive mode, or type the confirmation phrase in interactive mode.

The preview shows:

- skill names;
- file list;
- byte counts;
- SHA256 values;
- metadata;
- detected warnings.

The preview does not upload anything.

## Maintainer Review

After upload, maintainers review the submission before publication. The hosted service may return these statuses:

- `uploaded`: upload received;
- `pending_review`: waiting for maintainer review;
- `changes_requested`: submitter should revise and resubmit;
- `approved`: accepted but not necessarily visible yet;
- `published`: visible in the registered community catalog;
- `rejected`: not accepted;
- `withdrawn`: removed by submitter or maintainer workflow.

Reviewer notes may be shown to the submitter. Private review internals are not exposed by the client.

Client commands:

```bash
unlimited-skills community submission-status [submission-id]
unlimited-skills community review-notes <submission-id>
unlimited-skills community withdraw <submission-id>
```

`submission-status`, `review-notes`, and `withdraw` are hosted community operations and require a registered installation.

## Prohibited Content

Community submissions must not include:

- secrets, tokens, private keys, passwords, or API keys;
- malware or credential harvesters;
- private customer data;
- copyrighted proprietary material without permission;
- prompts containing hidden exfiltration instructions;
- tool instructions that bypass local, team, or enterprise policies;
- code or instructions that disable safety checks;
- files from `.git`, `.env`, vector databases, dependency folders, virtual environments, local learning logs, caches, or logs.

The client rejects blocked file classes before upload and warns on obvious secret patterns. Maintainer review remains required because local heuristics are not a substitute for policy review.

## Deprecation And Removal

Published community items may later be deprecated, retired, or removed when they become unsafe, obsolete, policy-violating, or superseded. The hosted service should expose deprecation metadata through list, search, preview, and install-plan responses so clients can warn users before install.
