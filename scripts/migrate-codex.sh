#!/usr/bin/env bash
set -euo pipefail

codex_home="${CODEX_HOME:-${HOME}/.codex}"
source_root="$codex_home/skills"
target_root="${UNLIMITED_SKILLS_ROOT:-}"
apply=0
skip_existing_names=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --source-root)
      source_root="$2"
      shift 2
      ;;
    --codex-home)
      codex_home="$2"
      shift 2
      ;;
    --target-root)
      target_root="$2"
      shift 2
      ;;
    --skip-existing-names)
      skip_existing_names=1
      shift
      ;;
    --apply)
      apply=1
      shift
      ;;
    *)
      echo "Unknown argument: $1" >&2
      exit 2
      ;;
  esac
done

if [[ -z "$target_root" ]]; then
  target_root="$codex_home/.unlimited-skills/library"
fi

if [[ ! -d "$source_root" ]]; then
  echo "Source root not found: $source_root" >&2
  exit 1
fi

source_root="$(cd -- "$source_root" && pwd)"
mkdir -p "$target_root"
target_root="$(cd -- "$target_root" && pwd)"
target_skills="$target_root/local/skills"
target_duplicates="$target_root/local/duplicates"
manifest_dir="$target_root/manifests"
timestamp="$(date +%Y%m%d-%H%M%S)"
manifest="$manifest_dir/local-migration-$timestamp.json"
excluded_dirs=("node_modules" ".git" ".venv" "__pycache__" ".chroma-skills" ".learning" "duplicates" ".pytest_cache" ".mypy_cache" ".ruff_cache")
excluded_names=("unlimited-skills" "skill-library")

contains_excluded_dir() {
  local path="$1"
  local excluded
  for excluded in "${excluded_dirs[@]}"; do
    [[ "$path" == *"/$excluded/"* || "$path" == *"/$excluded" ]] && return 0
  done
  return 1
}

is_excluded_name() {
  local name="$1"
  local excluded
  for excluded in "${excluded_names[@]}"; do
    [[ "$name" == "$excluded" ]] && return 0
  done
  return 1
}

copy_skill_tree() {
  local source_dir="$1"
  local destination_dir="$2"
  local tar_args=()
  local excluded

  mkdir -p "$destination_dir"
  for excluded in "${excluded_dirs[@]}"; do
    tar_args+=(--exclude="./$excluded" --exclude="*/$excluded")
  done
  tar -C "$source_dir" "${tar_args[@]}" -cf - . | tar -C "$destination_dir" -xf -
}

existing_names_file="$(mktemp)"
items_file="$(mktemp)"
duplicates_file="$(mktemp)"
trap 'rm -f "$existing_names_file" "$items_file" "$duplicates_file"' EXIT

if [[ "$skip_existing_names" -eq 1 && -d "$target_root" ]]; then
  while IFS= read -r -d '' existing_skill; do
    case "$existing_skill" in
      "$target_root/local/"*)
        continue
        ;;
    esac
    basename "$(dirname "$existing_skill")" >> "$existing_names_file"
  done < <(find "$target_root" -type f -name 'SKILL.md' -print0)
fi

while IFS= read -r -d '' skill_file; do
  if contains_excluded_dir "$skill_file"; then
    continue
  fi
  skill_dir="$(dirname "$skill_file")"
  name="$(basename "$skill_dir")"
  if is_excluded_name "$name"; then
    continue
  fi
  relative="${skill_dir#$source_root/}"
  if [[ "$skip_existing_names" -eq 1 ]] && grep -Fxq "$name" "$existing_names_file"; then
    printf '%s\t%s\t%s\t%s\n' "$name" "$skill_dir" "$target_duplicates/$relative" "$relative" >> "$duplicates_file"
    continue
  fi
  printf '%s\t%s\t%s\t%s\n' "$name" "$skill_dir" "$target_skills/$relative" "$relative" >> "$items_file"
  printf '%s\n' "$name" >> "$existing_names_file"
done < <(find "$source_root" -type f -name 'SKILL.md' -print0)

if [[ "$apply" -eq 0 ]]; then
  echo "Dry run. Add --apply to copy skills."
  cat "$items_file"
  echo "Duplicates:"
  cat "$duplicates_file"
  exit 0
fi

mkdir -p "$target_skills" "$target_duplicates" "$manifest_dir"
while IFS=$'\t' read -r name skill_dir destination relative; do
  [[ -z "${name:-}" ]] && continue
  copy_skill_tree "$skill_dir" "$destination"
done < <(cat "$items_file" "$duplicates_file")

if command -v python3 >/dev/null 2>&1; then
  python_json="python3"
elif command -v python >/dev/null 2>&1; then
  python_json="python"
else
  python_json=""
fi

if [[ -n "$python_json" ]]; then
  "$python_json" - "$items_file" "$duplicates_file" "$source_root" "$target_root" "$manifest" <<'PY'
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

items_file, duplicates_file, source_root, target_root, manifest = sys.argv[1:6]

def rows(path: str, duplicate: bool) -> list[dict]:
    output = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        if not line:
            continue
        name, source, destination, relative = line.split("\t", 3)
        output.append({"name": name, "source": source, "destination": destination, "relative": relative, "duplicate": duplicate})
    return output

items = rows(items_file, False)
duplicates = rows(duplicates_file, True)
payload = {
    "collection": "local",
    "source_root": source_root,
    "target_root": target_root,
    "migrated_at": datetime.now(timezone.utc).isoformat(),
    "count": len(items),
    "duplicate_count": len(duplicates),
    "items": items,
    "duplicates": duplicates,
}
Path(manifest).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
PY
fi

count="$(grep -c . "$items_file" || true)"
duplicate_count="$(grep -c . "$duplicates_file" || true)"
echo "Migrated $count local skills to $target_skills"
echo "Moved $duplicate_count duplicate skills to $target_duplicates"
echo "Manifest: $manifest"
