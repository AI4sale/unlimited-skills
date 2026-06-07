param(
  [string]$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path,
  [string]$ClaudeHome = (Join-Path $env:USERPROFILE ".claude"),
  [string]$ProjectRoot = (Get-Location).Path,
  [string]$InstallRoot = (Join-Path $env:USERPROFILE ".unlimited-skills"),
  [string]$Python = "python",
  [ValidateSet("default", "bundled", "adapt-installed")]
  [string]$Mode = "default",
  [string]$ClaudeFile = "",
  [switch]$NoClaudePatch,
  [switch]$NoProjectSkills,
  [switch]$SkipPipInstall,
  [switch]$SkipReindex,
  [switch]$VectorReindex,
  [switch]$Json
)

$ErrorActionPreference = "Stop"

$cliPython = $Python
$venv = Join-Path $InstallRoot ".venv"
$venvPython = Join-Path $venv "Scripts\python.exe"

if (-not $SkipPipInstall) {
  if (-not (Test-Path $venvPython)) {
    & $Python -m venv $venv
  }
  & $venvPython -m pip install --upgrade pip
  & $venvPython -m pip install -e "$RepoRoot[all]"
  $cliPython = $venvPython
} elseif (Test-Path $venvPython) {
  $cliPython = $venvPython
}

$env:PYTHONPATH = "$RepoRoot$([System.IO.Path]::PathSeparator)$env:PYTHONPATH"

$argsList = @(
  "-m", "unlimited_skills.installers.claude_code",
  "--repo-root", $RepoRoot,
  "--claude-home", $ClaudeHome,
  "--project-root", $ProjectRoot,
  "--install-root", $InstallRoot,
  "--mode", $Mode,
  "--python-executable", $cliPython
)

if ($ClaudeFile) { $argsList += @("--claude-file", $ClaudeFile) }
if ($NoClaudePatch) { $argsList += "--no-claude-patch" }
if ($NoProjectSkills) { $argsList += "--no-project-skills" }
if ($SkipReindex) { $argsList += "--skip-reindex" }
if ($VectorReindex) { $argsList += "--vector-reindex" }
if ($Json) { $argsList += "--json" }

& $cliPython @argsList
