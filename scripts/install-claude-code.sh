#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage: install-claude-code.sh [options]

Install the Unlimited Skills router adapter for Claude Code.

Options:
  --repo-root PATH       Repository root. Defaults to the parent of this script directory.
  --claude-home PATH     Claude Code home directory. Defaults to ~/.claude.
  --project-root PATH    Project root whose CLAUDE.md and .claude/skills are used. Defaults to $PWD.
  --install-root PATH    Unlimited Skills install root. Defaults to ~/.unlimited-skills.
  --python CMD           Python executable. Defaults to python3, then python.
  --mode MODE            default, bundled, or adapt-installed. Defaults to default.
  --claude-file PATH     Patch this CLAUDE.md file. Defaults to $project_root/CLAUDE.md.
  --no-claude-patch      Do not patch CLAUDE.md.
  --no-project-skills    Do not import project .claude/skills.
  --skip-pip-install     Do not create/update ~/.unlimited-skills/.venv.
  --skip-reindex         Do not rebuild the lexical index.
  --vector-reindex       Also rebuild the Chroma vector index.
  --remote-first         Configure router instructions to prefer Local Skill Hub remote resolve.
  --no-remote            Disable remote-first configuration.
  --remote-hub-url URL   Local Skill Hub URL.
  --hub-token-env NAME   Environment variable that contains the hub token. Preferred.
  --hub-token TOKEN      Hub token to store in private remote.json. Avoid for shared machines.
  --remote-fallback MODE local_allowed or hub_required. Defaults to local_allowed.
  --json                 Print JSON report.
  -h, --help             Show this help.
EOF
}

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd -- "$script_dir/.." && pwd)"
claude_home="${CLAUDE_HOME:-${HOME}/.claude}"
project_root="$PWD"
install_root="${HOME}/.unlimited-skills"
python_cmd=""
mode="default"
claude_file=""
no_claude_patch=0
no_project_skills=0
skip_pip_install=0
skip_reindex=0
vector_reindex=0
remote_first=0
no_remote=0
remote_hub_url=""
hub_token_env=""
hub_token=""
remote_fallback="local_allowed"
json=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --repo-root)
      repo_root="$2"
      shift 2
      ;;
    --claude-home)
      claude_home="$2"
      shift 2
      ;;
    --project-root)
      project_root="$2"
      shift 2
      ;;
    --install-root)
      install_root="$2"
      shift 2
      ;;
    --python)
      python_cmd="$2"
      shift 2
      ;;
    --mode)
      mode="$2"
      shift 2
      ;;
    --claude-file)
      claude_file="$2"
      shift 2
      ;;
    --no-claude-patch)
      no_claude_patch=1
      shift
      ;;
    --no-project-skills)
      no_project_skills=1
      shift
      ;;
    --skip-pip-install)
      skip_pip_install=1
      shift
      ;;
    --skip-reindex)
      skip_reindex=1
      shift
      ;;
    --vector-reindex)
      vector_reindex=1
      shift
      ;;
    --remote-first)
      remote_first=1
      shift
      ;;
    --no-remote)
      no_remote=1
      shift
      ;;
    --remote-hub-url)
      remote_hub_url="$2"
      shift 2
      ;;
    --hub-token-env)
      hub_token_env="$2"
      shift 2
      ;;
    --hub-token)
      hub_token="$2"
      shift 2
      ;;
    --remote-fallback)
      remote_fallback="$2"
      shift 2
      ;;
    --json)
      json=1
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

case "$mode" in
  default|bundled|adapt-installed)
    ;;
  *)
    echo "Invalid --mode: $mode" >&2
    exit 2
    ;;
esac

repo_root="$(cd -- "$repo_root" && pwd)"
project_root="$(cd -- "$project_root" && pwd)"

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

venv="$install_root/.venv"
venv_python="$venv/bin/python"
cli_python="$python_cmd"

if [[ "$skip_pip_install" -eq 0 ]]; then
  if [[ ! -x "$venv_python" ]]; then
    "$python_cmd" -m venv "$venv"
  fi
  "$venv_python" -m pip install --upgrade pip
  "$venv_python" -m pip install -e "$repo_root[all]"
  cli_python="$venv_python"
elif [[ -x "$venv_python" ]]; then
  cli_python="$venv_python"
fi

export PYTHONPATH="$repo_root:${PYTHONPATH:-}"

args=(
  -m unlimited_skills.installers.claude_code
  --repo-root "$repo_root"
  --claude-home "$claude_home"
  --project-root "$project_root"
  --install-root "$install_root"
  --mode "$mode"
  --python-executable "$cli_python"
)

if [[ -n "$claude_file" ]]; then
  args+=(--claude-file "$claude_file")
fi
if [[ "$no_claude_patch" -eq 1 ]]; then
  args+=(--no-claude-patch)
fi
if [[ "$no_project_skills" -eq 1 ]]; then
  args+=(--no-project-skills)
fi
if [[ "$skip_reindex" -eq 1 ]]; then
  args+=(--skip-reindex)
fi
if [[ "$vector_reindex" -eq 1 ]]; then
  args+=(--vector-reindex)
fi
if [[ "$remote_first" -eq 1 ]]; then
  args+=(--remote-first)
fi
if [[ "$no_remote" -eq 1 ]]; then
  args+=(--no-remote)
fi
if [[ -n "$remote_hub_url" ]]; then
  args+=(--remote-hub-url "$remote_hub_url")
fi
if [[ -n "$hub_token_env" ]]; then
  args+=(--hub-token-env "$hub_token_env")
fi
if [[ -n "$hub_token" ]]; then
  args+=(--hub-token "$hub_token")
fi
args+=(--remote-fallback "$remote_fallback")
if [[ "$json" -eq 1 ]]; then
  args+=(--json)
fi

"$cli_python" "${args[@]}"
