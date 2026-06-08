#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage: install-codex.sh [options]

Install the Unlimited Skills router skill for Codex on macOS/Linux.

Options:
  --repo-root PATH       Repository root. Defaults to the parent of this script directory.
  --codex-home PATH      Codex home directory. Defaults to ~/.codex.
  --install-root PATH    Unlimited Skills install root. Defaults to $CODEX_HOME/.unlimited-skills.
  --python CMD           Python executable. Defaults to python3, then python.
  --mode MODE            default, bundled, or adapt-installed. Defaults to default.
  --agents-file PATH     Patch this AGENTS.md file. Defaults to $CODEX_HOME/AGENTS.md.
  --no-agents-patch      Do not patch AGENTS.md.
  --skip-pip-install     Only install the router skill and launcher.
  --remote-first         Configure router instructions to prefer Local Skill Hub remote resolve.
  --no-remote            Disable remote-first configuration.
  --remote-hub-url URL   Local Skill Hub URL.
  --hub-token-env NAME   Environment variable that contains the hub token. Preferred.
  --hub-token TOKEN      Hub token to store in private remote.json. Avoid for shared machines.
  --remote-fallback MODE local_allowed or hub_required. Defaults to local_allowed.
  -h, --help             Show this help.
EOF
}

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd -- "$script_dir/.." && pwd)"
codex_home="${HOME}/.codex"
install_root=""
python_cmd=""
skip_pip_install=0
mode="default"
agents_file=""
no_agents_patch=0
remote_first=0
no_remote=0
remote_hub_url=""
hub_token_env=""
hub_token=""
remote_fallback="local_allowed"

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
if [[ -z "$install_root" ]]; then
  install_root="$codex_home/.unlimited-skills"
fi
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
mkdir -p "$skill_target"
cp -R "$skill_source"/. "$skill_target"/

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
remote_enabled=0
if [[ "$no_remote" -eq 0 && ( "$remote_first" -eq 1 || -n "$remote_hub_url" || -n "$hub_token_env" || -n "$hub_token" ) ]]; then
  remote_enabled=1
fi
if [[ "$no_remote" -eq 1 && ( "$remote_first" -eq 1 || -n "$remote_hub_url" || -n "$hub_token_env" || -n "$hub_token" ) ]]; then
  echo "--no-remote cannot be combined with remote hub options." >&2
  exit 2
fi
if [[ "$remote_enabled" -eq 1 && -z "$remote_hub_url" ]]; then
  echo "--remote-hub-url is required when remote-first mode is enabled." >&2
  exit 2
fi
if [[ "$remote_enabled" -eq 1 && -n "$hub_token_env" && -n "$hub_token" ]]; then
  echo "Use either --hub-token-env or --hub-token, not both." >&2
  exit 2
fi
if [[ "$remote_enabled" -eq 1 && -z "$hub_token_env" && -z "$hub_token" ]]; then
  echo "Remote-first mode requires --hub-token-env or --hub-token." >&2
  exit 2
fi

launcher="$skill_target/scripts/unlimited-skills.sh"
mkdir -p "$(dirname "$launcher")"
cat > "$launcher" <<EOF
#!/usr/bin/env bash
set -euo pipefail
if [[ -x "$venv_python" ]]; then
  export UNLIMITED_SKILLS_HOME="$install_root"
  export UNLIMITED_SKILLS_ROOT="$library_root"
  exec "$venv_python" -m unlimited_skills.cli --root "$library_root" "\$@"
fi
export PYTHONPATH="$repo_root:\${PYTHONPATH:-}"
export UNLIMITED_SKILLS_HOME="$install_root"
export UNLIMITED_SKILLS_ROOT="$library_root"
exec "$python_cmd" -m unlimited_skills.cli --root "$library_root" "\$@"
EOF
chmod +x "$launcher"

remote_block=""
token_source=""
if [[ "$remote_enabled" -eq 1 ]]; then
  export UNLIMITED_SKILLS_HOME="$install_root"
  remote_args=(--root "$library_root" remote configure --url "$remote_hub_url" --fallback "$remote_fallback")
  if [[ -n "$hub_token_env" ]]; then
    remote_args+=(--token-env "$hub_token_env")
    token_source="env:$hub_token_env"
  else
    remote_args+=(--token "$hub_token")
    token_source="private remote.json"
  fi
  "$cli_python" -m unlimited_skills.cli "${remote_args[@]}" >/dev/null
  remote_block="$(cat <<EOF
## Remote-First Local Skill Hub Mode

This install is configured for remote-first skill routing through Local Skill Hub.

- Hub URL: \`$remote_hub_url\`
- Token source: \`$token_source\`
- Fallback policy: \`$remote_fallback\`

Before local \`search\`/\`view\`, prefer remote resolution:

\`\`\`bash
"$launcher" remote resolve "<task or skill name>" --agent codex --max-skills 2 --max-chars 12000
\`\`\`

Use only the selected skill bodies returned by the hub. If a selected skill is metadata-only or requires a local install plan, surface the missing capability warning instead of pretending the skill is ready.

Never print, paste, or store the raw hub token in visible router files, prompts, or logs.
EOF
)"
fi
"$cli_python" - "$skill_target/SKILL.md" "$remote_block" <<'PY'
import sys
from pathlib import Path

path = Path(sys.argv[1])
block = sys.argv[2]
text = path.read_text(encoding="utf-8")
path.write_text(text.replace("{{REMOTE_HUB_ROUTER_BLOCK}}", block), encoding="utf-8")
PY

if [[ "$no_agents_patch" -eq 0 ]]; then
  if [[ -z "$agents_file" ]]; then
    agents_file="$codex_home/AGENTS.md"
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
  AGENTS_BLOCK="$agents_block" "$cli_python" -m unlimited_skills.agents_patch "$agents_file"
fi

migrate="$repo_root/scripts/lib/migrate-skills.sh"
migrate_codex="$repo_root/scripts/migrate-codex.sh"

if [[ "$mode" == "bundled" ]]; then
  for pack in ecc superpowers; do
    pack_root="$repo_root/packs/$pack/skills"
    if [[ -d "$pack_root" ]]; then
      "$migrate" --source-root "$pack_root" --target-root "$library_root" --collection "$pack" --apply
    fi
  done
fi

if [[ -d "$codex_home/skills" ]]; then
  "$migrate_codex" \
    --source-root "$codex_home/skills" \
    --target-root "$library_root" \
    --skip-existing-names \
    --apply
fi

if [[ "$mode" == "adapt-installed" ]]; then
  "$cli_python" -m unlimited_skills.cli --root "$library_root" adapt --collection local --source-pack local
fi

"$cli_python" -m unlimited_skills.cli --root "$library_root" reindex

echo "Installed Codex router skill: $skill_target"
echo "Installed Unlimited Skills venv: $venv"
echo "Install mode: $mode"
echo "Library root: $library_root"
echo "Launcher: $launcher"
if [[ "$remote_enabled" -eq 1 ]]; then
  echo "Remote-first hub: enabled"
  echo "Remote hub URL: $remote_hub_url"
  echo "Remote fallback: $remote_fallback"
  echo "Remote token source: $token_source"
else
  echo "Remote-first hub: disabled"
fi
if [[ "$no_agents_patch" -eq 0 ]]; then
  echo "Patched AGENTS.md: $agents_file"
else
  echo "Skipped AGENTS.md patch."
fi
echo "Restart Codex so the router skill appears in the available skill list."
