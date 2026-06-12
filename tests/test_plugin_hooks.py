from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from unlimited_skills.search_core import save_index

REPO_ROOT = Path(__file__).resolve().parents[1]
HOOKS_DIR = REPO_ROOT / "plugin" / "hooks"
SESSION_START = HOOKS_DIR / "session_start.py"
USER_PROMPT_SUBMIT = HOOKS_DIR / "user_prompt_submit.py"


def make_library(tmp_path: Path) -> Path:
    root = tmp_path / "library"
    skill_dir = root / "local" / "skills" / "python-patterns"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "---\nname: python-patterns\ndescription: Pythonic idioms, PEP 8 standards, and code review best practices for Python.\n---\n\n# python-patterns\n",
        encoding="utf-8",
    )
    save_index(root)
    return root


def hook_env(tmp_path: Path, **overrides: str) -> dict[str, str]:
    env = dict(os.environ)
    # Isolate the fallback chain from the developer machine's real installs.
    env["CLAUDE_HOME"] = str(tmp_path / "claude-home")
    env["UNLIMITED_SKILLS_INSTALL_ROOT"] = str(tmp_path / "install-root")
    env.pop("UNLIMITED_SKILLS_CLI", None)
    env.update(overrides)
    return env


def repo_cli_override(root: Path) -> str:
    python = Path(sys.executable).as_posix()
    return f'"{python}" -m unlimited_skills --root "{root.as_posix()}"'


def run_hook(script: Path, stdin_text: str, env: dict[str, str]) -> subprocess.CompletedProcess:
    env = dict(env)
    env["PYTHONPATH"] = str(REPO_ROOT) + os.pathsep + env.get("PYTHONPATH", "")
    return subprocess.run(
        [sys.executable, str(script)],
        input=stdin_text,
        capture_output=True,
        text=True,
        env=env,
        timeout=60,
        cwd=str(REPO_ROOT),
    )


def test_session_start_emits_missing_text_when_no_install_found(tmp_path: Path) -> None:
    env = hook_env(tmp_path)
    env["PATH"] = str(tmp_path / "empty-path")
    if os.name == "nt":
        env["PATH"] += os.pathsep + os.environ.get("SYSTEMROOT", "")
    result = run_hook(SESSION_START, "", env)
    assert result.returncode == 0
    assert "no unlimited-skills CLI was" in result.stdout
    assert "TRIGGERS" not in result.stdout  # the contract is not emitted without a CLI
    assert len(result.stdout) < 2000


def test_session_start_resolves_install_venv_before_nagging(tmp_path: Path) -> None:
    env = hook_env(tmp_path)
    env["PATH"] = str(tmp_path / "empty-path")
    if os.name == "nt":
        env["PATH"] += os.pathsep + os.environ.get("SYSTEMROOT", "")
    venv = tmp_path / "install-root" / ".venv"
    exe = venv / ("Scripts/unlimited-skills.exe" if os.name == "nt" else "bin/unlimited-skills")
    exe.parent.mkdir(parents=True)
    exe.write_text("stub", encoding="utf-8")
    exe.chmod(0o755)
    result = run_hook(SESSION_START, "", env)
    assert result.returncode == 0
    assert "unlimited-skills" in result.stdout
    assert str(exe) in result.stdout.replace("\n", " ")
    assert 'suggest "<task in 3-8 keywords>"' in result.stdout
    assert "SKIP only when a relevant skill is already active" in result.stdout


def test_session_start_resolves_rendered_launcher(tmp_path: Path) -> None:
    env = hook_env(tmp_path)
    env["PATH"] = str(tmp_path / "empty-path")
    if os.name == "nt":
        env["PATH"] += os.pathsep + os.environ.get("SYSTEMROOT", "")
    scripts_dir = tmp_path / "claude-home" / "skills" / "unlimited-skills" / "scripts"
    scripts_dir.mkdir(parents=True)
    if os.name == "nt":
        (scripts_dir / "unlimited-skills.ps1").write_text("# stub", encoding="utf-8")
    else:
        launcher = scripts_dir / "unlimited-skills.sh"
        launcher.write_text("#!/usr/bin/env bash\n", encoding="utf-8")
        launcher.chmod(0o755)
        env["PATH"] = os.environ.get("PATH", "")  # bash must stay resolvable
    result = run_hook(SESSION_START, "", env)
    assert result.returncode == 0
    assert "unlimited-skills" in result.stdout
    assert 'suggest "<task in 3-8 keywords>"' in result.stdout


