param(
  [string]$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path,
  [string]$CodexHome = (Join-Path $env:USERPROFILE ".codex"),
  [string]$InstallRoot = "",
  [string]$Python = "python",
  [ValidateSet("default", "bundled", "adapt-installed")]
  [string]$Mode = "default",
  [string]$AgentsFile = "",
  [switch]$NoAgentsPatch,
  [switch]$SkipPipInstall,
  [switch]$RemoteFirst,
  [switch]$NoRemote,
  [string]$RemoteHubUrl = "",
  [string]$HubTokenEnv = "",
  [string]$HubToken = "",
  [ValidateSet("local_allowed", "hub_required")]
  [string]$RemoteFallback = "local_allowed"
)

$ErrorActionPreference = "Stop"

if (-not $InstallRoot) {
  $InstallRoot = Join-Path $CodexHome ".unlimited-skills"
}

$skillSource = Join-Path $RepoRoot "skills\skill-router"
$skillTarget = Join-Path $CodexHome "skills\unlimited-skills"

if (-not (Test-Path $skillSource)) {
  throw "Router skill not found: $skillSource"
}

New-Item -ItemType Directory -Force -Path (Split-Path $skillTarget -Parent) | Out-Null
New-Item -ItemType Directory -Force -Path $skillTarget | Out-Null
Get-ChildItem -LiteralPath $skillSource -Force | ForEach-Object {
  Copy-Item -LiteralPath $_.FullName -Destination $skillTarget -Recurse -Force
}

$venv = Join-Path $InstallRoot ".venv"
$venvPython = Join-Path $venv "Scripts\python.exe"
$libraryRoot = Join-Path $InstallRoot "library"

if (-not $SkipPipInstall) {
  if (-not (Test-Path $venvPython)) {
    & $Python -m venv $venv
  }
  & $venvPython -m pip install --upgrade pip
  & $venvPython -m pip install -e "$RepoRoot[all]"
}

$cliPython = if (Test-Path $venvPython) { $venvPython } else { $Python }
& $cliPython -I -c "import unlimited_skills" 2>$null
if ($LASTEXITCODE -ne 0) {
  $env:PYTHONPATH = "$RepoRoot;$env:PYTHONPATH"
}
$remoteEnabled = (-not $NoRemote) -and ($RemoteFirst -or $RemoteHubUrl -or $HubTokenEnv -or $HubToken)
if ($NoRemote -and ($RemoteFirst -or $RemoteHubUrl -or $HubTokenEnv -or $HubToken)) {
  throw "-NoRemote cannot be combined with remote hub options."
}
if ($remoteEnabled -and -not $RemoteHubUrl) {
  throw "-RemoteHubUrl is required when remote-first mode is enabled."
}
if ($remoteEnabled -and $HubTokenEnv -and $HubToken) {
  throw "Use either -HubTokenEnv or -HubToken, not both."
}
if ($remoteEnabled -and -not ($HubTokenEnv -or $HubToken)) {
  throw "Remote-first mode requires -HubTokenEnv or -HubToken."
}

