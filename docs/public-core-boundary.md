# Public Core Boundary

The public MIT core must remain local-first. Registration gates hosted services only.

## Commands That Must Not Require Registration

- `search`
- `list`
- `view`
- `where`
- `use`
- `feedback`
- `reindex`
- `vector-reindex`
- `serve`
- `adapt`
- `adapt-one`
- `adapt-next`
- `apply-adaptation`
- `sync-native`
- `self-update check`
- `self-update apply`
- agent installers
- migration scripts
- local daemon and local learning logs

`serve` is the free local daemon and remains unregistered.

## Commands That Require Registration

- `register`
- `catalog list`
- `updates check`
- `updates apply`
- `enhance download`
- `enhance run`
- `team create`
- `team join`
- `team sync`
- `team pending`
- `team members`
- `team approve`
- `team reject`
- `team revoke`
- `team mode`
- `team collections`
- `team leave`
- `community list`
- `community search`
- `community preview`
- `community install`
- `community submit`
- `community submission-status`
- `hub serve`
- `hub clients`
- `hub token create`
- `hub token list`
- `hub token revoke`
- `remote search`
- `remote resolve`
- `remote view`

`remote search`, `remote resolve`, and `remote view` are registered product commands, but in `v0.2.0-alpha` they are contract skeletons only. Real hub calls are planned for the next remote-client PR.

`license status` reads local registration state only. It must work without registration and show unregistered status.

No registration, no official hosted skill updates. Local skills remain usable.

`community installed` is local-only unless `--refresh` is passed. `community remove` is local-only by default and must not contact the hosted service.

## Hosted Client Privacy Boundary

Hosted metadata calls must not upload skill bodies, prompts, source code, full local paths, repository paths, customer names, environment variables, tokens, secrets, or device private keys. Collection versions, source labels, skill-count buckets, public device keys, key thumbprints, and signed device proof metadata are allowed.

Community submission is the explicit exception: `community submit <path>` uploads only the selected skill or pack after local validation, preview generation, and explicit confirmation. List, search, preview, update checks, install-plan checks, and installed listing must not upload local skill bodies.

Public repo self-update remains unregistered because it updates the MIT public core from GitHub. Hosted skill updates require registration.

Team status may read local `team.json` without a hosted refresh. Any hosted status refresh, member listing, approval, rejection, revocation, collection listing, sync, or leave operation requires registration.

`hub status`, `hub init`, `hub doctor`, `remote configure`, and `remote status` may read or write local configuration without hosted calls. `hub serve` is a separate registration-required product command and must not be confused with the free `serve` daemon.

Local `search`, `list`, and `view` remain unregistered even when remote hub support exists.

Local Skill Hub client tokens are local credentials stored as hashes in `hub.json`. They protect the registered local/LAN hub only and must not be confused with hosted registration tokens.
