param(
  [string]$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path,
  [string]$OpenClawHome = $(if ($env:OPENCLAW_HOME) { $env:OPENCLAW_HOME } else { Join-Path $env:USERPROFILE ".openclaw" }),
  [string]$WorkspaceRoot = $(if ($env:OPENCLAW_WORKSPACE) { $env:OPENCLAW_WORKSPACE } else { Join-Path $OpenClawHome "workspace" }),
  [string]$InstallRoot = (Join-Path $env:USERPROFILE ".unlimited-skills"),
  [string]$Python = "python",
  [ValidateSet("default", "bundled", "adapt-installed")]
  [string]$Mode = "default",
  [string]$AgentsFile = "",
  [switch]$NoAgentsPatch,
  [switch]$NoBuiltin,
  [switch]$NoPluginSkills,
  [switch]$SkipPipInstall,
  [switch]$SkipReindex,
  [switch]$VectorReindex,
  [switch]$RemoteFirst,
  [switch]$NoRemote,
  [string]$RemoteHubUrl = "",
  [string]$HubTokenEnv = "",
  [string]$HubToken = "",
  [ValidateSet("local_allowed", "hub_required")]
  [string]$RemoteFallback = "local_allowed",
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
  "-m", "unlimited_skills.installers.openclaw",
  "--repo-root", $RepoRoot,
  "--openclaw-home", $OpenClawHome,
  "--workspace-root", $WorkspaceRoot,
  "--install-root", $InstallRoot,
  "--mode", $Mode,
  "--python-executable", $cliPython
)

if ($AgentsFile) { $argsList += @("--agents-file", $AgentsFile) }
if ($NoAgentsPatch) { $argsList += "--no-agents-patch" }
if ($NoBuiltin) { $argsList += "--no-builtin" }
if ($NoPluginSkills) { $argsList += "--no-plugin-skills" }
if ($SkipReindex) { $argsList += "--skip-reindex" }
if ($VectorReindex) { $argsList += "--vector-reindex" }
if ($RemoteFirst) { $argsList += "--remote-first" }
if ($NoRemote) { $argsList += "--no-remote" }
if ($RemoteHubUrl) { $argsList += @("--remote-hub-url", $RemoteHubUrl) }
if ($HubTokenEnv) { $argsList += @("--hub-token-env", $HubTokenEnv) }
if ($HubToken) { $argsList += @("--hub-token", $HubToken) }
if ($RemoteFallback) { $argsList += @("--remote-fallback", $RemoteFallback) }
if ($Json) { $argsList += "--json" }

& $cliPython @argsList
