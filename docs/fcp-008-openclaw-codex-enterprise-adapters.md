# FCP-008: OpenClaw and Codex Enterprise Fleet Adapters

Status: adapters and local contract tests implemented. Real-topology rollout
evidence is still required before a Business or Enterprise-ready claim.

## Contract change without a wire change

Fleet Wire Contract v1 remains frozen. FCP-008 fixes the local adapter
semantics behind it:

- every desired-state pack is downloaded and verified before activation;
- the complete managed inventory is materialized atomically;
- one runtime generation attests the complete inventory digest;
- each pack retains its own attempt, action, activation nonce, and receipt
  chain;
- a legacy single-item adapter fails closed on a multi-pack desired state
  before it activates anything.

The complete target inventory may contain multiple packs, and each pack may
contain multiple skills. A rollback is a new, higher-epoch complete target,
not an imperative file-reversal command.

## OpenClaw boundary

One `OpenClawFleetAdapter` manages exactly one configured OpenClaw `agentId`
and its exact workspace. Six configured agents therefore require six
registered Fleet instances and six independent managed roots.

The adapter:

- verifies the agent ID and workspace through `openclaw agents list --json`
  during provisioning;
- keeps immutable pack revisions outside the live skills directory;
- retains the signed hash-bound archive and re-verifies the extracted tree
  before activation;
- atomically materializes the active inventory under
  `<workspace>/skills/.unlimited-skills-fleet-active`;
- rejects duplicate delivered skill names;
- rejects collisions with an unmanaged skill at the same workspace
  precedence;
- installs a finite host-level `agent:bootstrap` hook;
- accepts runtime evidence only when that exact agent ID and workspace start
  a real run after the activation.

The hook invokes only the local, installed Unlimited Skills evidence command.
It does not accept a server-provided command, add prompt text, read
transcripts, or upload skill bodies. It stores a hash of the OpenClaw session
key rather than the raw key.

Provision one already-configured agent:

```bash
unlimited-skills fleet openclaw-provision \
  --managed-root <fleet-root-for-agent> \
  --agent-id <exact-agent-id> \
  --workspace <exact-workspace> \
  --openclaw-home <openclaw-state-root> \
  --json
```

Run one control-loop iteration:

```bash
unlimited-skills fleet run-once \
  --runtime-vendor openclaw \
  --managed-root <fleet-root-for-agent> \
  --agent-id <exact-agent-id> \
  --workspace <exact-workspace> \
  --openclaw-home <openclaw-state-root> \
  --public-keys <fleet-public-keys.json> \
  --organization-id <server-org-id> \
  --auto-activate \
  --json
```

OpenClaw loads workspace skills at the highest skill precedence and refreshes
the skill snapshot on a later turn when its watcher observes `SKILL.md`
changes. The runtime receipt is still pending until the managed
`agent:bootstrap` hook runs for the bound agent. A newly installed hook may
require the operator to reload or restart the Gateway for the installed
OpenClaw version; `hooks info` alone is not runtime proof.

OpenClaw skills outside the adapter-owned subtree remain unmanaged. The
adapter does not claim they are absent, compliant, or governed by the Fleet
inventory digest.

## Codex boundary

One `CodexFleetAdapter` owns an isolated:

```text
<managed-root>/
  managed-root.json
  releases/
  state/
  runtime/
    codex-home/
      hooks.json
    workspace/
      .agents/
        skills/
  runtime-history/
  control/
```

The runtime workspace is deliberately not the AIS-OS repository. The active
pack inventory is the complete `.agents/skills` directory in that isolated
workspace. Codex is launched with the exact workspace and `CODEX_HOME`.

Codex also loads user, admin, and system skills from locations outside this
workspace. Those skills are not part of the Fleet inventory digest. Before
activation, the adapter rejects a name collision with the configured user
skills root. Admin and system skill policy remains an Enterprise
configuration responsibility.

Prepare or run one control-loop iteration:

```powershell
unlimited-skills fleet run-once `
  --runtime-vendor codex `
  --managed-root <codex-agent-root> `
  --public-keys <fleet-public-keys.json> `
  --organization-id <server-org-id> `
  --auto-activate `
  --json
```

Launch the corresponding Codex runtime:

```powershell
unlimited-skills fleet codex-launch `
  --managed-root <codex-agent-root> `
  -- `
  <codex-arguments>
```

The launcher rejects a caller-supplied `-C` or `--cd` override and starts the
resolved Codex executable without a shell. The `SessionStart` hook must
observe `startup` or `resume`, the exact managed `CODEX_HOME`, exact managed
workspace, current activation marker, and current skills tree.

User-level Codex command hooks require review and trust. The adapter never
silently bypasses that control. A production Enterprise rollout should deliver
the same command as a managed hook through the organization's supported
system, MDM, cloud, or `requirements.toml` policy. Until either the user-level
hook is explicitly trusted or the admin-managed hook is active, the accurate
state is `ACTIVATION_PENDING`.

## Privacy and security

Neither adapter writes the following to Fleet evidence:

- registration or device credentials;
- raw OpenClaw session keys or Codex session IDs;
- prompts, task text, transcripts, or working-directory paths;
- environment values;
- private skill bodies.

Evidence contains only bounded runtime identifiers or their hashes, agent and
release identities, activation bindings, tree and inventory digests, adapter
version, process identifiers, and timestamps.

Remote agents must not mount or crawl the AIS-OS repository, Company Memory,
raw chat, or private runtime ledgers. Delivery uses signed pack artifacts and
the Fleet control plane only.

## Required real-topology proof

FCP-008 is accepted only after all of the following are captured:

1. one independent Fleet identity for every configured OpenClaw agent and
   every managed Codex runtime;
2. exact agent/workspace or home/workspace binding for every instance;
3. a multi-pack activation observed by each real runtime;
4. one intentionally pending runtime proving that copied files are not
   reported as active;
5. independent drift and receipt-backed repair;
6. higher-epoch rollback with a fresh runtime generation;
7. offline/retry recovery without receipt loss;
8. matching dashboard, projection, ledger, snapshot, and rebuild truth;
9. no path, credential, prompt, transcript, or private body leakage;
10. documented OpenClaw Gateway lifecycle and Codex hook-trust procedure.

Until that evidence exists, the only accurate status is:
`FCP-008 implementation complete; real-topology pilot pending`.

## Runtime references

- OpenClaw skills: <https://docs.openclaw.ai/skills>
- OpenClaw internal hooks: <https://docs.openclaw.ai/automation/hooks>
- OpenClaw agent workspaces: <https://docs.openclaw.ai/agent-workspace>
- Codex skills: <https://learn.chatgpt.com/docs/build-skills>
- Codex hooks: <https://learn.chatgpt.com/docs/hooks>
- Codex environment variables:
  <https://learn.chatgpt.com/docs/config-file/environment-variables>
