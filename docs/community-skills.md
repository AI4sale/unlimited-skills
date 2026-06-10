# Community Skills

Status: registered client flow implemented; hosted backend remains AI4sale-operated early access.

The Community Skills surface is the user-facing discovery, installation, and submission layer for shared skill packs. It is separate from the official registered adapted catalog:

- `catalog` means official registered hosted catalogs and collection metadata;
- `community` means community discovery, preview, install, submission, local installed listing, and local removal.

The public MIT repository contains the local client, schemas, sanitized examples, and docs. It does not publish private registered catalog skill bodies.

## Registration Boundary

Registration is required for hosted community operations:

```bash
unlimited-skills community list
unlimited-skills community search "react"
unlimited-skills community preview <catalog-item-id>
unlimited-skills community install <catalog-item-id>
unlimited-skills community submission-status [submission-id]
unlimited-skills community withdraw <submission-id>
unlimited-skills community review-notes <submission-id>
unlimited-skills community submit <path> --yes
```

Without registration, the MIT local core still works:

- `search`;
- `list`;
- `view`;
- `where`;
- `reindex`;
- `adapt`;
- `serve`;
- native sync;
- agent installers;
- public `self-update`.

`community installed` reads local metadata and does not call the hosted service unless `--refresh` is passed. `community remove` is local-only by default.

`community submit <path> --dry-run` is also local-only: it validates the selected path and writes the upload preview without requiring registration or contacting the hosted service.

## Browse And Install

```bash
unlimited-skills community list --channel canary
unlimited-skills community search "browser qa" --compatible-agent codex
unlimited-skills community preview comm_browser_qa
unlimited-skills community install comm_browser_qa --dry-run
unlimited-skills community install comm_browser_qa --yes
```

Install flow:

1. The client requests an install plan from the registered community service.
2. The server returns a signed approved/published item plus sanitized metadata, archive URL, and SHA256.
3. The client downloads the archive over HTTPS.
4. The client verifies SHA256 before extraction.
5. The client safely extracts the archive and rejects path traversal.
6. The client installs under `registry/<requested-collection>/`, usually `registry/community/`.
7. The client records local installed metadata and rebuilds the lexical index unless `--skip-reindex` is passed.

No downloaded community content is executed by this flow. Preview and install refuse unsigned hosted community responses and signed items whose review status is not `approved` or `published`.

## Submit

Community submission intentionally uploads the selected skill or pack for maintainer review. It is not telemetry.

```bash
unlimited-skills community submit ./my-skill --dry-run
unlimited-skills community submit ./my-skill --tags qa,browser --compatible-agent codex --yes
```

Submit flow:

1. The client validates the selected path.
2. The client rejects hidden files, environment files, VCS directories, vector databases, local learning logs, virtualenvs, dependency trees, cache files, and logs.
3. The client validates `name` and `description` frontmatter for each selected skill.
4. The client scans selected files for obvious secrets and local absolute paths.
5. The client writes a preview file under `~/.unlimited-skills/submissions/`.
6. The client prints exactly what will be uploaded: skill names, file list, total bytes, metadata, and warnings.
7. Upload requires `--yes` in non-interactive mode or typed confirmation in interactive mode.

The upload contains only the user-selected skill or pack content. List, search, preview, update checks, and installed listing do not upload local skill bodies.

## Status And Local Management

```bash
unlimited-skills community submission-status
unlimited-skills community submission-status <submission-id>
unlimited-skills community withdraw <submission-id>
unlimited-skills community review-notes <submission-id>
unlimited-skills community installed
unlimited-skills community installed --refresh
unlimited-skills community remove community --dry-run
unlimited-skills community remove community --yes
```

Submission statuses:

- `draft`;
- `uploaded`;
- `pending_review`;
- `changes_requested`;
- `approved`;
- `published`;
- `rejected`;
- `withdrawn`.

Local remove refuses to delete non-community local skills unless `--force` is passed.
