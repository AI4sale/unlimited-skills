---
name: unlimited-skills
description: Primary gateway to the external Unlimited Skills library for Hermes. Use before tasks that may need a specialized workflow, checklist, domain procedure, ECC skill, or Superpowers skill not already loaded.
version: 0.1.0
source: https://github.com/AI4sale/unlimited-skills
---

# Unlimited Skills Router for Hermes

Unlimited Skills is an external skill memory and retrieval layer. It keeps large packs out of Hermes' visible skill directory and retrieves only the relevant `SKILL.md` when needed.

## When to Use

Use this router first when:

- the user asks what skills, abilities, workflows, procedures, agents, or checklists are available;
- the user names a skill that is not currently loaded;
- the task may benefit from specialized domain knowledge, a review checklist, a workflow, a tool procedure, or a regression-test recipe;
- the task is security, testing, debugging, frontend, backend, infrastructure, documentation, research, data, agent, or workflow related.

Do not conclude that a skill is missing just because it is absent from Hermes' visible skill list. Query Unlimited Skills first and report what the library returns.

## Installed Paths

Library root:

```text
{{UNLIMITED_SKILLS_LIBRARY_ROOT}}
```

Hermes launcher for bash, Git Bash, macOS, or Linux:

```bash
"{{HERMES_SH_LAUNCHER}}" search "<query>" --mode hybrid --limit 8
"{{HERMES_SH_LAUNCHER}}" view <skill-name>
```

Hermes launcher for Windows PowerShell:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File "{{HERMES_PS_LAUNCHER}}" search "<query>" --mode hybrid --limit 8
powershell -NoProfile -ExecutionPolicy Bypass -File "{{HERMES_PS_LAUNCHER}}" view <skill-name>
```

## Workflow

1. Build a short search query from the user's request, project stack, error text, framework names, and domain terms.
2. Run `search "<query>" --mode hybrid --limit 8` with the launcher above.
3. Pick a skill only when the result is concrete enough to change the work.
4. Run `view <skill-name>` and follow only the relevant instructions.
5. Record usage with `use <skill-name> --query "<query>" --task "<short task>"`.
6. If the selected skill was wrong or especially useful, record feedback with the `feedback` command.

For inventory-style questions such as "what skills do you have?", search broad task terms first, then summarize matching library skills. Do not paste every result or every skill body into the conversation. Treat the library as a retrieval layer, not as context that should always be loaded.

## Windows / Git Bash Safety Rules

Hermes on Windows commonly runs terminal commands through Git Bash/MSYS while Python may be Windows-native. Avoid these failure modes:

- Do not execute `scripts/unlimited-skills.sh` directly from Windows-native Python `subprocess` with `shell=False`; Windows will raise `OSError: [WinError 193] %1 is not a valid Win32 application` because `.sh` is not a Win32 executable. Use `terminal()`/Git Bash directly, or explicitly invoke `bash ".../unlimited-skills.sh" ...`.
- When a Bash command writes output that Windows Python will read, use an explicit Windows-style path such as `C:/Users/<user>/AppData/Local/Temp/skills.json`; do not rely on `/tmp/...`, which may resolve differently between MSYS Bash and Windows-native Python.
- When editing Git Bash launchers that invoke Windows-native Python, do not append an empty `:${PYTHONPATH:-}` segment to a Windows-style repo path. If `PYTHONPATH` is empty, `PYTHONPATH='C:/repo:'` may be treated as a literal path containing a trailing colon and make imports fail. Use an `if [[ -n "${PYTHONPATH:-}" ]]` branch instead.
- For JSON inventory processing, prefer a single shell pipeline that writes to a Windows path before Python parses it:

```bash
tmp="${LOCALAPPDATA//\\//}/Temp/unlimited-skills.json"
"{{HERMES_SH_LAUNCHER}}" list --limit 0 --json > "$tmp"
TMP_PATH="$tmp" python - <<'PY'
import json
import os
with open(os.environ["TMP_PATH"], encoding="utf-8") as f:
    data = json.load(f)
print(data["total"], len({s["name"] for s in data["skills"]}))
PY
```

## Common Commands

```bash
"{{HERMES_SH_LAUNCHER}}" list --limit 40
"{{HERMES_SH_LAUNCHER}}" list --filter "security review" --limit 20
"{{HERMES_SH_LAUNCHER}}" search "React component rerender performance" --mode hybrid --limit 8
"{{HERMES_SH_LAUNCHER}}" where security-review
"{{HERMES_SH_LAUNCHER}}" view security-review
"{{HERMES_SH_LAUNCHER}}" use security-review --query "security review" --task "Review code for security issues"
"{{HERMES_SH_LAUNCHER}}" feedback security-review --query "security review" --verdict accepted --notes "Matched the task"
```
