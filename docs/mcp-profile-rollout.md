# MCP profile rollout simulator and policy doctor (E16)

`unlimited-skills mcp profiles rollout-plan|doctor` is a local **dry-run**
over the artifacts the Unlimited Tools gateway would load at startup -- the
raw E09/E10 profile file, the E13/E14 signed bundle, the E14/E15 trust
artifacts, and the gateway upstream config -- answering *"what WOULD happen
if I started the gateway with these flags?"* before anything is applied.

Both commands are **read-only and offline by construction**: no upstream is
ever spawned (no subprocess use at all), no audit row is written, no runtime
state changes, no network calls, no telemetry, and no private key material
is read or printed. The REAL loading and verification logic runs in
dry-run -- `unlimited_skills/mcp/profile_rollout.py` reuses
`profiles.resolve_profile_state`, `bundles.resolve_bundle_state` (the full
E14 10-step verification), and the E15 trust-store doctor; nothing is
reimplemented, so the simulator can never drift from enforcement.

## Inputs (both commands)

| Flag | Meaning |
| --- | --- |
| `--config FILE` | Gateway upstream config (`schemas/mcp-upstream-config.schema.json`). Its pre-declared `tools` entries are the default tool list; disabled / placeholder upstreams are excluded exactly as the gateway excludes them. |
| `--profiles FILE` | Raw permissioned tool-profile file (E09/E10). Alongside `--bundle` it is the narrow-only local override. |
| `--bundle FILE` | Signed profile bundle (`schemas/mcp-profile-bundle.schema.json`); the real E14 verification runs in dry-run. |
| `--trusted-keys FILE` | Trusted-keys file for verification. Omitted: defaults to the managed trust store's `trusted-keys.json` under `<root>/.unlimited-skills-trust` when it exists (E15), exactly like the gateway. |
| `--audience-id ID` | This consumer's audience identifier (repeatable; beats `UNLIMITED_SKILLS_MCP_AUDIENCE`). |
| `--profile NAME` | Profile to simulate (`--profile` > `UNLIMITED_SKILLS_MCP_PROFILE` > the source's `default_profile`). |
| `--tools-fixture FILE` | What-if tool list: a JSON list of `{upstream, name, description}` objects replacing the config's pre-declared tools. |
| `--require-signed-profiles` | Simulate the signed-required policy (unsigned sources fail closed with `-32015`). |
| `--json` | Machine-readable output. |

## `rollout-plan`

Builds the plan (human text, or `--json` validating against
`schemas/mcp-profile-rollout-plan.schema.json`, draft 2020-12; a generated
example lives at `examples/mcp/profile-rollout-plan.example.json`):

- **tools** -- visible count and full list, hidden count and list, callable
  count, view-only count, and `refused_by_policy`: every call the gateway
  would refuse on policy grounds (hidden `-32011` + view-only `-32012`; the
  whole set in a fail-closed state).
- **upstreams** -- per upstream: trust level, spawnability, declared and
  visible tool counts, and `would_spawn` / `loses_all_visibility`: an
  upstream none of whose tools can ever be visible under the profile is
  never spawned by the gateway, and the plan says so up front.
- **inheritance** -- the `extends` chain and, per step from root to leaf,
  the declared rule counts plus the cumulative visible/callable tool counts
  (restriction-only inheritance: the counts can only ever shrink). A
  narrow-only local file alongside a bundle is flagged.
- **verification** -- what E14 verification WOULD say: `ok` with the bundle
  provenance (file SHA-256, issuer key id/display, audience, expiry), or
  the exact refusal code/name and the failing step
  (`key_lookup`/`signature`/`validity_window`/`revocation`/`audience`/
  `namespace_ceiling`/`shape_or_static_checks`/`selection`/`policy`).
- **audit_impact** -- the exact fields the gateway's `profile_loaded`
  startup row would record (hashes, key ids, names, counts -- never key
  material or signature values), whether per-call rows would carry the
  profile name, and the upstream `audit_level` split.
- **warnings / blockers** -- blockers are conditions under which the
  gateway would refuse to start (bad flag combinations, an invalid config)
  or refuse every call (a fail-closed profile state).

Exit code 0 whenever a plan is produced; the plan itself carries blockers.

## `doctor`

The same dry-run expressed as **distinct findings**, each with a severity:
`problem` (exit 1) or `warning` (exit 0). Unlike verification -- which
stops at the first failing step -- the doctor reports every independent
condition it can see:

| Finding | Severity | Meaning |
| --- | --- | --- |
| `trust_store_missing` | problem | A bundle is configured but no trusted-keys file / managed store exists (`-32019`). |
| `trust_store_corrupt` | problem | The trusted-keys file is unreadable or malformed (`-32019`). |
| `key_expired` | problem / warning | A trusted key is past `not_after` (problem when it signs the configured bundle, warning for bystander keys). |
| `key_revoked` | problem / warning | A trusted key is listed in the local CRL (problem when it signs the configured bundle). |
| `unknown_key_id` | problem | The bundle is signed by a key absent from the trust store (`-32019`). |
| `audience_mismatch` | problem | The bundle's audience does not intersect the local identifiers (`-32018`). |
| `issuer_scope_violation` | problem | A profile rule escapes the issuer's `allowed_upstream_namespaces` ceiling (`-32018`). |
| `bundle_expired` | problem | The current time is outside the signed validity window (`-32016`). |
| `profile_hides_all_tools` | problem | The selected profile's visible set is empty over the known tool list: `tools_search` would return nothing and no upstream would ever spawn. |
| `callable_not_covered` | warning | A declared callable rule matches nothing the resolved visible set could ever contain -- inert dead weight (callable always requires visible). |
| `shadowed_tool_name` | warning | The same tool name exists on multiple upstreams (confused-deputy heads-up; addressing is fully qualified, but review intent). |
| `profile_chain_too_deep` | problem | An `extends` chain deeper than 8 -- loading would fail with `-32014`. |
| `unsigned_under_signed_policy` | problem | `--require-signed-profiles` with only an unsigned `--profiles` source (`-32015`). |
| `unsigned_local_narrowing` | warning | An unsigned local file narrows a signed bundle under the signed-required policy (allowed, narrow-only -- but an unsigned artifact in a signed rollout). |
| `trust_store_doctor` | problem / warning | Pass-through of the E15 managed-store doctor's own checks (rotation, metadata, permissions, strict-loader agreement). |
| `rollout_fail_closed` | problem | The authoritative dry-run outcome: the real resolution's first failing step with its exact refusal code. |
| `input_error` | problem | A flag combination or input the gateway would refuse to start with. |
| `bundle_unreadable` | problem | The bundle file is not a readable JSON object (`-32014`). |
| `no_tools` | warning | No tool list available; visibility findings are over an empty set. |

## Boundaries

- Simulation only: nothing here changes enforcement, the trust store, the
  audit log, or any runtime state -- removing the commands changes nothing
  about the gateway.
- No hosted calls, no network, no telemetry, no upload; private keys are
  never read, requested, or printed.
- Verification semantics live in `unlimited_skills/mcp/bundles.py` and are
  never altered or bypassed by the simulator; a plan saying "ok" is the
  same code path that the gateway runs at startup.

See also: [mcp-gateway.md](mcp-gateway.md),
[mcp-permissioned-tool-profiles.md](mcp-permissioned-tool-profiles.md),
[mcp-signed-profile-bundles.md](mcp-signed-profile-bundles.md),
[mcp-trust-store.md](mcp-trust-store.md).
