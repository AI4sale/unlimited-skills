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
PRE_COMPACT = HOOKS_DIR / "pre_compact.py"


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


def make_card_library(tmp_path: Path, body: str = "Step 1: read the diff.\nStep 2: check idioms.") -> Path:
    """Single-skill library whose description scores ABOVE the tier-3 high
    threshold (18.0) for the fixture prompt, with no runner-up."""
    root = tmp_path / "card-library"
    skill_dir = root / "local" / "skills" / "python-patterns"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "---\nname: python-patterns\ndescription: Pythonic idioms, pep8 issues, code review best practices for any Python module.\n---\n\n# python-patterns\n\n" + body + "\n",
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
        encoding="utf-8",  # the hook pins UTF-8 on its stdio
        errors="replace",
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
    assert 'suggest "<3-8 keyword phase summary>" --json --card --limit 1' in result.stdout
    assert "current phase" in result.stdout
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
    assert 'suggest "<3-8 keyword phase summary>" --json --card --limit 1' in result.stdout


def test_pre_compact_hook_records_claude_compaction_event(tmp_path: Path) -> None:
    from unlimited_skills.money_events import load_summary

    library = make_library(tmp_path)
    home = tmp_path / "install-root"
    env = hook_env(
        tmp_path,
        UNLIMITED_SKILLS_CLI=repo_cli_override(library),
        UNLIMITED_SKILLS_HOME=str(home),
    )

    result = run_hook(PRE_COMPACT, "", env)
    assert result.returncode == 0

    summary = load_summary(home / "money_saved")
    assert sum(bucket["event_count"] for bucket in summary["buckets"].values()) == 1
    bucket = next(iter(summary["buckets"].values()))
    assert bucket["basis"]["agent"] == "claude-code"
    assert bucket["basis"]["price_class"] == "cache_write_5m"
    assert bucket["event_types"] == {"compaction": 1}


def test_user_prompt_submit_emits_hint_for_relevant_prompt(tmp_path: Path) -> None:
    # Medium confidence (fixture scores 16, below the 18.0 high threshold):
    # tier 2, the one-line NAME-only hint, never a card.
    library = make_library(tmp_path)
    env = hook_env(tmp_path, UNLIMITED_SKILLS_CLI=repo_cli_override(library))
    prompt = "review my python module for pep8 issues and idioms"
    payload = json.dumps({"prompt": prompt})
    result = run_hook(USER_PROMPT_SUBMIT, payload, env)
    assert result.returncode == 0, result.stderr
    output = json.loads(result.stdout)
    specific = output["hookSpecificOutput"]
    assert specific["hookEventName"] == "UserPromptSubmit"
    hint = specific["additionalContext"]
    assert "Relevant skill available: python-patterns" in hint
    assert "unlimited-skills view python-patterns" in hint
    assert "Skill card:" not in hint
    # Privacy: the hint never echoes the prompt text and carries no local paths.
    assert prompt not in hint
    assert str(library) not in hint
    assert str(tmp_path) not in hint
    assert ":\\" not in hint and ":/" not in hint


def test_user_prompt_submit_injects_card_at_high_confidence(tmp_path: Path) -> None:
    library = make_card_library(tmp_path)
    env = hook_env(tmp_path, UNLIMITED_SKILLS_CLI=repo_cli_override(library))
    prompt = "review my python module for pep8 issues and idioms"
    result = run_hook(USER_PROMPT_SUBMIT, json.dumps({"prompt": prompt}), env)
    assert result.returncode == 0, result.stderr
    context = json.loads(result.stdout)["hookSpecificOutput"]["additionalContext"]
    assert context.startswith("Skill card: python-patterns (source: local)")
    assert "When to use:" in context
    assert "Step 1: read the diff." in context  # the body rides along BY DESIGN
    assert context.rstrip().endswith("Full skill body: unlimited-skills view python-patterns")
    # Privacy: no prompt echo, no local paths.
    assert prompt not in context
    assert str(library) not in context
    assert str(tmp_path) not in context
    assert ":\\" not in context and ":/" not in context


