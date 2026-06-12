# MCP permissioned tool profiles

**Status: PROTOTYPE ENFORCED (designed in E09, implemented in E10).** This
document specifies permissioned tool profiles for the Unlimited Tools
gateway: named, local, default-deny profiles that control which upstream
tools an agent can *see* and which it can *call*. It remains the
authoritative design contract; the gateway now enforces it
(`unlimited_skills/mcp/profiles.py` loads and resolves profiles,
`unlimited_skills/mcp/gateway.py` enforces them in the three meta-tools,
`unlimited-skills mcp gateway --profiles FILE [--profile NAME]` wires them
in — opt-in until v0.6, per "Migration path" step 2; enforcement tests:
`tests/test_mcp_tool_profile_enforcement.py`). References below to "a future
implementation" date from the E09 design stage and now describe the shipped
prototype. It builds directly
on the upstream security model
([mcp-upstream-security-model.md](mcp-upstream-security-model.md), E07) and
its enforcement in the gateway (E08); it strictly tightens that model and
never weakens any existing guarantee (trust levels, redaction, structured
refusals, no-schema-dump).

Artifacts in this change:

- this document;
- `schemas/mcp-tool-profile.schema.json` — JSON Schema (draft 2020-12) for
  the profile file format below;
- `examples/mcp/tool-profile.example.json` — an annotated example that
  validates against the schema (`tests/test_mcp_tool_profile_schema.py`).

Compatibility note: the project has almost no users and backward
compatibility before v0.6 is explicitly not required. Profiles are opt-in
until v0.6 (see "Migration path"); the current open behavior remains the
default and is named **no-profiles mode** below.

## Concept and goals

The upstream security model answers "which *processes* may run and under what
constraints". Profiles answer the next question: "which *tools*, across all
configured upstreams, may this particular agent see and call". One gateway
config can front dozens of upstreams with hundreds of tools; a reviewer agent
should not be able to call `github.create_issue` just because the gateway can
reach it.

A profile defines two sets over fully qualified `<upstream>.<tool>`
identifiers:

- **Visibility** — which tools appear at all. Visibility filters
  `tools_search` results and gates `tools_schema`: an invisible tool is never
  listed, its schema can never be fetched, and refreshing the index never
  spawns an upstream that cannot contribute a visible tool.
- **Callability** — which tools `tools_call` may route. Callability is
  checked after visibility.

**Rule: callable is always a subset of visible.** A tool may be visible but
not callable; it may never be callable but invisible. Justification:

- Visibility is the review surface. Everything an agent could possibly
  invoke must be discoverable by reading `tools_search` output under that
  profile; a hidden-but-callable tool would be capability that no reviewer or
  audit reader can see coming.
- A call to a tool the agent could never have discovered through the
  meta-tools proves out-of-band knowledge (prompt injection, a copy-pasted
  transcript from a more privileged session, host misconfiguration). The
  safe response to that signal is refusal, not routing.
- The converse — visible but not callable — is useful and harmless: the
  agent can find the tool, read its schema (`tools_schema` is
  visibility-gated, not callability-gated), explain to the user that the
  task needs it, and ask for a wider profile, all without being able to
  execute it.

The subset rule is enforced twice: statically at load time (see "Profile
format": every `callable` rule must be covered by the same profile's
`visible` rules) and structurally at evaluation time (a tool is callable only
if it is also visible — defense in depth, so no inheritance edge case can
reorder the two sets).

Design goals, extending E07's:

1. **Default deny when active.** With a profile in force, anything not
   explicitly allowed is invisible and uncallable.
2. **Fail closed, refuse loudly.** A missing or invalid profile never falls
   back to open behavior; it refuses every meta-tool call with a named code.
3. **Local and reviewable.** v1 profiles are one local JSON file a human can
   read top to bottom; the rule grammar is small enough to audit by eye.
4. **Everything observable.** The active profile name is stamped on every
   audit row; every profile refusal is audited.

## Profile format

Profiles live in one local JSON file, validated against
`schemas/mcp-tool-profile.schema.json` (draft 2020-12,
`additionalProperties: false` throughout — unknown keys are load errors, so a
typo like `visble` fails instead of silently denying). Annotated example at
`examples/mcp/tool-profile.example.json`:

