param(
  [string]$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path,
  [string]$CodexHome = (Join-Path $env:USERPROFILE ".codex"),
  [string]$InstallRoot = (Join-Path $env:USERPROFILE ".unlimited-skills"),
  [string]$Python = "python",
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

if (-not $SkipPipInstall) {
  if (-not (Test-Path $venvPython)) {
    & $Python -m venv $venv
  }
  & $venvPython -m pip install --upgrade pip
  & $venvPython -m pip install -e "$RepoRoot[all]"
}

$launcher = Join-Path $skillTarget "scripts\unlimited-skills.ps1"
New-Item -ItemType Directory -Force -Path (Split-Path $launcher -Parent) | Out-Null
@"
param(
  [Parameter(ValueFromRemainingArguments = `$true)]
  [string[]]`$Args
)

`$ErrorActionPreference = "Stop"
& "$venvPython" -m unlimited_skills.cli @Args
"@ | Set-Content -LiteralPath $launcher -Encoding UTF8

Write-Host "Installed Codex router skill: $skillTarget"
Write-Host "Installed Unlimited Skills venv: $venv"
Write-Host "Launcher: $launcher"
Write-Host "Restart Codex so the router skill appears in the available skill list."
