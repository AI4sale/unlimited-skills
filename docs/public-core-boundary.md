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
- `service configure`
- `service status`
- `service doctor`
- `service verify-trust`
- `service test-registration --dry-run`
- `service test-proof`
- `policy status`
- `policy verify`
- `policy install`
- `policy remove --yes`
- `policy explain`
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
- `hub sync`
- `hub clients`
- `hub token create`
- `hub token list`
- `hub token revoke`

`remote search`, `remote resolve`, and `remote view` are Local Skill Hub client commands. They do not require hosted registration on the client machine, but they require a configured hub URL and hub client token when using the hub. With `fallback=local_allowed`, they can fall back to the local MIT library if the hub is unavailable. With `fallback=hub_required`, they fail clearly. They never query the hosted registry by default.

Remote-first installer flags for Codex, Claude Code, Hermes, and OpenClaw write local remote hub config and router instructions only. They do not register the client, do not gate local MIT commands, and do not store raw hub tokens in visible router files. Prefer `--hub-token-env ULS_HUB_TOKEN`; `--hub-token` stores the raw token only in private `remote.json`.

`license status` reads local registration state only. It must work without registration and show unregistered status.

`service configure`, `service status`, `service doctor`, `service verify-trust`, `service test-registration --dry-run`, and `service test-proof` are onboarding/support commands. They do not unlock hosted catalog features and do not gate local MIT commands. `service status` is local-only unless `--refresh` is passed. `service doctor` and `service verify-trust` may contact only health/ready/public-key endpoints and must not upload local skill bodies, skill names, prompts, paths, queries, tokens, or private keys.

Enterprise Skill Lock is opt-in local governance. With no installed policy, Community Core behavior is unchanged. With a policy installed in `audit` mode, disallowed actions are logged and allowed. With a policy installed in `enforce` mode, hosted registry access, release-channel selection, manifest keys/scopes, community install/submit, hub local allowlists, remote fallback, and explicitly restricted local roots can be refused. This policy layer must not require registration and must not upload local skills or prompts.

No registration, no official hosted skill updates. Local skills remain usable.

`community installed` is local-only unless `--refresh` is passed. `community remove` is local-only by default and must not contact the hosted service.

## Hosted Client Privacy Boundary

Hosted metadata calls must not upload skill bodies, prompts, source code, full local paths, repository paths, customer names, environment variables, tokens, secrets, or device private keys. Collection versions, source labels, skill-count buckets, public device keys, key thumbprints, and signed device proof metadata are allowed.

Community submission is the explicit exception: `community submit <path>` uploads only the selected skill or pack after local validation, preview generation, and explicit confirmation. List, search, preview, update checks, install-plan checks, and installed listing must not upload local skill bodies.

Public repo self-update remains unregistered because it updates the MIT public core from GitHub. Hosted skill updates require registration.

Team status may read local `team.json` without a hosted refresh. Any hosted status refresh, member listing, approval, rejection, revocation, collection listing, sync, or leave operation requires registration.

`hub status`, `hub init`, `hub doctor`, `remote configure`, and `remote status` may read or write local configuration without hosted calls. `hub init --allowlist <file>` is allowed without registration because the operator explicitly supplies a local fixture allowlist. Official `hub sync` requires registration and must not upload local skill bodies. `hub serve` is a separate registration-required product command and must not be confused with the free `serve` daemon.

Local `search`, `list`, and `view` remain unregistered even when remote hub support exists.

Local Skill Hub client tokens are local credentials stored as hashes in `~/.unlimited-skills/hub/hub.json`. They protect the registered local/LAN hub only and must not be confused with hosted registration tokens.

Capability reports and install plans are local/remote-hub metadata. They may list package names, binary names, platform names, and environment variable names, but they must not include environment values or execute installers.
