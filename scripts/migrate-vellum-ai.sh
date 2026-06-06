#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
source_root="${HOME}/.vellum-ai/skills"
target_root="${UNLIMITED_SKILLS_ROOT:-${HOME}/.unlimited-skills/library}"
extra_args=()

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
    *)
      extra_args+=("$1")
      shift
      ;;
  esac
done

exec "$script_dir/lib/migrate-skills.sh" \
  --source-root "$source_root" \
  --target-root "$target_root" \
  --collection "vellum-ai" \
  "${extra_args[@]}"