def test_user_prompt_submit_emits_hint_for_relevant_prompt(tmp_path: Path) -> None:
    library = make_library(tmp_path)
    env = hook_env(tmp_path, UNLIMITED_SKILLS_CLI=repo_cli_override(library))
    payload = json.dumps({"prompt": "review my python module for pep8 issues and idioms"})
    result = run_hook(USER_PROMPT_SUBMIT, payload, env)
    assert result.returncode == 0, result.stderr
    output = json.loads(result.stdout)
    specific = output["hookSpecificOutput"]
    assert specific["hookEventName"] == "UserPromptSubmit"
    assert "Relevant skill available: python-patterns" in specific["additionalContext"]
    assert "view python-patterns" in specific["additionalContext"]


def test_user_prompt_submit_is_silent_below_floor(tmp_path: Path) -> None:
    library = make_library(tmp_path)
    env = hook_env(tmp_path, UNLIMITED_SKILLS_CLI=repo_cli_override(library))
    payload = json.dumps({"prompt": "what is the capital of Australia please tell me"})
    result = run_hook(USER_PROMPT_SUBMIT, payload, env)
    assert result.returncode == 0
    assert result.stdout.strip() == ""


def test_user_prompt_submit_skips_short_prompts(tmp_path: Path) -> None:
    library = make_library(tmp_path)
    env = hook_env(tmp_path, UNLIMITED_SKILLS_CLI=repo_cli_override(library))
    result = run_hook(USER_PROMPT_SUBMIT, json.dumps({"prompt": "hi"}), env)
    assert result.returncode == 0
    assert result.stdout.strip() == ""


def test_user_prompt_submit_fails_open_on_bad_stdin(tmp_path: Path) -> None:
    env = hook_env(tmp_path)
    for stdin_text in ("", "not json at all", "[1, 2"):
        result = run_hook(USER_PROMPT_SUBMIT, stdin_text, env)
        assert result.returncode == 0
        assert result.stdout.strip() == ""


def test_user_prompt_submit_fails_open_on_missing_cli(tmp_path: Path) -> None:
    env = hook_env(tmp_path, UNLIMITED_SKILLS_CLI=str(tmp_path / "missing" / "cli.exe"))
    payload = json.dumps({"prompt": "review my python module for pep8 issues and idioms"})
    result = run_hook(USER_PROMPT_SUBMIT, payload, env)
    assert result.returncode == 0
    assert result.stdout.strip() == ""


def test_user_prompt_submit_fails_open_on_timeout(tmp_path: Path) -> None:
    sleeper = tmp_path / "sleeper.py"
    sleeper.write_text("import time\ntime.sleep(10)\n", encoding="utf-8")
    cli = f'"{Path(sys.executable).as_posix()}" "{sleeper.as_posix()}"'
    env = hook_env(tmp_path, UNLIMITED_SKILLS_CLI=cli, UNLIMITED_SKILLS_SUGGEST_TIMEOUT="0.5")
    payload = json.dumps({"prompt": "review my python module for pep8 issues and idioms"})
    result = run_hook(USER_PROMPT_SUBMIT, payload, env)
    assert result.returncode == 0
    assert result.stdout.strip() == ""


@pytest.mark.parametrize("event,script", [("SessionStart", "session_start.py"), ("UserPromptSubmit", "user_prompt_submit.py")])
def test_hook_manifest_registers_both_hooks(event: str, script: str) -> None:
    payload = json.loads((HOOKS_DIR / "hooks.json").read_text(encoding="utf-8"))
    entries = payload["hooks"][event]
    command = entries[0]["hooks"][0]["command"]
    assert script in command
    assert "${CLAUDE_PLUGIN_ROOT}" in command
    assert (HOOKS_DIR / script).is_file()
