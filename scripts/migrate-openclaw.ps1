param(
  [string]$SourceRoot = $(if ($env:OPENCLAW_WORKSPACE) { Join-Path $env:OPENCLAW_WORKSPACE "skills" } elseif ($env:OPENCLAW_HOME) { Join-Path $env:OPENCLAW_HOME "workspace\skills" } else { Join-Path $env:USERPROFILE ".openclaw\workspace\skills" }),
  [string]$TargetRoot = (Join-Path $env:USERPROFILE ".unlimited-skills\library"),
  [switch]$AllowNodeModules,
  [switch]$Apply
)

$ErrorActionPreference = "Stop"

& (Join-Path $PSScriptRoot "lib\Migrate-Skills.ps1") `
  -SourceRoot $SourceRoot `
  -TargetRoot $TargetRoot `
  -Collection "openclaw-workspace" `
  -AllowNodeModules:$AllowNodeModules `
  -Apply:$Apply
