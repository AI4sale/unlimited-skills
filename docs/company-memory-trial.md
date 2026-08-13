# Company Memory trial client

Unlimited Skills includes an opt-in client for a compatible Company Memory
service. The hosted service and its operator control plane are not part of this
public repository.

## Start and verify

```bash
unlimited-skills memory init --trial --url https://memory.example.com --json
unlimited-skills memory status --json
unlimited-skills memory doctor --json
```

For a private server certificate authority:

```bash
unlimited-skills memory init --trial \
  --url https://memory.example.com \
  --server-ca ./server-ca.crt \
  --json
```

`init` performs the complete non-commercial setup:

1. Generates independent 3072-bit RSA keys and CSRs for executor and checker.
2. Persists an opaque installation ID and the pending keys before the network
   call, so a lost response replays the same installation instead of creating
   an orphan tenant.
3. Requests a bounded provisional trial over HTTPS.
4. Stores the returned client certificates beside the local private keys.
5. Installs the JSON-over-stdio business-context provider.
6. Retrieves start context under both identities, submits one checked terminal
   outcome, retrieves the resulting record, and requires server state
   `FIRST_VALUE_VERIFIED`.

Private keys never leave the machine. The server receives only CSRs. The
server derives tenant and workload identity from the authenticated certificate;
request bodies cannot select another tenant.

## Runtime task correlation

Set a stable task ID before an agent begins company work:

```bash
export UNLIMITED_SKILLS_TASK_ID=customer-onboarding-2026-08-13
unlimited-skills suggest "prepare customer onboarding" --json --card
```

Or provide it directly to an explicit retrieval:

```bash
unlimited-skills context retrieve "customer onboarding policy" \
  --task-id customer-onboarding-2026-08-13 \
  --json
```

The task ID is forwarded to Company Memory so the service can issue a
correlated access receipt. It does not grant write, commercial, or external
action authority.

## Checked task write-back

The default provider role is `executor`. Before task execution, retrieve with a
stable task ID. A separate checker run retrieves under the same task ID with
the checker identity:

```bash
export UNLIMITED_SKILLS_TASK_ID=customer-onboarding-2026-08-13
export UNLIMITED_SKILLS_MEMORY_ROLE=checker
unlimited-skills context retrieve "checker policy and task evidence" --json
```

The provider stores only the two access-receipt IDs in the private local
bundle. It does not cache the retrieved excerpts. After checking the terminal
result, the checker writes a bounded file:

```json
{
  "schema_version": "unlimited-skills.checked-task-outcome.v1",
  "task_id": "customer-onboarding-2026-08-13",
  "outcome_key": "customer-onboarding-2026-08-13:accepted",
  "verdict": "accepted",
  "confidence": 0.95,
  "summary": "The onboarding result was completed and independently checked.",
  "evidence_refs": ["artifact-ref:customer-onboarding-result"]
}
```

Submit it from the checker runtime:

```bash
unlimited-skills memory outcome --file checked-outcome.json --json
```

The file cannot select tenant, actor, executor, checker, or receipt IDs. The
client derives the executor workload and both task-bound access receipts; the
server derives checker and tenant from mTLS. Missing or cross-task receipts
fail closed. `accepted` and `returned` are both terminal evidence states and
are routed by the server-side Knowledge Evolution policy.

The one-machine trial demonstrates protocol separation but is not an
organizational independence claim. Production deployments should run executor
and checker identities in separate least-privilege runtimes controlled by the
tenant's reviewer policy.

## Lifecycle commands

```bash
unlimited-skills memory renew --json
unlimited-skills memory maintain --json
unlimited-skills memory outcome --file checked-outcome.json --json
unlimited-skills memory handoff --json
unlimited-skills memory revoke --json
```

- `renew` rotates executor and checker certificates independently. Pending
  keys survive interruption and the server replays an already issued result.
- `maintain` performs the same renewal check and requests handoff when the
  verified trial reaches its final 24 hours. Normal provider retrieval runs
  this maintenance lazily, so an actively used trial needs no copied secret or
  human scheduler step.
- `handoff` asks for human claim after first value. It cannot carry price,
  payment, contract, production scope, or secrets.
- `revoke` revokes both server identities and disables the local context
  provider. Tenant deletion remains a server retention-policy operation.

Commercial activation is intentionally absent from the public agent CLI. A
human owner must claim the tenant and a separate billing authority must record
commercial evidence on the private control plane. Only that transition lifts
trial TTL and quota enforcement; the agent cannot promote itself.

## Local files

The default root is `~/.unlimited-skills`; override it with
`UNLIMITED_SKILLS_HOME`. The client creates:

- `company-memory/state.json`;
- `company-memory/executor-identity.pem`;
- `company-memory/checker-identity.pem`;
- optional `company-memory/server-ca.crt`;
- `business-context-provider.json`.

State and key material are written atomically with private file permissions.
Do not commit, upload, or attach these files to support requests.
