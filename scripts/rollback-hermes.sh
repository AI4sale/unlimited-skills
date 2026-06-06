#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage: rollback-hermes.sh --manifest PATH [options]

Restore Hermes visible skills from an Unlimited Skills rollback manifest.

By default this is a dry run. Pass --apply to change files.

Options:
  --repo-root PATH       Repository root. Defaults to the parent of this script directory.
  --python CMD           Python executable. Defaults to python3, then python.
  --manifest PATH        Rollback manifest written by install-hermes.
  --json                 Print JSON report.
  --apply                Actually restore files. Without this flag, prints a dry-run report.
  -h, --help             Show this help.
EOF
}

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd -- "$script_dir/.." && pwd)"
python_cmd=""
manifest=""
apply=0
json=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --repo-root)
      repo_root="$2"
      shift 2
      ;;
    --python)
      python_cmd="$2"
      shift 2
      ;;
    --manifest)
      manifest="$2"
      shift 2
      ;;
    --json)
      json=1
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

if [[ -z "$manifest" ]]; then
  usage >&2
  exit 2
fi

repo_root="$(cd -- "$repo_root" && pwd)"
if [[ -z "$python_cmd" ]]; then
  if command -v python3 >/dev/null 2>&1; then
    python_cmd="python3"
  elif command -v python >/dev/null 2>&1; then
    python_cmd="python"
  else
    echo "Python was not found. Pass --python PATH." >&2
    exit 2
  fi
fi

export PYTHONPATH="$repo_root:${PYTHONPATH:-}"
args=(-m unlimited_skills.installers.hermes rollback --manifest "$manifest")
if [[ "$apply" -eq 1 ]]; then
  args+=(--apply)
fi
if [[ "$json" -eq 1 ]]; then
  args+=(--json)
fi

"$python_cmd" "${args[@]}"
