#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage: install-codex.sh [options]

Install the Unlimited Skills router skill for Codex on macOS/Linux.

Options:
  --repo-root PATH       Repository root. Defaults to the parent of this script directory.
  --codex-home PATH      Codex home directory. Defaults to ~/.codex.
  --install-root PATH    Unlimited Skills install root. Defaults to ~/.unlimited-skills.
  --python CMD           Python executable. Defaults to python3, then python.
  --skip-pip-install     Only install the router skill and launcher.
  -h, --help             Show this help.
EOF
}

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd -- "$script_dir/.." && pwd)"
codex_home="${HOME}/.codex"
install_root="${HOME}/.unlimited-skills"
python_cmd=""
skip_pip_install=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --repo-root)
      repo_root="$2"
      shift 2
      ;;
    --codex-home)
      codex_home="$2"
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
    --skip-pip-install)
      skip_pip_install=1
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

repo_root="$(cd -- "$repo_root" && pwd)"
skill_source="$repo_root/skills/skill-router"
skill_target="$codex_home/skills/unlimited-skills"

if [[ ! -d "$skill_source" ]]; then
  echo "Router skill not found: $skill_source" >&2
  exit 2
fi

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

mkdir -p "$(dirname "$skill_target")"
rm -rf "$skill_target"
cp -R "$skill_source" "$skill_target"

venv="$install_root/.venv"
venv_python="$venv/bin/python"

if [[ "$skip_pip_install" -eq 0 ]]; then
  if [[ ! -x "$venv_python" ]]; then
    "$python_cmd" -m venv "$venv"
  fi
  "$venv_python" -m pip install --upgrade pip
  "$venv_python" -m pip install -e "$repo_root[all]"
fi

launcher="$skill_target/scripts/unlimited-skills.sh"
mkdir -p "$(dirname "$launcher")"
cat > "$launcher" <<EOF
#!/usr/bin/env bash
set -euo pipefail
if [[ -x "$venv_python" ]]; then
  exec "$venv_python" -m unlimited_skills.cli "\$@"
fi
export PYTHONPATH="$repo_root:\${PYTHONPATH:-}"
exec "$python_cmd" -m unlimited_skills.cli "\$@"
EOF
chmod +x "$launcher"

echo "Installed Codex router skill: $skill_target"
echo "Installed Unlimited Skills venv: $venv"
echo "Launcher: $launcher"
echo "Restart Codex so the router skill appears in the available skill list."
