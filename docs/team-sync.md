# Team Sync

Team sync installs approved hosted/team collection assignments on registered team instances.

## Dry Run

Always inspect changes first:

```bash
unlimited-skills team sync --dry-run --json
```

Dry run shows:

- collections to install or update;
- target versions;
- installed versions when known;
- archive sizes when provided by the server;
- warnings;
- local target paths;
- whether reindexing is needed.

Dry run writes no library files. It records a local redacted audit event.

## Apply

```bash
unlimited-skills team sync --yes
```

Apply flow:

1. Fetch team sync manifest from the hosted service.
2. Filter by `--collection` when supplied.
3. Download team collection archives.
4. Verify SHA256 before extraction.
5. Safely extract archives and reject path traversal.
6. Install team-owned collections.
7. Rebuild the lexical index unless `--skip-reindex` is passed.
8. Record a redacted local audit event.

The current client enforces SHA256 verification and safe extraction. Cryptographic signature verification is planned and must not be described as implemented until the client enforces it.

## Removals

The manifest may include `removals`. The current public client reports removals in dry run. Destructive removal of local collections must not delete custom local skills unless the manifest explicitly owns the collection and the user confirms. Private encrypted pack publishing is not part of Team Free.

## Ownership

Team sync manages team-assigned collections. It should not overwrite unrelated local custom collections unless the target collection is explicitly assigned by the team manifest and the user confirms the operation.

## Rollback Expectations

Collection install uses the existing local update path: the previous target collection is moved to a temporary backup, the new collection is copied into place, and the backup is restored if installation fails. This protects the collection being updated, but it is not a full machine backup. Use `team sync --dry-run` before applying changes and keep separate backups for important local custom collections.

## Offline Behavior

Without registration or hosted access, Team Free commands fail with a registration/hosted-access message. Local MIT commands such as `search`, `list`, `view`, `reindex`, `adapt`, and `self-update` continue to work.

## Vector Index

Successful sync rebuilds the lexical index. If a Chroma vector index exists, run:

```bash
unlimited-skills vector-reindex
```

Vector reindexing is recommended after large team collection changes.