def test_user_prompt_submit_card_respects_hard_cap(tmp_path: Path) -> None:
    library = make_card_library(tmp_path, body="HEAD-OF-PROCEDURE marker.\n" + ("padding line for the cap test\n" * 600))
    env = hook_env(tmp_path, UNLIMITED_SKILLS_CLI=repo_cli_override(library))
    prompt = "review my python module for pep8 issues and idioms"
    result = run_hook(USER_PROMPT_SUBMIT, json.dumps({"prompt": prompt}), env)
    assert result.returncode == 0, result.stderr
    context = json.loads(result.stdout)["hookSpecificOutput"]["additionalContext"]
    assert len(context) <= 8000  # CARD_MAX_CHARS
    assert "HEAD-OF-PROCEDURE marker." in context  # head of the body survives
    assert "(card truncated — full skill: unlimited-skills view python-patterns)" in context
    assert context.rstrip().endswith("Full skill body: unlimited-skills view python-patterns")


def test_user_prompt_submit_kill_switch_downgrades_card_to_hint(tmp_path: Path) -> None:
    library = make_card_library(tmp_path)
    env = hook_env(
        tmp_path,
        UNLIMITED_SKILLS_CLI=repo_cli_override(library),
        UNLIMITED_SKILLS_NO_INJECT="1",
    )
    prompt = "review my python module for pep8 issues and idioms"
    result = run_hook(USER_PROMPT_SUBMIT, json.dumps({"prompt": prompt}), env)
    assert result.returncode == 0, result.stderr
    context = json.loads(result.stdout)["hookSpecificOutput"]["additionalContext"]
    assert "Relevant skill available: python-patterns" in context
    assert "Skill card:" not in context
    assert "Step 1:" not in context


def test_user_prompt_submit_falls_back_to_hint_on_unreadable_skill_file(tmp_path: Path) -> None:
    library = make_card_library(tmp_path)
    (library / "local" / "skills" / "python-patterns" / "SKILL.md").unlink()
    env = hook_env(tmp_path, UNLIMITED_SKILLS_CLI=repo_cli_override(library))
    prompt = "review my python module for pep8 issues and idioms"
    result = run_hook(USER_PROMPT_SUBMIT, json.dumps({"prompt": prompt}), env)
    assert result.returncode == 0, result.stderr
    context = json.loads(result.stdout)["hookSpecificOutput"]["additionalContext"]
    assert "Relevant skill available: python-patterns" in context
    assert "Skill card:" not in context


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


def test_user_prompt_submit_instructs_english_requery_for_non_english(tmp_path: Path) -> None:
    # Non-English prompt: lexical finds nothing; with no sidecar the probe flags
    # needs_english_query and the hook injects the English-keywords instruction.
    library = make_library(tmp_path)
    env = hook_env(
        tmp_path,
        UNLIMITED_SKILLS_CLI=repo_cli_override(library),
        UNLIMITED_SKILLS_NO_VECTOR_FALLBACK="1",
    )
    prompt = "проверь безопасность кода и найди уязвимости в аутентификации"
    result = run_hook(USER_PROMPT_SUBMIT, json.dumps({"prompt": prompt}), env)
    assert result.returncode == 0, result.stderr
    context = json.loads(result.stdout)["hookSpecificOutput"]["additionalContext"]
    assert "English" in context and "unlimited-skills suggest" in context
    # Warns about the cold-load cost and states that daemon warming was triggered.
    assert "serve" in context and "background daemon" in context
    assert "approv" not in context.lower()
    assert "14" in context
    assert prompt not in context  # privacy: no raw prompt echo


def test_user_prompt_submit_instructs_english_requery_on_non_english_timeout(tmp_path: Path) -> None:
    sleeper = tmp_path / "sleeper.py"
    sleeper.write_text("import time\ntime.sleep(10)\n", encoding="utf-8")
    cli = f'"{Path(sys.executable).as_posix()}" "{sleeper.as_posix()}"'
    env = hook_env(tmp_path, UNLIMITED_SKILLS_CLI=cli, UNLIMITED_SKILLS_SUGGEST_TIMEOUT="0.5")
    prompt = "проверь безопасность кода и найди уязвимости"
    result = run_hook(USER_PROMPT_SUBMIT, json.dumps({"prompt": prompt}), env)
    assert result.returncode == 0
    context = json.loads(result.stdout)["hookSpecificOutput"]["additionalContext"]
    assert "English" in context and "unlimited-skills suggest" in context


