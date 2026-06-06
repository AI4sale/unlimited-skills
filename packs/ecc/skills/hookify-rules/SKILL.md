---
name: hookify-rules
description: "This skill should be used when the user asks to create a hookify rule, write a hook rule, configure hookify, add a hookify rule, or needs guidance on hookify rule syntax and patterns."
version: 1.0.0
category: ecc
tags: "[hookify-rules, this, should, used, user, asks, create, hookify]"
status: published
confidence: 0.8
source: imported
source_pack: ecc
source_repo: "https://github.com/affaan-m/ECC"
source_path: skills\hookify-rules\SKILL.md
source_sha256: b604608e30ac2b8f4f62dea3023efe2d3247b41a38c4156a6b6297173f2405a8
unlimited_skills_adapter: odysseus-action-schema-v1
created: "2026-06-06T06:14:56Z"
---

## When to Use

This skill should be used when the user asks to create a hookify rule, write a hook rule, configure hookify, add a hookify rule, or needs guidance on hookify rule syntax and patterns.

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

Not specified by the source skill.

## Examples of Successful Execution

Not specified by the source skill.

## Regression Tests

Not specified by the source skill.

## Original Skill Body

## Overview

Hookify rules are markdown files with YAML frontmatter that define patterns to watch for and messages to show when those patterns match. Rules are stored in `.claude/hookify.{rule-name}.local.md` files.

## Basic Structure

```markdown
---
name: rule-identifier
enabled: true
event: bash|file|stop|prompt|all
pattern: regex-pattern-here
---

Message to show Claude when this rule triggers.
Can include markdown formatting, warnings, suggestions, etc.
```

## Frontmatter Fields

| Field | Required | Values | Description |
|-------|----------|--------|-------------|
| name | Yes | kebab-case string | Unique identifier (verb-first: warn-*, block-*, require-*) |
| enabled | Yes | true/false | Toggle without deleting |
| event | Yes | bash/file/stop/prompt/all | Which hook event triggers this |
| action | No | warn/block | warn (default) shows message; block prevents operation |
| pattern | Yes* | regex string | Pattern to match (*or use conditions for complex rules) |

## Advanced Format (Multiple Conditions)

```markdown
---
name: warn-env-api-keys
enabled: true
event: file
conditions:
  - field: file_path
    operator: regex_match
    pattern: \.env$
  - field: new_text
    operator: contains
    pattern: API_KEY
---

You're adding an API key to a .env file. Ensure this file is in .gitignore!
```

**Condition fields by event:**
- bash: `command`
- file: `file_path`, `new_text`, `old_text`, `content`
- prompt: `user_prompt`

**Operators:** `regex_match`, `contains`, `equals`, `not_contains`, `starts_with`, `ends_with`

All conditions must match for rule to trigger.

## bash Events

Match Bash command patterns:
- Dangerous commands: `rm\s+-rf`, `dd\s+if=`, `mkfs`
- Privilege escalation: `sudo\s+`, `su\s+`
- Permission issues: `chmod\s+777`

## file Events

Match Edit/Write/MultiEdit operations:
- Debug code: `console\.log\(`, `debugger`
- Security risks: `eval\(`, `innerHTML\s*=`
- Sensitive files: `\.env$`, `credentials`, `\.pem$`

## stop Events

Completion checks and reminders. Pattern `.*` matches always.

## prompt Events

Match user prompt content for workflow enforcement.

## Regex Basics

- Escape special chars: `.` to `\.`, `(` to `\(`
- `\s` whitespace, `\d` digit, `\w` word char
- `+` one or more, `*` zero or more, `?` optional
- `|` OR operator

## Common Pitfalls

- **Too broad**: `log` matches "login", "dialog" — use `console\.log\(`
- **Too specific**: `rm -rf /tmp` — use `rm\s+-rf`
- **YAML escaping**: Use unquoted patterns; quoted strings need `\\s`

## Testing

```bash
python3 -c "import re; print(re.search(r'your_pattern', 'test text'))"
```

## File Organization

- **Location**: `.claude/` directory in project root
- **Naming**: `.claude/hookify.{descriptive-name}.local.md`
- **Gitignore**: Add `.claude/*.local.md` to `.gitignore`

## Commands

- `/hookify [description]` - Create new rules (auto-analyzes conversation if no args)
- `/hookify-list` - View all rules in table format
- `/hookify-configure` - Toggle rules on/off interactively
- `/hookify-help` - Full documentation

## Quick Reference

Minimum viable rule:
```markdown
---
name: my-rule
enabled: true
event: bash
pattern: dangerous_command
---
Warning message here
```
