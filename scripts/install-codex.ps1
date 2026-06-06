param(
  [string]$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path,
  [string]$CodexHome = (Join-Path $env:USERPROFILE ".codex"),
  [string]$InstallRoot = (Join-Path $env:USERPROFILE ".unlimited-skills"),
  [string]$Python = "python",
  [ValidateSet("default", "bundled", "adapt-installed")]
  [string]$Mode = "default",
  [string]$AgentsFile = "",
  [switch]$SkipPipInstall
)

$ErrorActionPreference = "Stop"

$skillSource = Join-Path $RepoRoot "skills\skill-router"
$skillTarget = Join-Path $CodexHome "skills\unlimited-skills"

if (-not (Test-Path $skillSource)) {
  throw "Router skill not found: $skillSource"
}

New-Item -ItemType Directory -Force -Path (Split-Path $skillTarget -Parent) | Out-Null
if (Test-Path $skillTarget) {
  Remove-Item -LiteralPath $skillTarget -Recurse -Force
}
Copy-Item -LiteralPath $skillSource -Destination $skillTarget -Recurse

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

$launcher = Join-Path $skillTarget "scripts\unlimited-skills.ps1"
New-Item -ItemType Directory -Force -Path (Split-Path $launcher -Parent) | Out-Null
@"
param(
  [Parameter(ValueFromRemainingArguments = `$true)]
  [string[]]`$Args
)

`$ErrorActionPreference = "Stop"
`$env:PYTHONPATH = "$RepoRoot;`$env:PYTHONPATH"
& "$cliPython" -m unlimited_skills.cli --root "$libraryRoot" @Args
"@ | Set-Content -LiteralPath $launcher -Encoding UTF8

if ($AgentsFile) {
  $agentsPath = [System.IO.Path]::GetFullPath($AgentsFile)
  $agentsDir = Split-Path $agentsPath -Parent
  if ($agentsDir) {
    New-Item -ItemType Directory -Force -Path $agentsDir | Out-Null
  }
  $agentsBlock = @'
<!-- BEGIN UNLIMITED SKILLS -->
## Unlimited Skills Library

Unlimited Skills is the external skill memory for this agent. Treat it as the first place to ask for task-specific skills, workflows, checklists, procedures, and regression recipes.

Before saying a skill is unavailable, query the library:

```powershell
& "{LAUNCHER}" search "<task or skill name>" --mode hybrid --limit 8
& "{LAUNCHER}" where <skill-name>
& "{LAUNCHER}" view <skill-name>
```

For inventory questions, query the library before answering:

```powershell
& "{LAUNCHER}" list --limit 80
```

Do not rely only on `.agents/skills`, `.codex/skills`, or the visible skill list. The library may contain skills that are intentionally not loaded into context.
<!-- END UNLIMITED SKILLS -->
'@.Replace("{LAUNCHER}", $launcher)
  $pattern = "(?s)<!-- BEGIN UNLIMITED SKILLS -->.*?<!-- END UNLIMITED SKILLS -->"
  $content = if (Test-Path $agentsPath) { Get-Content -LiteralPath $agentsPath -Raw } else { "" }
  if ([regex]::IsMatch($content, $pattern)) {
    $content = [regex]::Replace($content, $pattern, [System.Text.RegularExpressions.MatchEvaluator]{ param($m) $agentsBlock })
  } elseif ($content.Trim()) {
    $content = $content.TrimEnd() + "`n`n" + $agentsBlock + "`n"
  } else {
    $content = $agentsBlock + "`n"
  }
  Set-Content -LiteralPath $agentsPath -Value $content -Encoding UTF8
}

$migrate = Join-Path $RepoRoot "scripts\lib\Migrate-Skills.ps1"

if ($Mode -eq "bundled") {
  foreach ($pack in @("ecc", "superpowers")) {
    $packRoot = Join-Path $RepoRoot "packs\$pack\skills"
    if (Test-Path $packRoot) {
      & $migrate -SourceRoot $packRoot -TargetRoot $libraryRoot -Collection $pack -Apply
    }
  }
}

if (Test-Path (Join-Path $CodexHome "skills")) {
  & $migrate `
    -SourceRoot (Join-Path $CodexHome "skills") `
    -TargetRoot $libraryRoot `
    -Collection "codex" `
    -ExcludeNames @(".system", "unlimited-skills", "skill-library") `
    -SkipExistingNames:($Mode -eq "bundled") `
    -Apply
}

if ($Mode -eq "adapt-installed") {
  & $cliPython -m unlimited_skills.cli --root $libraryRoot adapt --collection codex --source-pack codex
}

& $cliPython -m unlimited_skills.cli --root $libraryRoot reindex

Write-Host "Installed Codex router skill: $skillTarget"
Write-Host "Installed Unlimited Skills venv: $venv"
Write-Host "Install mode: $Mode"
Write-Host "Library root: $libraryRoot"
Write-Host "Launcher: $launcher"
if ($AgentsFile) {
  Write-Host "Patched AGENTS.md: $AgentsFile"
}
Write-Host "Restart Codex so the router skill appears in the available skill list."
