# Local business-context provider

Unlimited Skills can retrieve an owner-approved slice of local business
knowledge alongside the selected skill. This is an opt-in local extension
point: the public core does not ship a company database, hosted memory service,
credentials, or company-specific policy.

## Configure a provider

Create `~/.unlimited-skills/business-context-provider.json` (or set
`UNLIMITED_SKILLS_CONTEXT_PROVIDER_CONFIG` to another file):

```json
{
  "schema_version": 1,
  "enabled": true,
  "provider": {
    "id": "company-memory",
    "command": ["python", "/path/to/local_provider.py"],
    "capabilities": ["retrieve", "completion_candidate", "doctor"],
    "timeout_seconds": 2,
    "max_context_chars": 6000,
    "allowed_sensitivities": ["public", "internal", "internal-sanitized"],
    "env": {"COMPANY_MEMORY_ROOT": "/path/to/private/memory"},
    "scope": "default"
  }
}
```

The command is an argument array, never a shell string. The provider receives
one JSON request on stdin and returns one JSON object on stdout. Test the
contract without changing memory:

```bash
unlimited-skills context doctor --json
unlimited-skills context retrieve "prepare the current customer proposal" --json
```

`unlimited-skills suggest --json --card` automatically includes the provider
result when the config exists. Ordinary text and non-card JSON `suggest`
contracts remain unchanged. Use `--no-business-context` for one card call or set
`UNLIMITED_SKILLS_NO_BUSINESS_CONTEXT=1` as the kill switch.

A provider may return a `diagnostics` object from `doctor`; the CLI exposes at
most 16 identifier-like scalar fields, each capped at 240 characters. This is
the intended place for states such as daemon readiness or policy revision—not
for secrets, raw records, or paths.

## Retrieval response

The provider owns source selection, entity walls, sensitivity policy, and
ranking. A successful response uses this shape:

```json
{
  "schema_version": "unlimited-skills.business-context-response.v1",
  "request_id": "the-request-id",
  "status": "ok",
  "items": [
    {
      "id": "offer-2026",
      "title": "Approved offer",
      "excerpt": "Bounded source-backed reference text.",
      "source_ref": "business/offers/approved.md",
      "sensitivity": "internal"
    }
  ]
}
```

Unlimited Skills rejects absolute/traversing source references, sensitivities
outside the configured allow-list, oversized output, mismatched request IDs,
and incompatible schemas. Injected text is delimited with
`authority="retrieval_only"` and `disclosure="internal"`, retains every
`source_ref`, and is data rather than instructions or external-action authority.

`status: no_context` means only that no eligible context was returned. It is
never converted into a verified absence claim. When the provider is warming or
unavailable, the hook tells the agent to continue only generic work and to
defer company-specific or consequential claims instead of guessing.

## Completion learning

The Claude Code `Stop` hook can offer a bounded final-response candidate to a
provider with the `completion_candidate` capability. It runs only when:

- a provider config exists;
- the Stop event is not recursive;
- no background task or session cron is still running;
- the final response is long enough and contains both an accepted artifact or
  destination and an independent checker or test reference.

The hook hashes raw session/prompt identifiers into an idempotency key and
submits the candidate in a detached process, so memory work does not delay the
agent response. The provider decides whether a completion is durable knowledge
and must return one of `accepted`, `ignored`, `quarantined`, or
`duplicate`. Unlimited Skills itself never promotes a completion to memory.

Set `UNLIMITED_SKILLS_NO_COMPLETION_LEARNING=1` to disable the Stop path while
keeping retrieval enabled. The broader business-context kill switch disables
both retrieval and completion submission.

## Security and privacy boundary

- Configuration is absent and silent by default.
- The task query and completion summary are sent only to the explicitly
  configured local command; they are not uploaded by the public core.
- Provider processes receive a minimal environment. Extra inherited variable
  names must be explicitly allow-listed; explicit static `env` values are
  owner-controlled, bounded, and should contain roots or modes rather than
  credentials.
- Calls have bounded input, output, item count, excerpt length, and timeout.
- A missing, slow, or malformed provider fails open without breaking skill
  retrieval or the agent turn.
- Provider code is trusted local code. Review it and its source/sensitivity
  policy before enabling the integration.
