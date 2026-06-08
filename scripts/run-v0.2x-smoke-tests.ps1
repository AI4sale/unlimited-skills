param(
  [string]$Python = "python",
  [string]$PytestArgs = ""
)

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = Split-Path -Parent $ScriptDir
Set-Location $RepoRoot

$argsList = @("scripts/run-v0.2x-smoke-tests.py")
if ($PytestArgs) {
  $argsList += @("--pytest-args", $PytestArgs)
}

& $Python @argsList
exit $LASTEXITCODE
