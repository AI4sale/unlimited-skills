# Enterprise Skill Lock

Status: planned, not implemented yet.

Enterprise Skill Lock is a planned governance feature for businesses that need centralized control over which skills can be delivered to agent instances.

The goal is simple: when an unmanaged source tries to deliver new skills to a locked enterprise instance, the agent should refuse the delivery and direct the operator to the corporate administrator or approved enterprise update channel.

## Intended Behavior

A locked enterprise instance should:

- accept skills only from approved enterprise registries, signed packs, or policy-approved local sources;
- reject direct skill delivery from unmanaged users, scripts, repositories, or ad hoc archives;
- explain that the instance is under enterprise skill governance;
- tell the operator to request the skill through the corporate administrator;
- continue using already approved local skills;
- keep normal MIT-core local search/view/index behavior for approved local libraries.

Example refusal:

```text
This instance is managed by Enterprise Skill Lock.
I cannot install or load unmanaged skills directly.
Ask your corporate Unlimited Skills administrator to publish this skill through the approved enterprise registry or update channel.
```

## Why This Exists

Skills change agent behavior. For a business, uncontrolled skill delivery is a governance and supply-chain risk.

Enterprise Skill Lock is intended to help with:

- controlled rollouts;
- approved skill sources;
- auditability;
- separation between community, team, and enterprise skills;
- preventing accidental or malicious skill injection;
- enforcing business policy across many agent instances.

## Planned Policy Controls

- allowed registries;
- allowed pack signatures;
- required update channels;
- denied community submissions;
- denied local ad hoc installs;
- approved local library roots;
- admin override flow;
- audit event generation for rejected skill-delivery attempts.

## Open Implementation Questions

- How each supported agent surface can enforce the lock.
- Whether enforcement lives in the router skill, installer patch, local CLI, agent config, or all of them.
- How to prevent bypass when an agent can still read arbitrary files.
- How corporate administrators publish emergency exceptions.
- How to represent policy in a portable signed file.
