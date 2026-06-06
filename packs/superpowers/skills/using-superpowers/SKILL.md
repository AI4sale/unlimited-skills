---
name: using-superpowers
description: Bootstrap Superpowers skill usage by checking for applicable skills before acting in a conversation.
version: 1.0.0
category: skills
tags: "[skills, routing, superpowers, bootstrap, policy]"
status: published
confidence: 0.8
source: imported
source_pack: superpowers
source_repo: "https://github.com/obra/superpowers"
source_path: skills\using-superpowers\SKILL.md
source_sha256: 316e29381219adf0cac62190c67aeabf427d6e6e5f2735541d502b3d339be7aa
unlimited_skills_adapter: odysseus-action-schema-v1
created: "2026-06-06T06:15:16Z"
unlimited_skills_agent_adapter: action-schema-agent-v1
---

## When to Use

Use at the start of a conversation or task when Superpowers skills are installed and the agent needs to decide whether a skill applies before responding or asking clarifying questions.

## When Not to Use

Do not use when running as a dispatched subagent with a specific delegated task that explicitly says to skip this bootstrap. Do not let this override direct user instructions or higher-priority project instructions.

## Required Context

Current user request, available skill index or skill search tool, user/project instructions, whether this is a subagent task, and whether Superpowers skills are enabled.

## Procedure

1. Check whether this is a subagent context that should skip the bootstrap.
2. Inspect the available skill index or search for likely skills before responding.
3. If a skill applies, load and follow it before doing the task.
4. If multiple skills apply, choose the one that controls the current phase of work.
5. Respect user and project instructions above Superpowers skill rules.
6. Continue with normal task execution after the relevant skill has been loaded.

## Tools

1. Skill search/list/view capability
2. Agent instruction context

## Expected Output

The agent either loads the relevant skill before acting or explicitly proceeds because no skill applies, while respecting user/project instruction priority.

## Known Traps

1. Responding before checking applicable skills.
2. Using a skill to override explicit user instructions.
3. Loading many skills instead of the phase-relevant one.
4. Applying bootstrap inside a subagent task that says to skip it.

## Examples of Successful Execution

1. At conversation start, the agent sees a debugging request, loads systematic-debugging, and follows it before proposing a fix.

## Regression Tests

1. The transcript shows skill lookup happened before task action.
2. Only relevant skills were loaded.
3. User/project instructions remained higher priority.
4. Subagent skip conditions were honored.

## Original Skill Body

<SUBAGENT-STOP>
If you were dispatched as a subagent to execute a specific task, skip this skill.
</SUBAGENT-STOP>

<EXTREMELY-IMPORTANT>
If you think there is even a 1% chance a skill might apply to what you are doing, you ABSOLUTELY MUST invoke the skill.

IF A SKILL APPLIES TO YOUR TASK, YOU DO NOT HAVE A CHOICE. YOU MUST USE IT.

This is not negotiable. This is not optional. You cannot rationalize your way out of this.
</EXTREMELY-IMPORTANT>

## Instruction Priority

Superpowers skills override default system prompt behavior, but **user instructions always take precedence**:

1. **User's explicit instructions** (CLAUDE.md, GEMINI.md, AGENTS.md, direct requests) — highest priority
2. **Superpowers skills** — override default system behavior where they conflict
3. **Default system prompt** — lowest priority

If CLAUDE.md, GEMINI.md, or AGENTS.md says "don't use TDD" and a skill says "always use TDD," follow the user's instructions. The user is in control.

## How to Access Skills

**In Claude Code:** Use the `Skill` tool. When you invoke a skill, its content is loaded and presented to you—follow it directly. Never use the Read tool on skill files.

**In Copilot CLI:** Use the `skill` tool. Skills are auto-discovered from installed plugins. The `skill` tool works the same as Claude Code's `Skill` tool.

**In Gemini CLI:** Skills activate via the `activate_skill` tool. Gemini loads skill metadata at session start and activates the full content on demand.

**In other environments:** Check your platform's documentation for how skills are loaded.

## Platform Adaptation

Skills use Claude Code tool names. Non-CC platforms: see `references/copilot-tools.md` (Copilot CLI), `references/codex-tools.md` (Codex) for tool equivalents. Gemini CLI users get the tool mapping loaded automatically via GEMINI.md.

## The Rule

**Invoke relevant or requested skills BEFORE any response or action.** Even a 1% chance a skill might apply means that you should invoke the skill to check. If an invoked skill turns out to be wrong for the situation, you don't need to use it.

```dot
digraph skill_flow {
    "User message received" [shape=doublecircle];
    "About to EnterPlanMode?" [shape=doublecircle];
    "Already brainstormed?" [shape=diamond];
    "Invoke brainstorming skill" [shape=box];
    "Might any skill apply?" [shape=diamond];
    "Invoke Skill tool" [shape=box];
    "Announce: 'Using [skill] to [purpose]'" [shape=box];
    "Has checklist?" [shape=diamond];
    "Create TodoWrite todo per item" [shape=box];
    "Follow skill exactly" [shape=box];
    "Respond (including clarifications)" [shape=doublecircle];

    "About to EnterPlanMode?" -> "Already brainstormed?";
    "Already brainstormed?" -> "Invoke brainstorming skill" [label="no"];
    "Already brainstormed?" -> "Might any skill apply?" [label="yes"];
    "Invoke brainstorming skill" -> "Might any skill apply?";

    "User message received" -> "Might any skill apply?";
    "Might any skill apply?" -> "Invoke Skill tool" [label="yes, even 1%"];
    "Might any skill apply?" -> "Respond (including clarifications)" [label="definitely not"];
    "Invoke Skill tool" -> "Announce: 'Using [skill] to [purpose]'";
    "Announce: 'Using [skill] to [purpose]'" -> "Has checklist?";
    "Has checklist?" -> "Create TodoWrite todo per item" [label="yes"];
    "Has checklist?" -> "Follow skill exactly" [label="no"];
    "Create TodoWrite todo per item" -> "Follow skill exactly";
}
```

## Red Flags

These thoughts mean STOP—you're rationalizing:

| Thought | Reality |
|---------|---------|
| "This is just a simple question" | Questions are tasks. Check for skills. |
| "I need more context first" | Skill check comes BEFORE clarifying questions. |
| "Let me explore the codebase first" | Skills tell you HOW to explore. Check first. |
| "I can check git/files quickly" | Files lack conversation context. Check for skills. |
| "Let me gather information first" | Skills tell you HOW to gather information. |
| "This doesn't need a formal skill" | If a skill exists, use it. |
| "I remember this skill" | Skills evolve. Read current version. |
| "This doesn't count as a task" | Action = task. Check for skills. |
| "The skill is overkill" | Simple things become complex. Use it. |
| "I'll just do this one thing first" | Check BEFORE doing anything. |
| "This feels productive" | Undisciplined action wastes time. Skills prevent this. |
| "I know what that means" | Knowing the concept ≠ using the skill. Invoke it. |

## Skill Priority

When multiple skills could apply, use this order:

1. **Process skills first** (brainstorming, debugging) - these determine HOW to approach the task
2. **Implementation skills second** (frontend-design, mcp-builder) - these guide execution

"Let's build X" → brainstorming first, then implementation skills.
"Fix this bug" → debugging first, then domain-specific skills.

## Skill Types

**Rigid** (TDD, debugging): Follow exactly. Don't adapt away discipline.

**Flexible** (patterns): Adapt principles to context.

The skill itself tells you which.

## User Instructions

Instructions say WHAT, not HOW. "Add X" or "Fix Y" doesn't mean skip workflows.
