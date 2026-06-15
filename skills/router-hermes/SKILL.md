---
name: unlimited-skills
description: Primary gateway to the external Unlimited Skills library for Hermes. Use before substantive work whenever a relevant skill is not already active, including writing, coding, review, debugging, research, docs, operations, planning, design, or tasks that may need an ECC, Superpowers, or Hermes skill not already loaded.
version: 0.1.0
source: https://github.com/AI4sale/unlimited-skills
---

# Unlimited Skills Router for Hermes

Unlimited Skills is an external skill memory and retrieval layer. It keeps large packs out of Hermes' visible skill directory and retrieves only the relevant `SKILL.md` when needed.

## When to Use

RUN the single `suggest` command BEFORE starting every substantive work phase that matches a trigger below. It costs ~1 second and returns at most one compact card, one name hint, or nothing. A 1-second lookup often replaces 20 minutes of rediscovery.

TRIGGERS (any one suffices):

- writing or reviewing code in a named language/framework (React, Python, Go, n8n, ...)
- review, audit, or security check of any artifact
- writing tests, fixing a bug, or debugging a failure
- git/GitHub workflows: branches, PRs, releases, changelogs
- writing prose: docs, posts, outreach, marketing, research reports
- planning, refactoring, migrations, deployments, ops procedures
- the user names a skill, workflow, or asks "what can you do"

MULTILINGUAL — if you have ever worked with this user in a language other than English, prefer the multilingual vector path: build the embedding sidecar with `unlimited-skills vector-reindex` and keep it warm via the daemon `unlimited-skills serve`. Lexical search scores non-English prompts at zero, so without the sidecar (and a warm model) a native-language query returns nothing.

SKIP only when a relevant skill is already active in the current context. Do not conclude that a skill is missing just because it is absent from Hermes' visible skill list — query the library first and report what it returns.

## Installed Paths

Library root:

```text
{{UNLIMITED_SKILLS_LIBRARY_ROOT}}
```

Hermes launcher for bash, Git Bash, macOS, or Linux:

```bash
"{{HERMES_SH_LAUNCHER}}" suggest "<3-8 keyword phase summary>" --json --card --limit 1
"{{HERMES_SH_LAUNCHER}}" view <skill-name>
```

Hermes launcher for Windows PowerShell:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File "{{HERMES_PS_LAUNCHER}}" suggest "<3-8 keyword phase summary>" --json --card --limit 1
powershell -NoProfile -ExecutionPolicy Bypass -File "{{HERMES_PS_LAUNCHER}}" view <skill-name>
```

## Workflow

Phase freshness: a `suggest` result is fresh only for the current substantive phase. Re-query at phase boundaries such as planning -> implementation, backend/API -> frontend/UI, implementation -> testing, testing -> debugging, implementation -> security review, code -> docs, or docs -> release/git workflow. A no-hit result is also scoped only to the current phase.

Anti-spam: do not re-query inside the same phase for trivially similar wording. Bound lookups to at most one `suggest` probe per phase unless the user explicitly asks for a broader search.

Tier behavior: silence means no confident match; a name hint means inspect that skill if it looks relevant; a compact card means a high-confidence match was found for this phase.

1. Run `suggest "<3-8 keyword phase summary>" --json --card --limit 1` with the launcher above.
2. If a suggestion looks relevant, run `view <skill-name>` and follow only the relevant instructions.
3. If `suggest` returns nothing, proceed with the current phase; do not search again with synonyms for that same phase. For unusual or high-stakes tasks you may escalate once to `search "<query>" --mode hybrid --limit 8`.
4. If the user asks what skills are available, run `list --limit 80` and summarize the relevant collections or names.
5. If the user names a specific skill, run `where <skill-name>` or `view <skill-name>` before saying it is unavailable.
6. Optionally enrich the learning loop with `use <skill-name> --query "<query>" --task "<short task>"` and the `feedback` command — helpful, never required.

{{REMOTE_HUB_ROUTER_BLOCK}}

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

## Hosted Registration / Community Access

Local Community Core usage does not require registration: `search`, `list`, `view`, `where`, `use`, `feedback`, local indexing, and bundled/local packs continue to work offline.

Hosted services require registration: hosted adapted-skill catalog, `community-skills` catalog/submissions, adapted collection updates, registered local enhancement scripts, team sync, and future dashboard/cloud/marketplace features.

Current community registration is self-service and does not require an invite key. Use:

```bash
"{{HERMES_SH_LAUNCHER}}" register --agent hermes
"{{HERMES_SH_LAUNCHER}}" license status
```

Registration creates a random install id plus an Ed25519 device key, sends only the public key and key thumbprint to the registry, and stores the returned hosted-service token plus device private key in `~/.unlimited-skills/registration.json`. Treat that file like a credential. Telemetry remains off unless `--telemetry` is explicitly passed.

After registering, verify hosted access with:

```bash
"{{HERMES_SH_LAUNCHER}}" catalog list
"{{HERMES_SH_LAUNCHER}}" updates check
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
