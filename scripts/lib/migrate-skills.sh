#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage: migrate-skills.sh --source-root PATH --target-root PATH --collection NAME [options]

Copy recursive SKILL.md directories into an Unlimited Skills collection.

Options:
  --source-root PATH     Source directory that contains recursive SKILL.md files.
  --target-root PATH     Unlimited Skills library root.
  --collection NAME      Collection name under the target root.
  --exclude-name NAME    Exclude a skill directory name. Can be repeated.
  --skip-existing-names  Do not copy a skill when any existing collection already has the same skill directory name.
  --allow-node-modules   Do not exclude paths that contain node_modules.
  --apply                Copy files. Without this flag, the script prints a dry-run JSON plan.
  -h, --help             Show this help.
EOF
}

source_root=""
target_root=""
collection=""
apply=0
skip_existing_names=0
allow_node_modules=0
exclude_names=()
excluded_dirs=("node_modules" ".git" ".venv" "__pycache__" ".chroma-skills" ".learning" ".pytest_cache" ".mypy_cache" ".ruff_cache")

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
    --collection)
      collection="$2"
      shift 2
      ;;
    --exclude-name)
      exclude_names+=("$2")
      shift 2
      ;;
    --skip-existing-names)
      skip_existing_names=1
      shift
      ;;
    --allow-node-modules)
      allow_node_modules=1
      shift
      ;;
    --apply)
      apply=1
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown argument: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

if [[ "$allow_node_modules" -eq 1 ]]; then
  filtered_excluded_dirs=()
  for excluded in "${excluded_dirs[@]}"; do
    [[ "$excluded" == "node_modules" ]] && continue
    filtered_excluded_dirs+=("$excluded")
  done
  excluded_dirs=("${filtered_excluded_dirs[@]}")
fi

if [[ -z "$source_root" || -z "$target_root" || -z "$collection" ]]; then
  usage >&2
  exit 2
fi

if [[ ! -d "$source_root" ]]; then
  echo "Source root not found: $source_root" >&2
  exit 1
fi

if command -v python3 >/dev/null 2>&1; then
  python_json="python3"
elif command -v python >/dev/null 2>&1; then
  python_json="python"
else
  echo "Python was not found. It is required for JSON manifest generation." >&2
  exit 2
fi

source_root="$(cd -- "$source_root" && pwd)"
mkdir -p "$target_root"
target_root="$(cd -- "$target_root" && pwd)"
target_skills="$target_root/registry/$collection/skills"
manifest_dir="$target_root/manifests"
timestamp="$(date +%Y%m%d-%H%M%S)"
manifest="$manifest_dir/${collection}-migration-${timestamp}.json"

is_excluded_name() {
  local name="$1"
  local excluded
  for excluded in "${exclude_names[@]}"; do
    [[ "$name" == "$excluded" ]] && return 0
  done
  return 1
}

contains_excluded_dir() {
  local path="$1"
  local excluded
  for excluded in "${excluded_dirs[@]}"; do
    [[ "$path" == *"/$excluded/"* || "$path" == *"/$excluded" ]] && return 0
  done
  return 1
}

contains_excluded_name_dir() {
  local path="$1"
  local excluded
  for excluded in "${exclude_names[@]}"; do
    [[ "$path" == *"/$excluded/"* || "$path" == *"/$excluded" ]] && return 0
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

items_file="$(mktemp)"
existing_names_file="$(mktemp)"
trap 'rm -f "$items_file" "$existing_names_file"' EXIT

if [[ "$skip_existing_names" -eq 1 && -d "$target_root" ]]; then
  while IFS= read -r -d '' existing_skill; do
    case "$existing_skill" in
      "$target_skills"/*)
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
  if contains_excluded_name_dir "$skill_file"; then
    continue
  fi
  skill_dir="$(dirname "$skill_file")"
  name="$(basename "$skill_dir")"
  if is_excluded_name "$name"; then
    continue
  fi
  if [[ "$skip_existing_names" -eq 1 ]] && grep -Fxq "$name" "$existing_names_file"; then
    continue
  fi
  destination="$target_skills/$name"
  relative="${skill_dir#$source_root/}"
  printf '%s\t%s\t%s\t%s\n' "$name" "$skill_dir" "$destination" "$relative" >> "$items_file"
done < <(find "$source_root" -type f -name 'SKILL.md' -print0)

if [[ "$apply" -eq 0 ]]; then
  echo "Dry run. Add --apply to copy skills."
  "$python_json" - "$items_file" <<'PY'
import json
import sys
from pathlib import Path

rows = []
for line in Path(sys.argv[1]).read_text(encoding="utf-8").splitlines():
    if not line:
        continue
    name, source, destination, relative = line.split("\t", 3)
    rows.append({"name": name, "source": source, "destination": destination, "relative": relative})
print(json.dumps(rows, ensure_ascii=False, indent=2))
PY
  exit 0
fi

mkdir -p "$target_skills" "$manifest_dir"

while IFS=$'\t' read -r name skill_dir destination relative; do
  [[ -z "${name:-}" ]] && continue
  copy_skill_tree "$skill_dir" "$destination"
done < "$items_file"

"$python_json" - "$items_file" "$collection" "$source_root" "$target_root" "$manifest" <<'PY'
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

items_path, collection, source_root, target_root, manifest = sys.argv[1:6]
items = []
for line in Path(items_path).read_text(encoding="utf-8").splitlines():
    if not line:
        continue
    name, source, destination, relative = line.split("\t", 3)
    items.append({"name": name, "source": source, "destination": destination, "relative": relative})
payload = {
    "collection": collection,
    "source_root": source_root,
    "target_root": target_root,
    "migrated_at": datetime.now(timezone.utc).isoformat(),
    "count": len(items),
    "items": items,
}
Path(manifest).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
PY

count="$(wc -l < "$items_file" | tr -d ' ')"
echo "Migrated $count skills to $target_skills"
echo "Manifest: $manifest"
