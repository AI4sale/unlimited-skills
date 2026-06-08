param(
  [Parameter(Mandatory = $true)]
  [string]$SourceRoot,

  [Parameter(Mandatory = $true)]
  [string]$TargetRoot,

  [Parameter(Mandatory = $true)]
  [string]$Collection,

  [string[]]$ExcludeNames = @(),
  [switch]$SkipExistingNames,
  [switch]$AllowNodeModules,
  [switch]$Apply
)

$ErrorActionPreference = "Stop"

if (-not (Test-Path $SourceRoot)) {
  Write-Error "Source root not found: $SourceRoot"
  exit 1
}

$source = Resolve-Path $SourceRoot
$targetRootPath = [System.IO.Path]::GetFullPath($TargetRoot)
$targetCollection = Join-Path (Join-Path $targetRootPath "registry") $Collection
$targetSkills = Join-Path $targetCollection "skills"
$manifestDir = Join-Path $targetRootPath "manifests"
$timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
$manifest = Join-Path $manifestDir "$Collection-migration-$timestamp.json"
$excludedDirs = @("node_modules", ".git", ".venv", "__pycache__", ".chroma-skills", ".learning", ".pytest_cache", ".mypy_cache", ".ruff_cache")
if ($AllowNodeModules) {
  $excludedDirs = $excludedDirs | Where-Object { $_ -ne "node_modules" }
}
$existingNames = @{}
if ($SkipExistingNames -and (Test-Path $targetRootPath)) {
  $targetSkillsFullPath = [System.IO.Path]::GetFullPath($targetSkills)
  Get-ChildItem -LiteralPath $targetRootPath -Recurse -Filter "SKILL.md" -File |
    Where-Object {
      $skillPath = [System.IO.Path]::GetFullPath($_.FullName)
      -not $skillPath.StartsWith($targetSkillsFullPath + [System.IO.Path]::DirectorySeparatorChar, [System.StringComparison]::OrdinalIgnoreCase)
    } |
    ForEach-Object {
      $existingName = Split-Path (Split-Path $_.FullName -Parent) -Leaf
      $existingNames[$existingName] = $true
    }
}

$copyTree = {
  param(
    [string]$SourceDir,
    [string]$DestinationDir
  )

  New-Item -ItemType Directory -Force -Path $DestinationDir | Out-Null
  Get-ChildItem -LiteralPath $SourceDir -Force | ForEach-Object {
    if ($_.PSIsContainer -and ($excludedDirs -contains $_.Name)) {
      return
    }

    $destinationPath = Join-Path $DestinationDir $_.Name
    if ($_.PSIsContainer) {
      & $copyTree $_.FullName $destinationPath
    } else {
      Copy-Item -LiteralPath $_.FullName -Destination $destinationPath -Force
    }
  }
}

$skillFiles = Get-ChildItem -LiteralPath $source -Recurse -Filter "SKILL.md" -File
$items = @()

foreach ($file in $skillFiles) {
  $parts = $file.FullName.Split([System.IO.Path]::DirectorySeparatorChar, [System.IO.Path]::AltDirectorySeparatorChar)
  if ($parts | Where-Object { $excludedDirs -contains $_ }) {
    continue
  }
  if ($parts | Where-Object { $ExcludeNames -contains $_ }) {
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
  & $copyTree $item.source $item.destination
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
