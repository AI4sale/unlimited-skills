param(
  [string]$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path,
  [string]$HermesHome = $(if ($env:HERMES_HOME) { $env:HERMES_HOME } else { Join-Path $env:USERPROFILE ".hermes" }),
  [string]$InstallRoot = (Join-Path $env:USERPROFILE ".unlimited-skills"),
  [string]$Python = "python",
  [ValidateSet("router-only", "evacuate-visible-skills")]
  [string]$Mode = "router-only",
  [switch]$SkipPipInstall,
  [switch]$SkipReindex,
  [switch]$Json,
  [switch]$Apply
)

$ErrorActionPreference = "Stop"

$cliPython = $Python
$venv = Join-Path $InstallRoot ".venv"
$venvPython = Join-Path $venv "Scripts\python.exe"

if ($Apply -and -not $SkipPipInstall) {
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
  "-m", "unlimited_skills.installers.hermes", "install",
  "--repo-root", $RepoRoot,
  "--hermes-home", $HermesHome,
  "--install-root", $InstallRoot,
  "--mode", $Mode,
  "--python-executable", $cliPython
)

if ($Apply) { $argsList += "--apply" }
if ($SkipReindex) { $argsList += "--skip-reindex" }
if ($Json) { $argsList += "--json" }

& $cliPython @argsList
