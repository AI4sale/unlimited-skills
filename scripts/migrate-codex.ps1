param(
  [string]$SourceRoot = (Join-Path $env:USERPROFILE ".codex\skills"),
  [string]$TargetRoot = (Join-Path $env:USERPROFILE ".unlimited-skills\library"),
  [switch]$Apply
)

$ErrorActionPreference = "Stop"

& (Join-Path $PSScriptRoot "lib\Migrate-Skills.ps1") `
  -SourceRoot $SourceRoot `
  -TargetRoot $TargetRoot `
  -Collection "codex" `
  -ExcludeNames @(".system", "unlimited-skills", "skill-library") `
  -Apply:$Apply