$launcher = Join-Path $skillTarget "scripts\unlimited-skills.ps1"
New-Item -ItemType Directory -Force -Path (Split-Path $launcher -Parent) | Out-Null
@"
param(
  [Parameter(ValueFromRemainingArguments = `$true)]
  [string[]]`$Args
)

`$ErrorActionPreference = "Stop"
# unlimited-skills-launcher: 1 (powershell-installed)
# Runs the INSTALLED unlimited_skills package; only a source/editable checkout
# that is not importable from this interpreter falls back to PYTHONPATH=<repo>.
& "$cliPython" -I -c "import unlimited_skills" 2>`$null
if (`$LASTEXITCODE -ne 0) {
  `$env:PYTHONPATH = "$RepoRoot" + [System.IO.Path]::PathSeparator + `$env:PYTHONPATH
}
`$env:UNLIMITED_SKILLS_HOME = "$InstallRoot"
`$env:UNLIMITED_SKILLS_ROOT = "$libraryRoot"
& "$cliPython" -m unlimited_skills --root "$libraryRoot" @Args
"@ | Set-Content -LiteralPath $launcher -Encoding UTF8

$skillFile = Join-Path $skillTarget "SKILL.md"
$remoteBlock = ""
if ($remoteEnabled) {
  $env:UNLIMITED_SKILLS_HOME = $InstallRoot
  $remoteArgs = @("--root", $libraryRoot, "remote", "configure", "--url", $RemoteHubUrl, "--fallback", $RemoteFallback)
  if ($HubTokenEnv) {
    $remoteArgs += @("--token-env", $HubTokenEnv)
    $tokenSource = "env:$HubTokenEnv"
  } else {
    $remoteArgs += @("--token", $HubToken)
    $tokenSource = "private remote.json"
  }
  & $cliPython -m unlimited_skills.cli @remoteArgs | Out-Null
  $remoteBlock = @"
## Remote-First Local Skill Hub Mode

This install is configured for remote-first skill routing through Local Skill Hub.

- Hub URL: ``$RemoteHubUrl``
- Token source: ``$tokenSource``
- Fallback policy: ``$RemoteFallback``

Before local ``search``/``view``, prefer remote resolution:

````powershell
powershell -NoProfile -ExecutionPolicy Bypass -File "$launcher" remote resolve "<task or skill name>" --agent codex --max-skills 2 --max-chars 12000
````

Use only the selected skill bodies returned by the hub. If a selected skill is metadata-only or requires a local install plan, surface the missing capability warning instead of pretending the skill is ready.

Never print, paste, or store the raw hub token in visible router files, prompts, or logs.

"@
}
if (Test-Path $skillFile) {
  $skillText = Get-Content -LiteralPath $skillFile -Raw
  $skillText = $skillText.Replace("{{REMOTE_HUB_ROUTER_BLOCK}}", $remoteBlock.TrimEnd())
  Set-Content -LiteralPath $skillFile -Value $skillText -Encoding UTF8
}

if (-not $NoAgentsPatch) {
  $agentsTarget = if ($AgentsFile) { $AgentsFile } else { Join-Path $CodexHome "AGENTS.md" }
  $agentsPath = [System.IO.Path]::GetFullPath($agentsTarget)
  $agentsDir = Split-Path $agentsPath -Parent
  if ($agentsDir) {
    New-Item -ItemType Directory -Force -Path $agentsDir | Out-Null
  }
  $agentsBlock = @'
<!-- BEGIN UNLIMITED SKILLS -->
## Unlimited Skills Library

A generated inventory of proven skills (checklists, workflows, regression recipes) that is deliberately NOT in the visible skill list. A 1-second lookup often replaces 20 minutes of rediscovery because the library has shipped-and-tested procedures for recurring tasks.

RUN this single command BEFORE starting every substantive work phase that matches a trigger below. It costs ~1 second and returns at most one compact card, one name hint, or nothing:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File "{LAUNCHER}" suggest "<3-8 keyword phase summary>" --json --card --limit 1
```

TRIGGERS (any one suffices):

- writing or reviewing code in a named language/framework (React, Python, Go, n8n, ...)
- review, audit, or security check of any artifact
- writing tests, fixing a bug, or debugging a failure
- git/GitHub workflows: branches, PRs, releases, changelogs
- writing prose: docs, posts, outreach, marketing, research reports
- planning, refactoring, migrations, deployments, ops procedures
- the user names a skill, workflow, or asks "what can you do"

PHASE FRESHNESS: a `suggest` result is fresh only for the current substantive phase. Re-query at phase boundaries such as planning -> implementation, backend/API -> frontend/UI, implementation -> testing, testing -> debugging, implementation -> security review, code -> docs, or docs -> release/git workflow. A no-hit result is also scoped only to the current phase.

ACT on the result: if a suggestion looks relevant, run `view <skill-name>` with the same launcher and follow it. If `suggest` returns nothing, proceed with the current phase; do not search again with synonyms for that same phase. Anti-spam: at most one `suggest` probe per phase unless the user explicitly asks for a broader search. For deeper retrieval use `search "<query>" --mode hybrid --limit 8`; for inventory questions use `list --limit 80`.

TIER BEHAVIOR: silence means no confident match; a name hint means inspect that skill if it looks relevant; a compact card means a high-confidence match for this phase.

SKIP only when a relevant skill is already active in the current context.
<!-- END UNLIMITED SKILLS -->
'@.Replace("{LAUNCHER}", $launcher)
  $env:AGENTS_BLOCK = $agentsBlock
  & $cliPython -m unlimited_skills.agents_patch $agentsPath
  if ($LASTEXITCODE -ne 0) {
    throw "Failed to patch AGENTS.md: $agentsPath"
  }
  Remove-Item Env:\AGENTS_BLOCK -ErrorAction SilentlyContinue
}

$migrate = Join-Path $RepoRoot "scripts\lib\Migrate-Skills.ps1"
$migrateCodex = Join-Path $RepoRoot "scripts\migrate-codex.ps1"

if ($Mode -eq "bundled") {
  foreach ($pack in @("ecc", "superpowers")) {
    $packRoot = Join-Path $RepoRoot "packs\$pack\skills"
    if (Test-Path $packRoot) {
      & $migrate -SourceRoot $packRoot -TargetRoot $libraryRoot -Collection $pack -Apply
    }
  }
}

if (Test-Path (Join-Path $CodexHome "skills")) {
  & $migrateCodex `
    -SourceRoot (Join-Path $CodexHome "skills") `
    -TargetRoot $libraryRoot `
    -SkipExistingNames `
    -Apply
}

if ($Mode -eq "adapt-installed") {
  & $cliPython -m unlimited_skills.cli --root $libraryRoot adapt --collection local --source-pack local
}

& $cliPython -m unlimited_skills.cli --root $libraryRoot reindex

Write-Host "Installed Codex router skill: $skillTarget"
Write-Host "Installed Unlimited Skills venv: $venv"
Write-Host "Install mode: $Mode"
Write-Host "Library root: $libraryRoot"
Write-Host "Launcher: $launcher"
if ($remoteEnabled) {
  Write-Host "Remote-first hub: enabled"
  Write-Host "Remote hub URL: $RemoteHubUrl"
  Write-Host "Remote fallback: $RemoteFallback"
  Write-Host "Remote token source: $tokenSource"
} else {
  Write-Host "Remote-first hub: disabled"
}
if ($AgentsFile) {
  Write-Host "Patched AGENTS.md: $AgentsFile"
} elseif (-not $NoAgentsPatch) {
  Write-Host "Patched AGENTS.md: $(Join-Path $CodexHome "AGENTS.md")"
} else {
  Write-Host "Skipped AGENTS.md patch."
}
Write-Host "Restart Codex so the router skill appears in the available skill list."
