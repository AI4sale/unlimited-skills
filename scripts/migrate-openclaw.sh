#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
openclaw_home="${OPENCLAW_HOME:-${HOME}/.openclaw}"
source_root="${OPENCLAW_WORKSPACE:-${openclaw_home}/workspace}/skills"
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
  --collection "openclaw-workspace" \
  "${extra_args[@]}"
