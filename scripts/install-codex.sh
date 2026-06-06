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
  --mode MODE            default, bundled, or adapt-installed. Defaults to default.
  --agents-file PATH     Patch this AGENTS.md file. Defaults to ./AGENTS.md.
  --no-agents-patch      Do not patch AGENTS.md.
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
mode="default"
agents_file=""
no_agents_patch=0

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
    --mode)
      mode="$2"
      shift 2
      ;;
    --agents-file)
      agents_file="$2"
      shift 2
      ;;
    --no-agents-patch)
      no_agents_patch=1
      shift
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

case "$mode" in
  default|bundled|adapt-installed)
    ;;
  *)
    echo "Invalid --mode: $mode" >&2
    exit 2
    ;;
esac

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
library_root="$install_root/library"

if [[ "$skip_pip_install" -eq 0 ]]; then
  if [[ ! -x "$venv_python" ]]; then
    "$python_cmd" -m venv "$venv"
  fi
  "$venv_python" -m pip install --upgrade pip
  "$venv_python" -m pip install -e "$repo_root[all]"
fi

cli_python="$python_cmd"
if [[ -x "$venv_python" ]]; then
  cli_python="$venv_python"
fi
export PYTHONPATH="$repo_root:${PYTHONPATH:-}"

launcher="$skill_target/scripts/unlimited-skills.sh"
mkdir -p "$(dirname "$launcher")"
cat > "$launcher" <<EOF
#!/usr/bin/env bash
set -euo pipefail
if [[ -x "$venv_python" ]]; then
  exec "$venv_python" -m unlimited_skills.cli --root "$library_root" "\$@"
fi
export PYTHONPATH="$repo_root:\${PYTHONPATH:-}"
exec "$python_cmd" -m unlimited_skills.cli --root "$library_root" "\$@"
EOF
chmod +x "$launcher"

if [[ "$no_agents_patch" -eq 0 ]]; then
  if [[ -z "$agents_file" ]]; then
    agents_file="$PWD/AGENTS.md"
  fi
  agents_dir="$(dirname -- "$agents_file")"
  mkdir -p "$agents_dir"
  agents_block="$(cat <<EOF
<!-- BEGIN UNLIMITED SKILLS -->
## Unlimited Skills Library

Unlimited Skills is the external skill memory for this agent. Treat it as the first place to ask for task-specific skills, workflows, checklists, procedures, and regression recipes.

Before doing substantive work, check whether Unlimited Skills has a relevant skill. This includes writing, editing, coding, review, debugging, research, documentation, operations, planning, and design tasks. Skip this check only when a relevant skill is already active in the current context and it is clear why that skill applies.

Before saying a skill is unavailable, query the library:

\`\`\`bash
"$launcher" search "<task or skill name>" --mode hybrid --limit 8
"$launcher" where <skill-name>
"$launcher" view <skill-name>
\`\`\`

For inventory questions, query the library before answering:

\`\`\`bash
"$launcher" list --limit 80
\`\`\`

Do not rely only on .agents/skills, .codex/skills, or the visible skill list. The library may contain skills that are intentionally not loaded into context.
<!-- END UNLIMITED SKILLS -->
EOF
)"
  tmp_agents="$(mktemp)"
  if [[ -f "$agents_file" ]]; then
    AGENTS_BLOCK="$agents_block" "$python_cmd" - "$agents_file" "$tmp_agents" <<'PY'
from pathlib import Path
import os
import re
import sys

path = Path(sys.argv[1])
out = Path(sys.argv[2])
block = os.environ["AGENTS_BLOCK"]
text = path.read_text(encoding="utf-8", errors="replace")
pattern = r"(?s)<!-- BEGIN UNLIMITED SKILLS -->.*?<!-- END UNLIMITED SKILLS -->"
if re.search(pattern, text):
    text = re.sub(pattern, block, text)
elif text.strip():
    text = text.rstrip() + "\n\n" + block + "\n"
else:
    text = block + "\n"
out.write_text(text, encoding="utf-8")
PY
    mv "$tmp_agents" "$agents_file"
  else
    printf '%s\n' "$agents_block" > "$agents_file"
    rm -f "$tmp_agents"
  fi
fi

migrate="$repo_root/scripts/lib/migrate-skills.sh"

if [[ "$mode" == "bundled" ]]; then
  for pack in ecc superpowers; do
    pack_root="$repo_root/packs/$pack/skills"
    if [[ -d "$pack_root" ]]; then
      "$migrate" --source-root "$pack_root" --target-root "$library_root" --collection "$pack" --apply
    fi
  done
fi

if [[ -d "$codex_home/skills" ]]; then
  migrate_args=(
    --source-root "$codex_home/skills"
    --target-root "$library_root"
    --collection "codex"
    --exclude-name ".system"
    --exclude-name "unlimited-skills"
    --exclude-name "skill-library"
    --apply
  )
  if [[ "$mode" == "bundled" ]]; then
    migrate_args+=(--skip-existing-names)
  fi
  "$migrate" "${migrate_args[@]}"
fi

if [[ "$mode" == "adapt-installed" ]]; then
  "$cli_python" -m unlimited_skills.cli --root "$library_root" adapt --collection codex --source-pack codex
fi

"$cli_python" -m unlimited_skills.cli --root "$library_root" reindex

echo "Installed Codex router skill: $skill_target"
echo "Installed Unlimited Skills venv: $venv"
echo "Install mode: $mode"
echo "Library root: $library_root"
echo "Launcher: $launcher"
if [[ "$no_agents_patch" -eq 0 ]]; then
  echo "Patched AGENTS.md: $agents_file"
else
  echo "Skipped AGENTS.md patch."
fi
echo "Restart Codex so the router skill appears in the available skill list."
