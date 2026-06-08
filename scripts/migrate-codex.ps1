param(
  [string]$CodexHome = (Join-Path $env:USERPROFILE ".codex"),
  [string]$SourceRoot = (Join-Path $env:USERPROFILE ".codex\skills"),
  [string]$TargetRoot = "",
  [switch]$SkipExistingNames,
  [switch]$Apply
)

$ErrorActionPreference = "Stop"

if (-not $TargetRoot) {
  $TargetRoot = Join-Path $CodexHome ".unlimited-skills\library"
}

if (-not (Test-Path $SourceRoot)) {
  Write-Error "Source root not found: $SourceRoot"
  exit 1
}

$source = Resolve-Path $SourceRoot
$sourceFullPath = [System.IO.Path]::GetFullPath($source.Path).TrimEnd([System.IO.Path]::DirectorySeparatorChar, [System.IO.Path]::AltDirectorySeparatorChar)
$targetRootPath = [System.IO.Path]::GetFullPath($TargetRoot)
$targetSkills = Join-Path $targetRootPath "local\skills"
$targetDuplicates = Join-Path $targetRootPath "local\duplicates"
$manifestDir = Join-Path $targetRootPath "manifests"
$timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
$manifest = Join-Path $manifestDir "local-migration-$timestamp.json"
$excludedDirs = @("node_modules", ".git", ".venv", "__pycache__", ".chroma-skills", ".learning", "duplicates", ".pytest_cache", ".mypy_cache", ".ruff_cache")
$excludedNames = @("unlimited-skills", "skill-library")

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

$existingNames = @{}
if ($SkipExistingNames -and (Test-Path $targetRootPath)) {
  $localRootFullPath = [System.IO.Path]::GetFullPath((Join-Path $targetRootPath "local"))
  Get-ChildItem -LiteralPath $targetRootPath -Recurse -Filter "SKILL.md" -File |
    Where-Object {
      $skillPath = [System.IO.Path]::GetFullPath($_.FullName)
      -not $skillPath.StartsWith($localRootFullPath + [System.IO.Path]::DirectorySeparatorChar, [System.StringComparison]::OrdinalIgnoreCase)
    } |
    ForEach-Object {
      $existingName = Split-Path (Split-Path $_.FullName -Parent) -Leaf
      $existingNames[$existingName] = $true
    }
}

$items = @()
$duplicates = @()
Get-ChildItem -LiteralPath $source -Recurse -Filter "SKILL.md" -File | ForEach-Object {
  $parts = $_.FullName.Split([System.IO.Path]::DirectorySeparatorChar, [System.IO.Path]::AltDirectorySeparatorChar)
  if ($parts | Where-Object { $excludedDirs -contains $_ }) {
    return
  }
  $skillDir = Split-Path $_.FullName -Parent
  $name = Split-Path $skillDir -Leaf
  if ($excludedNames -contains $name) {
    return
  }
  $skillDirFullPath = [System.IO.Path]::GetFullPath($skillDir)
  if ($skillDirFullPath.StartsWith($sourceFullPath + [System.IO.Path]::DirectorySeparatorChar, [System.StringComparison]::OrdinalIgnoreCase)) {
    $relative = $skillDirFullPath.Substring($sourceFullPath.Length + 1)
  } else {
    $relative = Split-Path $skillDirFullPath -Leaf
  }
  $isDuplicate = $SkipExistingNames -and $existingNames.ContainsKey($name)
  $destination = Join-Path ($(if ($isDuplicate) { $targetDuplicates } else { $targetSkills })) $relative
  $row = [ordered]@{
    name = $name
    source = $skillDir
    destination = $destination
    relative = $relative
    duplicate = $isDuplicate
  }
  if ($isDuplicate) {
    $duplicates += $row
  } else {
    $items += $row
    $existingNames[$name] = $true
  }
}

if (-not $Apply) {
  Write-Host "Dry run. Add -Apply to copy skills."
  [ordered]@{ items = $items; duplicates = $duplicates } | ConvertTo-Json -Depth 8
  return
}

New-Item -ItemType Directory -Force -Path $targetSkills, $targetDuplicates, $manifestDir | Out-Null
foreach ($row in @($items + $duplicates)) {
  & $copyTree $row.source $row.destination
}

[ordered]@{
  collection = "local"
  source_root = $source.Path
  target_root = $targetRootPath
  migrated_at = (Get-Date).ToString("o")
  count = $items.Count
  duplicate_count = $duplicates.Count
  items = $items
  duplicates = $duplicates
} | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath $manifest -Encoding UTF8

Write-Host "Migrated $($items.Count) local skills to $targetSkills"
Write-Host "Moved $($duplicates.Count) duplicate skills to $targetDuplicates"
Write-Host "Manifest: $manifest"
