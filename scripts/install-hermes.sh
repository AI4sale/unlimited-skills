#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage: install-hermes.sh [options]

Install the Unlimited Skills router adapter for Hermes.

By default this is a dry run. Pass --apply to change files.

Options:
  --repo-root PATH       Repository root. Defaults to the parent of this script directory.
  --hermes-home PATH     Hermes home directory. Defaults to ${HERMES_HOME:-~/.hermes}.
  --install-root PATH    Unlimited Skills install root. Defaults to ~/.unlimited-skills.
  --python CMD           Python executable. Defaults to python3, then python.
  --mode MODE            router-only or evacuate-visible-skills. Defaults to router-only.
  --skip-pip-install     Do not create/update ~/.unlimited-skills/.venv.
  --skip-reindex         Do not rebuild the lexical index.
  --remote-first         Configure router instructions to prefer Local Skill Hub remote resolve.
  --no-remote            Disable remote-first configuration.
  --remote-hub-url URL   Local Skill Hub URL.
  --hub-token-env NAME   Environment variable that contains the hub token. Preferred.
  --hub-token TOKEN      Hub token to store in private remote.json. Avoid for shared machines.
  --remote-fallback MODE local_allowed or hub_required. Defaults to local_allowed.
  --json                 Print JSON report.
  --apply                Actually change files. Without this flag, prints a dry-run report.
  -h, --help             Show this help.

Context reduction mode:
  ./scripts/install-hermes.sh --mode evacuate-visible-skills --apply
EOF
}

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd -- "$script_dir/.." && pwd)"
hermes_home="${HERMES_HOME:-${HOME}/.hermes}"
install_root="${HOME}/.unlimited-skills"
python_cmd=""
mode="router-only"
skip_pip_install=0
skip_reindex=0
remote_first=0
no_remote=0
remote_hub_url=""
hub_token_env=""
hub_token=""
remote_fallback="local_allowed"
apply=0
json=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --repo-root)
      repo_root="$2"
      shift 2
      ;;
    --hermes-home)
      hermes_home="$2"
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
    --skip-pip-install)
      skip_pip_install=1
      shift
      ;;
    --skip-reindex)
      skip_reindex=1
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

case "$mode" in
  router-only|evacuate-visible-skills)
    ;;
  *)
    echo "Invalid --mode: $mode" >&2
    exit 2
    ;;
esac

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

cli_python="$python_cmd"
venv="$install_root/.venv"
venv_python="$venv/bin/python"
if [[ ! -x "$venv_python" && -x "$venv/Scripts/python.exe" ]]; then
  venv_python="$venv/Scripts/python.exe"
fi

if [[ "$apply" -eq 1 && "$skip_pip_install" -eq 0 ]]; then
  if [[ ! -x "$venv_python" ]]; then
    "$python_cmd" -m venv "$venv"
    if [[ ! -x "$venv_python" && -x "$venv/Scripts/python.exe" ]]; then
      venv_python="$venv/Scripts/python.exe"
    fi
  fi
  pip_repo_root="$repo_root"
  if command -v cygpath >/dev/null 2>&1 && [[ "$venv_python" == *.exe ]]; then
    pip_repo_root="$(cygpath -w "$repo_root")"
  fi
  "$venv_python" -m pip install --upgrade pip
  "$venv_python" -m pip install -e "$pip_repo_root[all]"
  cli_python="$venv_python"
elif [[ -x "$venv_python" ]]; then
  cli_python="$venv_python"
fi

if ! "$cli_python" -I -c "import unlimited_skills" >/dev/null 2>&1; then
  export PYTHONPATH="$repo_root:${PYTHONPATH:-}"
fi
args=(
  -m unlimited_skills.installers.hermes install
  --repo-root "$repo_root"
  --hermes-home "$hermes_home"
  --install-root "$install_root"
  --mode "$mode"
  --python-executable "$cli_python"
)

if [[ "$apply" -eq 1 ]]; then
  args+=(--apply)
fi
if [[ "$skip_reindex" -eq 1 ]]; then
  args+=(--skip-reindex)
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
