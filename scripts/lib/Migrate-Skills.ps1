param(
  [Parameter(Mandatory = $true)]
  [string]$SourceRoot,

  [Parameter(Mandatory = $true)]
  [string]$TargetRoot,

  [Parameter(Mandatory = $true)]
  [string]$Collection,

  [string[]]$ExcludeNames = @(),
  [switch]$SkipExistingNames,
  [switch]$Apply
)

$ErrorActionPreference = "Stop"

if (-not (Test-Path $SourceRoot)) {
  Write-Host "Source root not found: $SourceRoot"
  return
}

$source = Resolve-Path $SourceRoot
$targetRootPath = [System.IO.Path]::GetFullPath($TargetRoot)
$targetCollection = Join-Path $targetRootPath $Collection
$targetSkills = Join-Path $targetCollection "skills"
$manifestDir = Join-Path $targetRootPath "manifests"
$timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
$manifest = Join-Path $manifestDir "$Collection-migration-$timestamp.json"
$excludedDirs = @("node_modules", ".git", ".venv", "__pycache__", ".chroma-skills", ".learning", ".pytest_cache", ".mypy_cache", ".ruff_cache")
$existingNames = @{}
if ($SkipExistingNames -and (Test-Path $targetRootPath)) {
  Get-ChildItem -LiteralPath $targetRootPath -Recurse -Filter "SKILL.md" -File |
    ForEach-Object {
      $existingName = Split-Path (Split-Path $_.FullName -Parent) -Leaf
      $existingNames[$existingName] = $true
    }
}

$skillFiles = Get-ChildItem -LiteralPath $source -Recurse -Filter "SKILL.md" -File
$items = @()

foreach ($file in $skillFiles) {
  $parts = $file.FullName.Split([System.IO.Path]::DirectorySeparatorChar, [System.IO.Path]::AltDirectorySeparatorChar)
  if ($parts | Where-Object { $excludedDirs -contains $_ }) {
    continue
  }
  $skillDir = Split-Path $file.FullName -Parent
  $name = Split-Path $skillDir -Leaf
  if ($ExcludeNames -contains $name) {
    continue
  }
  if ($SkipExistingNames -and $existingNames.ContainsKey($name)) {
    continue
  }
  $relative = Resolve-Path -LiteralPath $skillDir -Relative
  $destination = Join-Path $targetSkills $name
  $items += [ordered]@{
    name = $name
    source = $skillDir
    destination = $destination
    relative = $relative
  }
}

if (-not $Apply) {
  Write-Host "Dry run. Add -Apply to copy skills."
  $items | ConvertTo-Json -Depth 5
  return
}

New-Item -ItemType Directory -Force -Path $targetSkills, $manifestDir | Out-Null

foreach ($item in $items) {
  if (Test-Path $item.destination) {
    Remove-Item -LiteralPath $item.destination -Recurse -Force
  }
  Copy-Item -LiteralPath $item.source -Destination $item.destination -Recurse
  Get-ChildItem -LiteralPath $item.destination -Recurse -Directory -Force |
    Where-Object { $excludedDirs -contains $_.Name } |
    ForEach-Object { Remove-Item -LiteralPath $_.FullName -Recurse -Force }
}

[ordered]@{
  collection = $Collection
  source_root = $source.Path
  target_root = $targetRootPath
  migrated_at = (Get-Date).ToString("o")
  count = $items.Count
  items = $items
} | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath $manifest -Encoding UTF8

Write-Host "Migrated $($items.Count) skills to $targetSkills"
Write-Host "Manifest: $manifest"
