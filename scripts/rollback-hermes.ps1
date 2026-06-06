param(
  [string]$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path,
  [string]$Python = "python",
  [Parameter(Mandatory = $true)]
  [string]$Manifest,
  [switch]$Json,
  [switch]$Apply
)

$ErrorActionPreference = "Stop"
$env:PYTHONPATH = "$RepoRoot$([System.IO.Path]::PathSeparator)$env:PYTHONPATH"

$argsList = @("-m", "unlimited_skills.installers.hermes", "rollback", "--manifest", $Manifest)
if ($Apply) { $argsList += "--apply" }
if ($Json) { $argsList += "--json" }

& $Python @argsList
