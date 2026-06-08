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
$env:PYTHONPATH = "$RepoRoot;$env:PYTHONPATH"
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
`$env:PYTHONPATH = "$RepoRoot;`$env:PYTHONPATH"
`$env:UNLIMITED_SKILLS_HOME = "$InstallRoot"
`$env:UNLIMITED_SKILLS_ROOT = "$libraryRoot"
& "$cliPython" -m unlimited_skills.cli --root "$libraryRoot" @Args
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

Unlimited Skills is the external skill memory for this agent. Treat it as the first place to ask for task-specific skills, workflows, checklists, procedures, and regression recipes.

Before doing substantive work, check whether Unlimited Skills has a relevant skill. This includes writing, editing, coding, review, debugging, research, documentation, operations, planning, and design tasks. Skip this check only when a relevant skill is already active in the current context and it is clear why that skill applies.

Before saying a skill is unavailable, query the library:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File "{LAUNCHER}" search "<task or skill name>" --mode hybrid --limit 8
powershell -NoProfile -ExecutionPolicy Bypass -File "{LAUNCHER}" where <skill-name>
powershell -NoProfile -ExecutionPolicy Bypass -File "{LAUNCHER}" view <skill-name>
```

For inventory questions, query the library before answering:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File "{LAUNCHER}" list --limit 80
```

Do not rely only on `.agents/skills`, `.codex/skills`, or the visible skill list. The library may contain skills that are intentionally not loaded into context.
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
