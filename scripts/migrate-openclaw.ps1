param(
  [string]$SourceRoot = (Join-Path $env:USERPROFILE ".openclaw\skills"),
  [string]$TargetRoot = (Join-Path $env:USERPROFILE ".unlimited-skills\library"),
  [switch]$Apply
)

$ErrorActionPreference = "Stop"

& (Join-Path $PSScriptRoot "lib\Migrate-Skills.ps1") `
  -SourceRoot $SourceRoot `
  -TargetRoot $TargetRoot `
  -Collection "openclaw" `
  -Apply:$Apply