```json
{
  "schema_version": 1,
  "default_profile": "dev-default",
  "profiles": {
    "dev-default": {
      "visible": ["github.*", "filesystem.*"],
      "callable": ["github.*", "filesystem.*"]
    },
    "reviewer": {
      "extends": "dev-default",
      "visible": ["github.*", "filesystem.*"],
      "callable": ["github.search_repositories", "filesystem.read_file"]
    }
  }
}
```

Top level:

| Field | Type | Default | Meaning |
| --- | --- | --- | --- |
| `schema_version` | const `1` | required | Format version. |
| `comment` | string | — | Annotation, ignored (house style: JSON has no comments). |
| `default_profile` | profile name | — | Profile used when neither `--profile` nor the env var selects one. |
| `profiles` | object, 1–64 entries | required | Map of profile name → profile. Names match `^[A-Za-z0-9][A-Za-z0-9_-]*$` (same grammar as upstream names). |
| `signature` | object | — | Optional detached-signature envelope; shape-only in v1 (see "Signed/local format"). |

Per profile:

| Field | Type | Default | Meaning |
| --- | --- | --- | --- |
| `comment` | string | — | Annotation, ignored. |
| `extends` | profile name | — | Single parent profile in the same file. No self-reference, no cycles, max chain depth 8 — violations are load errors (`profile_invalid`). |
| `visible` | array of rules, unique, ≤ 256 | see below | Visibility rules. |
| `callable` | array of rules, unique, ≤ 256 | see below | Callability rules. Every rule must be covered by this profile's `visible` rules. |

### Rule grammar

