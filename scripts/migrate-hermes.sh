#!/usr/bin/env bash
set -euo pipefail

source_root="${HOME}/.hermes/skills"
target_root="${UNLIMITED_SKILLS_ROOT:-${HOME}/.unlimited-skills/library}"
apply=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --source-root)
      source_root="$2"
      shift 2
      ;;
    --target-root)
      target_root="$2"
      shift 2
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

if [[ ! -d "$source_root" ]]; then
  echo "Source root not found: $source_root" >&2
  exit 1
fi

source_root="$(cd -- "$source_root" && pwd)"
mkdir -p "$target_root"
target_root="$(cd -- "$target_root" && pwd)"
target_skills="$target_root/local/hermes/skills"
excluded_dirs=("node_modules" ".git" ".venv" "__pycache__" ".chroma-skills" ".learning" "duplicates" ".pytest_cache" ".mypy_cache" ".ruff_cache")
excluded_names=("unlimited-skills" "skill-library")
items_file="$(mktemp)"
trap 'rm -f "$items_file"' EXIT

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

while IFS= read -r -d '' skill_file; do
  contains_excluded_dir "$skill_file" && continue
  skill_dir="$(dirname "$skill_file")"
  name="$(basename "$skill_dir")"
  is_excluded_name "$name" && continue
  relative="${skill_dir#$source_root/}"
  printf '%s\t%s\t%s\n' "$name" "$skill_dir" "$relative" >> "$items_file"
done < <(find "$source_root" -type f -name 'SKILL.md' -print0)

if [[ "$apply" -eq 0 ]]; then
  echo "Dry run. Add --apply to copy skills."
  cat "$items_file"
  exit 0
fi

mkdir -p "$target_skills"
while IFS=$'\t' read -r name skill_dir relative; do
  [[ -z "${name:-}" ]] && continue
  destination="$target_skills/$relative"
  mkdir -p "$destination"
  cp -R "$skill_dir"/. "$destination"/
done < "$items_file"

count="$(grep -c . "$items_file" || true)"
echo "Migrated $count Hermes skills to $target_skills"
