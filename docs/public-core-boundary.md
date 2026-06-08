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
- `team approve`
- `team mode`
- `community list`
- `community search`
- `community preview`
- `community install`
- `community submit`
- `community submission-status`

`license status` reads local registration state only. It must work without registration and show unregistered status.

No registration, no official hosted skill updates. Local skills remain usable.

`community installed` is local-only unless `--refresh` is passed. `community remove` is local-only by default and must not contact the hosted service.

## Hosted Client Privacy Boundary

Hosted metadata calls must not upload skill bodies, prompts, source code, full local paths, repository paths, customer names, environment variables, tokens, secrets, or device private keys. Collection versions, source labels, skill-count buckets, public device keys, key thumbprints, and signed device proof metadata are allowed.

Community submission is the explicit exception: `community submit <path>` uploads only the selected skill or pack after local validation, preview generation, and explicit confirmation. List, search, preview, update checks, install-plan checks, and installed listing must not upload local skill bodies.

Public repo self-update remains unregistered because it updates the MIT public core from GitHub. Hosted skill updates require registration.
