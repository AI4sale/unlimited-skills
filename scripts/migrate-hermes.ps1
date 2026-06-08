param(
  [string]$SourceRoot = (Join-Path $env:USERPROFILE ".hermes\skills"),
  [string]$TargetRoot = (Join-Path $env:USERPROFILE ".unlimited-skills\library"),
  [switch]$Apply
)

$ErrorActionPreference = "Stop"

if (-not (Test-Path $SourceRoot)) {
  Write-Error "Source root not found: $SourceRoot"
  exit 1
}

$source = Resolve-Path $SourceRoot
$sourceFullPath = [System.IO.Path]::GetFullPath($source.Path).TrimEnd([System.IO.Path]::DirectorySeparatorChar, [System.IO.Path]::AltDirectorySeparatorChar)
$targetSkills = Join-Path ([System.IO.Path]::GetFullPath($TargetRoot)) "local\hermes\skills"
$excludedDirs = @("node_modules", ".git", ".venv", "__pycache__", ".chroma-skills", ".learning", "duplicates", ".pytest_cache", ".mypy_cache", ".ruff_cache")
$excludedNames = @("unlimited-skills", "skill-library")
$items = @()

Get-ChildItem -LiteralPath $source -Recurse -Filter "SKILL.md" -File | ForEach-Object {
  $parts = $_.FullName.Split([System.IO.Path]::DirectorySeparatorChar, [System.IO.Path]::AltDirectorySeparatorChar)
  if ($parts | Where-Object { $excludedDirs -contains $_ }) { return }
  $skillDir = Split-Path $_.FullName -Parent
  $name = Split-Path $skillDir -Leaf
  if ($excludedNames -contains $name) { return }
  $skillDirFullPath = [System.IO.Path]::GetFullPath($skillDir)
  $relative = if ($skillDirFullPath.StartsWith($sourceFullPath + [System.IO.Path]::DirectorySeparatorChar, [System.StringComparison]::OrdinalIgnoreCase)) {
    $skillDirFullPath.Substring($sourceFullPath.Length + 1)
  } else {
    Split-Path $skillDirFullPath -Leaf
  }
  $items += [ordered]@{
    name = $name
    source = $skillDir
    destination = Join-Path $targetSkills $relative
    relative = $relative
  }
}

if (-not $Apply) {
  Write-Host "Dry run. Add -Apply to copy skills."
  $items | ConvertTo-Json -Depth 6
  return
}

New-Item -ItemType Directory -Force -Path $targetSkills | Out-Null
foreach ($row in $items) {
  New-Item -ItemType Directory -Force -Path $row.destination | Out-Null
  Get-ChildItem -LiteralPath $row.source -Force | ForEach-Object {
    Copy-Item -LiteralPath $_.FullName -Destination $row.destination -Recurse -Force
  }
}

Write-Host "Migrated $($items.Count) Hermes skills to $targetSkills"