@pytest.mark.parametrize(
    "event,script",
    [("SessionStart", "session_start.py"), ("UserPromptSubmit", "user_prompt_submit.py"), ("PreCompact", "pre_compact.py")],
)
def test_hook_manifest_registers_both_hooks(event: str, script: str) -> None:
    payload = json.loads((HOOKS_DIR / "hooks.json").read_text(encoding="utf-8"))
    entries = payload["hooks"][event]
    command = entries[0]["hooks"][0]["command"]
    assert script in command
    assert "${CLAUDE_PLUGIN_ROOT}" in command
    assert (HOOKS_DIR / script).is_file()


# --- SessionStart auto-heal of a stale launcher / inject -----------------------

def _load_session_start_module():
    import importlib.util

    spec = importlib.util.spec_from_file_location("uls_session_start_under_test", SESSION_START)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_session_start_constants_match_package() -> None:
    # The hook inlines the contract versions for a zero-import drift check; they
    # must never drift from the package source of truth.
    from unlimited_skills.agents_patch import CONTRACT_VERSION
    from unlimited_skills.launchers import LAUNCHER_CONTRACT_VERSION

    module = _load_session_start_module()
    assert module.LAUNCHER_CONTRACT_VERSION == LAUNCHER_CONTRACT_VERSION
    assert module.INJECT_CONTRACT_VERSION == CONTRACT_VERSION


_LEGACY_LAUNCHER_SH = (
    "#!/usr/bin/env bash\nset -euo pipefail\nexport PYTHONPATH=/old/repo\n"
    'exec /old/py -m unlimited_skills --root /old/lib "$@"\n'
)


def _install_stale_claude_launcher(tmp_path: Path) -> Path:
    scripts = tmp_path / "claude-home" / "skills" / "unlimited-skills" / "scripts"
    scripts.mkdir(parents=True)
    (tmp_path / "claude-home" / "skills" / "unlimited-skills" / "SKILL.md").write_text(
        "---\nname: unlimited-skills\n---\nrouter\n", encoding="utf-8"
    )
    (scripts / "unlimited-skills.sh").write_text(_LEGACY_LAUNCHER_SH, encoding="utf-8")
    return scripts / "unlimited-skills.sh"


def _autoheal_env(tmp_path: Path, library: Path) -> dict[str, str]:
    env = hook_env(tmp_path, UNLIMITED_SKILLS_CLI=repo_cli_override(library))
    # Keep the heal hermetic: library root + project root under tmp, not the dev machine.
    env["UNLIMITED_SKILLS_HOME"] = str(tmp_path / "install-root")
    env["UNLIMITED_SKILLS_CLAUDE_PROJECT_ROOT"] = str(tmp_path / "proj")
    env["CLAUDE_HOME"] = str(tmp_path / "claude-home")
    return env


def test_session_start_autoheals_stale_launcher(tmp_path: Path) -> None:
    from unlimited_skills.launchers import LAUNCHER_CONTRACT_VERSION, parse_launcher_contract

    launcher = _install_stale_claude_launcher(tmp_path)
    assert parse_launcher_contract(launcher.read_text(encoding="utf-8")) == 0
    library = make_library(tmp_path)
    result = run_hook(SESSION_START, "", _autoheal_env(tmp_path, library))
    assert result.returncode == 0
    assert "TRIGGERS" in result.stdout  # contract still emitted
    assert parse_launcher_contract(launcher.read_text(encoding="utf-8")) == LAUNCHER_CONTRACT_VERSION
    assert "export PYTHONPATH=" not in launcher.read_text(encoding="utf-8")


def test_session_start_autoheal_kill_switch(tmp_path: Path) -> None:
    from unlimited_skills.launchers import parse_launcher_contract

    launcher = _install_stale_claude_launcher(tmp_path)
    library = make_library(tmp_path)
    env = _autoheal_env(tmp_path, library)
    env["UNLIMITED_SKILLS_NO_AUTOHEAL"] = "1"
    result = run_hook(SESSION_START, "", env)
    assert result.returncode == 0
    assert "TRIGGERS" in result.stdout
    assert parse_launcher_contract(launcher.read_text(encoding="utf-8")) == 0  # left stale
