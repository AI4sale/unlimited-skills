---
name: messages-ops
description: "Evidence-first live messaging workflow for ECC. Use when the user wants to read texts or DMs, recover a recent one-time code, inspect a thread before replying, or prove which message source was actually checked."
version: 1.0.0
category: ecc
tags: "[messages-ops, evidence-first, live, messaging, workflow, ecc., user, wants]"
status: published
confidence: 0.8
source: imported
source_pack: ecc
source_repo: "https://github.com/affaan-m/ECC"
source_path: skills\messages-ops\SKILL.md
source_sha256: 662aa73e5b2b309a2fb8436d718ce0d7b65bba1046b4bf5abccc436659a0142b
unlimited_skills_adapter: odysseus-action-schema-v1
created: "2026-06-06T06:14:57Z"
---

## When to Use

- user says "read my messages", "check texts", "look in DMs", or "find the code"
- the task depends on a live thread or a recent code delivered to a local messaging surface
- the user wants proof of which source or thread was inspected

## When Not to Use

Not specified by the source skill.

## Required Context

Not specified by the source skill.

## Procedure

1. Read the preserved source skill body below.
2. Apply only the parts relevant to the current task.
3. Verify the result using the regression tests or project-specific checks.

## Tools

Not specified by the source skill.

## Expected Output

Not specified by the source skill.

## Known Traps

- do not blur mailbox work and DM/text work
- do not claim retrieval without naming the source
- do not burn time on broad searches when the ask is a recent-code lookup
- do not keep retrying a blocked auth path without surfacing the blocker

## Examples of Successful Execution

Not specified by the source skill.

## Regression Tests

- the response names the message source
- the response includes a sender, service, thread, or clear blocker
- the final state is explicit and bounded

## Original Skill Body

## Messages Ops

Use this when the task is live-message retrieval: iMessage, DMs, recent one-time codes, or thread inspection before a follow-up.

This is not email work. If the dominant surface is a mailbox, use `email-ops`.

## Skill Stack

Pull these ECC-native skills into the workflow when relevant:

- `email-ops` when the message task is really mailbox work
- `connections-optimizer` when the DM thread belongs to outbound network work
- `lead-intelligence` when the live thread should inform targeting or warm-path outreach
- `knowledge-ops` when the thread contents need to be captured into durable context

## Guardrails

- resolve the source first:
  - local messages
  - X / social DM
  - another browser-gated message surface
- do not claim a thread was checked without naming the source
- do not improvise raw database access if a checked helper or standard path exists
- if auth or MFA blocks the surface, report the exact blocker

## 1. Resolve the exact thread

Before doing anything else, settle:

- message surface
- sender / recipient / service
- time window
- whether the task is retrieval, inspection, or prep for a reply

## 2. Read before drafting

If the task may turn into an outbound follow-up:

- read the latest inbound
- identify the open loop
- then hand off to the correct outbound skill if needed

## 3. Handle codes as a focused retrieval task

For one-time codes:

- search the recent local message window first
- narrow by service or sender when possible
- stop once the code is found or the focused search is exhausted

## 4. Report exact evidence

Return:

- source used
- thread or sender when possible
- time window
- exact status:
  - read
  - code-found
  - blocked
  - awaiting reply draft

## Output Format

```text
SOURCE
- message surface
- sender / thread / service

RESULT
- message summary or code
- time window

STATUS
- read / code-found / blocked / awaiting reply draft
```