A rule is one string over the same fully qualified identifiers the gateway
already uses for addressing (`<upstream>.<tool>`, split at the **first** dot,
exactly like `tools_call`'s `tool` argument). Exactly two forms exist:

1. **Exact**: `github.create_issue` — matches exactly one tool on exactly one
   upstream. The tool segment is compared as a literal string (MCP tool names
   may themselves contain dots; no further splitting happens).
2. **Whole-upstream glob**: `github.*` — matches every tool of the one named
   upstream. `*` is only valid as the *entire* tool segment.

Schema pattern (the grammar is the pattern — there is no second parser):

```
^[A-Za-z0-9][A-Za-z0-9_-]*\.(\*|[A-Za-z0-9_][A-Za-z0-9_.-]*)$
```

Deliberately unrepresentable, so the matcher stays unambiguous and
constant-time per rule:

- partial globs (`github.create_*`), character classes, alternation,
  regex of any kind — refused by the pattern;
- a wildcard upstream segment (`*.read_file`, `*.*`) — a rule always names
  exactly one upstream, so a tool-name collision on another upstream can
  never be matched by accident (see "Threat model additions");
- whitespace, quoting, escaping — none of it exists in the grammar.

There is intentionally no "allow everything" rule. A maximally open profile
lists one `<upstream>.*` rule per upstream it opens — adding a new upstream
to the gateway config never silently widens any existing profile.

### Evaluation semantics

Matching is over the fully qualified tool name only — rule evaluation never
receives call arguments (see "Redaction"). For a profile `P` and tool `t`:

- `visible(P, t)` = `match(P.visible, t)` AND `visible(parent(P), t)`.
  If `P.visible` is absent: a child inherits (`visible(P, t)` =
  `visible(parent, t)`); a root profile denies everything (default-deny has
  no implicit allow).
- `callable(P, t)` = `match(P.callable, t)` AND `callable(parent(P), t)`
  AND `visible(P, t)` — the trailing conjunct is the structural subset
  guarantee. Absent `P.callable`: child inherits, root denies.

### Static load checks (all `profile_invalid` on failure)

1. Document validates against the schema (types, patterns, unknown keys).
2. Every `extends` target exists in the same file; no self-reference; no
   cycle; chain depth ≤ 8.
3. **Callable coverage**: in any profile that declares both fields, every
   `callable` rule is covered by a `visible` rule — an exact rule is covered
   by the same exact rule or by its upstream's `.*` rule; a `.*` rule is
   covered only by the same `.*` rule. (When `visible` is inherited, the
   check is skipped for that profile; the evaluation-time conjunct still
   guarantees the subset property.)
4. `default_profile`, when present, names an existing profile.

## Default-deny

Three modes, with no silent transitions between them:

1. **No-profiles mode** (current behavior, the default until v0.6): no
   profile file is configured. The gateway behaves exactly as documented in
   [mcp-gateway.md](mcp-gateway.md) — every tool of every spawnable upstream
   is visible and callable, subject only to the E07/E08 upstream security
   model. This mode is a deliberate, named state, not an accident: docs and
   the v0.6 migration call it out explicitly.
2. **Profile active**: a profile file is configured and a profile resolved.
   Anything not matched by the active profile's visible rules does not exist
   as far as the agent can tell; anything not matched by its callable rules
   cannot be routed. There is no "warn-but-allow" intermediate.
3. **Fail-closed refuse-all**: a profile file is configured but the selected
   profile cannot be resolved (`profile_not_found`) or the file is invalid
   (`profile_invalid`). The gateway still starts and serves the three
   meta-tools, but refuses **every** call with the corresponding code, each
   refusal audited. Rationale for starting at all: many MCP hosts swallow
   server startup stderr, so a gateway that dies at load is
   indistinguishable from a missing binary — a structured, audited refusal
   on every call is the loud failure E07 demands, and it never degrades to
   open behavior. (When the gateway is started interactively from the CLI,
   the same condition is *also* reported as a `GatewayConfigError` message on
   stderr at startup.)

## Profile selection

The profile file is wired in with a new CLI flag on the gateway:

```bash
unlimited-skills mcp gateway --config cfg.json --profiles ~/.unlimited-skills/tool-profiles.json --profile reviewer
```

In v1 the file path comes from `--profiles` only (it is deliberately not a
key inside the upstream config file, so the E07 schema is untouched; folding
it into the config can be revisited at v0.6 with a `schema_version` bump).

Which profile applies, highest precedence first:

| Precedence | Source | Typical use |
| --- | --- | --- |
| 1 | `--profile NAME` CLI flag | **Per-agent**: each agent's host entry (e.g. `.mcp.json` args) pins its own profile; two agents on one machine run two gateway processes with different flags. |
| 2 | `UNLIMITED_SKILLS_MCP_PROFILE` env var | **Per-runtime**: CI jobs, containers, or a shell session select a profile without editing host config. |
| 3 | `default_profile` in the profile file | **Per-team**: the team-distributed file carries the team's default. |
| — | none of the above | Fail-closed refuse-all with `profile_not_found` — configuring a profile file *is* the opt-in to default-deny; an unresolved selection never falls back to open behavior. |

CLI beats env beats file because that is the order of explicitness and
proximity to the invocation: the flag is visible in the host config under
review; the env var is ambient; the file default is the fallback the team
shipped. A selected name that does not exist in the file is
`profile_not_found` (fail-closed), never a fallback to `default_profile` —
falling back would silently run an agent under the wrong (likely wider)
profile.

Selection is **per gateway process, fixed at startup**. There is no per-call
or per-session profile switching inside one process (see "Threat model
additions": confused deputy between profiles).

**Team distribution (v1):** profiles are local files. Teams distribute them
like any other dotfile — checked into a repo, copied by an installer, or
managed by existing config tooling. Synchronizing profiles through the
registry (`policy_sync`) is a FUTURE gate with its own design (distribution
authenticity, rollout, revocation) and is explicitly not designed here beyond
this pointer; the optional signature envelope below reserves the format slot
it will need.

## Inheritance

A profile may `extends` exactly **one** parent in the same file. Single
inheritance only: multiple parents force a merge policy — union widens (a
child would gain what any parent allows, inverting the restriction
direction), intersection across several parents is hard to reason about when
reading a file, and diamond chains make "why is this tool denied" a graph
query instead of a linear read. One parent keeps the audit trail linear: a
reviewer reads at most 8 profiles top-down to know exactly what a child can
do.

**Inheritance is restriction-only (intersection), never additive.** A child's
effective sets are the conjunction of its own rules with its parent's
effective sets (see "Evaluation semantics"): a child can narrow what the
parent grants and can never widen beyond it. This is the safer model because
the parent acts as a ceiling — a team ships a baseline profile, and no
locally added child (including a tampered or sloppily written one) can grant
itself more than the baseline, only less. Additive inheritance ("parent +
extra rules") would make every child a potential escalation and would turn
review into auditing every leaf instead of one ceiling. The cost is mild
verbosity (a child restates the subset it keeps; an omitted field inherits
the parent's set unchanged), which is the right trade for a security
boundary.

Cycle handling: `extends` chains are resolved at load; a self-reference, any
cycle, a dangling parent name, or a chain deeper than 8 is a load error
(`profile_invalid`, fail-closed refuse-all) — never a silently ignored edge.

## Signed/local format

**v1 is local, unsigned JSON with a strict schema.** The profile file has the
same trust standing as the upstream config file next to it: whoever can edit
one can edit the other, so v1 signing would add ceremony without adding a
boundary (see "Threat model additions": tampering).

The format reserves one optional, forward-compatible slot — a detached
signature envelope — so that the future profile-signing gate (**Gate C**,
needed for team/registry distribution where the file author and the file
consumer are different parties) does not require a `schema_version` bump:

```json
"signature": {
  "algorithm": "ed25519",
  "key_id": "ai4sale-team-profiles-2026",
  "value": "<base64 detached signature>"
}
```

- The signature is computed over the **canonical JSON** of the document with
  the top-level `signature` member removed: UTF-8, object keys sorted
  lexicographically, no insignificant whitespace (i.e. Python
  `json.dumps(doc, sort_keys=True, separators=(",", ":"), ensure_ascii=False)`).
  Gate C may upgrade this definition to RFC 8785 (JCS); until then the simple
  definition above is normative.
- `algorithm` is a placeholder enum with the single reserved value
  `ed25519`; Gate C owns the final algorithm and key-format decisions.
- **In v1 the gateway validates the envelope's shape only and never verifies
  signatures** — presence of a `signature` grants nothing and blocks
  nothing. Key distribution, trust anchors, rotation, and revocation are
  PKI questions that belong to Gate C and are explicitly not designed here.

**Gate C is now designed (E13):**
[mcp-signed-profile-bundles.md](mcp-signed-profile-bundles.md) specifies
signed profile *bundles* — a self-contained distribution envelope (issuer,
audience, validity window, upstream-namespace ceiling, revocation pointer,
mandatory Ed25519 signature over the canonical JSON defined above) verified
against a local trusted-keys file, with reserved refusal codes
`-32015`…`-32019` continuing this document's family. The paragraphs above
remain accurate for the unsigned local profile file: signing stays opt-in,
this file format is unchanged, and signed bundles are verified only when the
gateway is started with the E14 `--profile-bundle` path.

The v0.4.7-alpha signed MCP profile bundle gate is alpha and may break before
v0.6. The local MIT core may still allow unsigned profiles by policy.
Registered/business signed-required behavior is future-gated unless explicitly
implemented in a later gate. There is no hosted trust fetch, no registry sync,
no OAuth, no resources, no prompts, and no production signing keys in the
public core gate.

## Refusal codes

Extending the implemented `-32001`…`-32010` family in
`unlimited_skills/mcp/gateway.py` contiguously (next free code is `-32011`;
all within the JSON-RPC implementation-defined server-error range). These
four codes are **reserved by this design** and must not be reused for
anything else:

| Code | Name | Meaning | Suggested agent behavior |
| --- | --- | --- | --- |
| `-32011` | `tool_not_visible` | The addressed tool is not in the active profile's visible set — or does not exist at all; the refusal never distinguishes the two. Returned by `tools_schema` and `tools_call` alike. | Do not retry. Use `tools_search` to find permitted alternatives; tell the user the active profile (named in the message) may need widening. |
| `-32012` | `tool_not_callable` | The tool is visible under the active profile but not callable (view-only). | Do not retry. Report that the tool exists but the active profile does not permit calling it; the user must select a wider profile. |
| `-32013` | `profile_not_found` | A profile file is configured but no profile could be resolved (selected name absent, or nothing selected and no `default_profile`). Every meta-tool call is refused with this code. | Never retry. Surface verbatim — this is a configuration stop; the user must fix `--profile` / `UNLIMITED_SKILLS_MCP_PROFILE` / `default_profile`. |
| `-32014` | `profile_invalid` | The profile file fails schema validation or a static load check (unknown key, bad rule string, self-extends, cycle, chain too deep, dangling parent, uncovered callable rule, malformed signature envelope). Every meta-tool call is refused with this code. | Never retry. Surface verbatim; the user must fix the profile file. |

**Information-leak decision:** `tools_call` (and `tools_schema`) on an
*invisible* tool returns `tool_not_visible`, not `tool_not_callable`, with an
existence-neutral message ("not visible under profile 'reviewer' or does not
exist"). Visibility is checked *before* existence, so probing with
`tools_call` cannot distinguish "hidden from you" from "nonexistent" — the
refusal is byte-identical either way. `tool_not_callable` is only ever
returned for tools the agent can already see in `tools_search` output, so it
discloses nothing the profile did not already disclose. Two adjacent leak
plugs that follow from the same decision: when a profile is active, the
unknown-upstream hint must not enumerate configured upstreams that have no
visible tools under the active profile, and the existing unknown-tool
`ToolError` (a domain error, not a refusal) is only reachable for *visible*
names — invisible-or-nonexistent collapse into `-32011` first. In no-profiles
mode the current error behavior is unchanged.

`tools_search` under an active profile returns only visible tools and adds a
`callable: true|false` field to each hit, so an agent never wastes a schema
fetch planning around a view-only tool.

## Audit requirements

Extends the implemented audit model (`unlimited_skills/mcp/audit.py`, E07
"Audit" section) without weakening it:

- **Profile name on every row.** When profiles are active, every audit row —
  success or refusal, at *both* `standard` and `minimal` levels — carries
  `profile: "<name>"`. Profile names are non-sensitive by grammar (see
  "Redaction") and forensically essential: an audit reader must be able to
  answer "what could this session see" from any single row. In fail-closed
  refuse-all states the rows carry the *requested* name (or `""` when none
  was selected). In no-profiles mode the field is absent, which is itself the
  unambiguous marker of open mode.
- **Refusals audited with their code.** Every `-32011`…`-32014` refusal
  appends an `ok: false` row whose error string includes the code name, like
  every existing refusal. No silent denials: a default-deny system without
  refusal audit rows would be undebuggable.
- **A `profile_loaded` startup row.** When a profile file is loaded the
  gateway appends one audit row recording the resolved profile name, the
  SHA-256 of the profile file bytes, and rule counts (numbers only). This
  pins *which version* of a profile governed a session, which is what makes
  the stale-profile threat (below) detectable after the fact.
- **No auto-reload — restart semantics.** The profile file is read exactly
  once at gateway startup; changes on disk have no effect on a running
  gateway. Decided for three operational reasons: (1) an agent's capability
  set never changes mid-task, so enforcement is deterministic for the whole
  session and audit rows need no per-row file hash; (2) no reload means no
  TOCTOU window and no risk of enforcing a half-written file mid-edit;
  (3) it matches the upstream config's existing load-once semantics, and
  stdio MCP servers are cheap for hosts to restart. The cost — revocation
  waits for a restart — is documented as the stale-profile threat with its
  mitigation.

## Redaction

- **Profile names and rule strings are not sensitive.** The grammar makes
  secrets unrepresentable in them (no whitespace, no values, bounded charset)
  — they may appear in audit rows, refusal messages, and stderr diagnostics
  without redaction.
- **Rule evaluation never touches argument values.** Matching is defined
  over the fully qualified tool name only; the evaluator's interface does not
  receive the `arguments` object at all, so "log why this rule matched" can
  never leak a payload by construction. Refusal messages name the profile,
  the code, and the addressed tool — never argument values or fragments.
- **Interplay with audit levels is unchanged.** The existing redaction floor
  (`redact()` / `looks_secret()` / `scrub_paths()`) stays in force
  underneath profiles; the only addition to a `minimal` row is the
  non-sensitive `profile` field. Profile refusal rows obey the addressed
  upstream's `audit_level` exactly like every other refusal (at `minimal`:
  ts/tool/upstream/duration_ms/ok/profile only).

## Threat model additions

Numbered continuing E07's nine vectors:

| # | Vector | Description | Impact | Mitigations |
| --- | --- | --- | --- | --- |
| 10 | **Tool-name collision across upstreams** | Upstream B exposes a tool named like upstream A's (`create_issue`) hoping a rule written for A also opens B. | Profile bypass: a hostile upstream inherits another upstream's grants. | Rules are fully qualified and always name exactly one upstream; the only glob form (`<upstream>.*`) is bounded to that one name; a wildcard upstream segment is unrepresentable by the grammar; upstream names are unique at config load (E07 vector 7 already enforces qualified addressing). |
| 11 | **Confused deputy between profiles** | A low-privilege agent routes requests through (or injects prompts into) a session whose gateway runs a wider profile. | Privilege escalation across agents sharing infrastructure. | One gateway process = one profile, fixed at startup; no per-call or per-session profile switching exists in the protocol surface, so there is nothing for a prompt to flip; per-agent isolation is per-process isolation (each host entry spawns its own gateway with its own `--profile`); audit rows stamp the profile name, so cross-profile traffic would be visible. Residual risk: two agents deliberately configured to share one gateway process share its profile — documented as unsupported for mixed-privilege agents. |
| 12 | **Stale profile** | A tool grant is revoked in the file but a long-running gateway still enforces the old profile (restart semantics). | Revoked capability remains usable until restart. | The `profile_loaded` audit row pins the file SHA-256 per session, so exposure windows are reconstructable; documentation requires restart-on-change as the revocation procedure; fail-closed states never arise from staleness (an old-but-valid profile keeps enforcing — it never widens by itself). Future: a host-visible staleness warning could be added without changing semantics. |
| 13 | **Profile file tampering** | An attacker with local write access edits the profile file to widen visibility/callability before the next gateway start. | Silent privilege escalation at next restart. | v1 stance: the profile file has the same trust standing as the upstream config beside it — local write access already grants upstream command configuration (E07 vector 4 controls), so profiles add no *new* exposure; schema strictness (`additionalProperties: false`, bounded grammar) blocks smuggled keys and over-broad rules; the `profile_loaded` SHA-256 row makes tampering forensically visible; the signature envelope (Gate C) is the designed escalation path for distribution scenarios where author ≠ consumer. |

## Migration path before v0.6

1. **Now (E09, this change):** design only. Codes `-32011`…`-32014` are
   reserved; the schema and example exist; nothing is enforced.
2. **Implementation (a future pre-v0.6 change):** `--profiles` / `--profile`
   / `UNLIMITED_SKILLS_MCP_PROFILE` ship as **opt-in**. No-profiles mode
   remains the default; running without a profile file changes nothing for
   existing setups. Enforcement tests mirror
   `tests/test_mcp_upstream_enforcement.py`.
3. **v0.6 (proposed flip — explicit choice, not silent default-deny):** the
   gateway requires an explicit stance at startup: either a configured
   profile file with a resolvable profile, **or** a new explicit
   `--no-profiles` flag acknowledging open mode. Neither present → startup
   refusal (`GatewayConfigError`, and refuse-all `profile_not_found` for
   hosts that swallow startup errors). This makes default-deny the effective
   default — nobody gets it silently, and nobody keeps open mode without
   having typed the word — without breaking anyone who reads the v0.6
   release notes. Pre-v0.6 breaks are acceptable per project policy; this
   flip is the loud kind.

## Non-goals

- **No implementation in this branch.** Design, schema, example, and
  schema-validation tests only; the gateway code does not change.
- **No OAuth, no remote upstreams, no MCP resources or prompts** — Gates A
  and B (E07) are untouched and unopened.
- **No registry/policy sync.** Team distribution beyond local files is a
  future gate; only the pointer exists here.
- **No PKI.** The signature envelope is a reserved format slot; algorithms,
  keys, trust anchors, and verification are Gate C.
- **No per-call profile switching, no per-tool argument-level rules** —
  rules match tool identity only, never payloads.
- **No PR from this branch before E08 is ready to open.**

## Invariants preserved

Everything in E07's "Invariants preserved" list holds unchanged. Profiles
add one more, restated from the sections above: **a configured profile file
never widens anything** — its only possible effects are hiding tools,
refusing calls, or (when broken) refusing everything.
