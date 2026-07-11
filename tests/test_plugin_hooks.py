from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from types import ModuleType

import pytest

from unlimited_skills.search_core import save_index

REPO_ROOT = Path(__file__).resolve().parents[1]
HOOKS_DIR = REPO_ROOT / "plugin" / "hooks"
SESSION_START = HOOKS_DIR / "session_start.py"
USER_PROMPT_SUBMIT = HOOKS_DIR / "user_prompt_submit.py"
PRE_COMPACT = HOOKS_DIR / "pre_compact.py"
STOP = HOOKS_DIR / "stop.py"


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
    # Generic hook tests exercise retrieval, not process lifecycle. Autoserve
    # has focused unit tests below so the suite never starts real daemons.
    env["UNLIMITED_SKILLS_NO_AUTOSERVE"] = "1"
    # Generic hook tests must not inherit the developer machine's opt-in local
    # business provider. Focused provider tests explicitly enable their fixture.
    env["UNLIMITED_SKILLS_NO_BUSINESS_CONTEXT"] = "1"
    env.pop("UNLIMITED_SKILLS_CLI", None)
    env.update(overrides)
    return env


def load_user_prompt_module() -> ModuleType:
    name = f"_unlimited_skills_user_prompt_submit_{os.urandom(6).hex()}"
    spec = importlib.util.spec_from_file_location(name, USER_PROMPT_SUBMIT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_session_start_module() -> ModuleType:
    name = f"_unlimited_skills_session_start_{os.urandom(6).hex()}"
    spec = importlib.util.spec_from_file_location(name, SESSION_START)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


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


def test_user_prompt_submit_drops_stale_index_entry_when_skill_file_disappears(tmp_path: Path) -> None:
    library = make_card_library(tmp_path)
    (library / "local" / "skills" / "python-patterns" / "SKILL.md").unlink()
    env = hook_env(tmp_path, UNLIMITED_SKILLS_CLI=repo_cli_override(library))
    prompt = "review my python module for pep8 issues and idioms"
    result = run_hook(USER_PROMPT_SUBMIT, json.dumps({"prompt": prompt}), env)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == ""


def test_user_prompt_submit_is_silent_below_floor(tmp_path: Path) -> None:
    library = make_library(tmp_path)
    env = hook_env(tmp_path, UNLIMITED_SKILLS_CLI=repo_cli_override(library))
    payload = json.dumps({"prompt": "what is the capital of Australia please tell me"})
    result = run_hook(USER_PROMPT_SUBMIT, payload, env)
    assert result.returncode == 0
    assert result.stdout.strip() == ""


def test_user_prompt_submit_injects_business_context_without_a_skill(tmp_path: Path) -> None:
    library = make_library(tmp_path)
    provider = tmp_path / "provider.py"
    provider.write_text(
        """
import json, sys
r = json.load(sys.stdin)
print(json.dumps({
    "schema_version": "unlimited-skills.business-context-response.v1",
    "request_id": r["request_id"],
    "status": "ok",
    "items": [{
        "id": "offer",
        "title": "Approved offer",
        "excerpt": "Use the source-backed business offer.",
        "source_ref": "business/offers/approved.md",
        "sensitivity": "internal-sanitized"
    }]
}))
""",
        encoding="utf-8",
    )
    config = tmp_path / "provider.json"
    config.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "provider": {
                    "id": "fixture-memory",
                    "command": [sys.executable, str(provider)],
                    "capabilities": ["retrieve"],
                },
            }
        ),
        encoding="utf-8",
    )
    env = hook_env(
        tmp_path,
        UNLIMITED_SKILLS_CLI=repo_cli_override(library),
        UNLIMITED_SKILLS_CONTEXT_PROVIDER_CONFIG=str(config),
        UNLIMITED_SKILLS_NO_BUSINESS_CONTEXT="",
    )
    payload = json.dumps({"prompt": "tell me the capital of Australia for this customer please"})
    result = run_hook(USER_PROMPT_SUBMIT, payload, env)
    assert result.returncode == 0, result.stderr
    context = json.loads(result.stdout)["hookSpecificOutput"]["additionalContext"]
    assert "Approved offer" in context
    assert "business/offers/approved.md" in context
    assert "Relevant skill" not in context


def test_user_prompt_submit_no_context_never_claims_verified_absence(tmp_path: Path) -> None:
    library = make_library(tmp_path)
    provider = tmp_path / "provider.py"
    provider.write_text(
        "import json, sys\n"
        "r=json.load(sys.stdin)\n"
        "print(json.dumps({'schema_version':'unlimited-skills.business-context-response.v1',"
        "'request_id':r['request_id'],'status':'no_context','items':[],"
        "'diagnostics':{'daemon_state':'warming'}}))\n",
        encoding="utf-8",
    )
    config = tmp_path / "provider.json"
    config.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "provider": {
                    "id": "fixture-memory",
                    "command": [sys.executable, str(provider)],
                    "capabilities": ["retrieve"],
                },
            }
        ),
        encoding="utf-8",
    )
    env = hook_env(
        tmp_path,
        UNLIMITED_SKILLS_CLI=repo_cli_override(library),
        UNLIMITED_SKILLS_CONTEXT_PROVIDER_CONFIG=str(config),
        UNLIMITED_SKILLS_NO_BUSINESS_CONTEXT="",
    )
    result = run_hook(
        USER_PROMPT_SUBMIT,
        json.dumps({"prompt": "tell me whether this company policy exists for the current decision"}),
        env,
    )
    assert result.returncode == 0
    context = json.loads(result.stdout)["hookSpecificOutput"]["additionalContext"]
    assert "not a verified not-found result" in context
    assert 'authority="retrieval_only"' in context


def test_user_prompt_submit_never_hints_below_floor_diagnostics(tmp_path: Path) -> None:
    library = make_library(tmp_path)
    gardening = library / "local" / "skills" / "gardening-basics"
    gardening.mkdir(parents=True)
    (gardening / "SKILL.md").write_text(
        "---\nname: gardening-basics\ndescription: Watering schedules for houseplants.\n---\n",
        encoding="utf-8",
    )
    save_index(library)
    env = hook_env(tmp_path, UNLIMITED_SKILLS_CLI=repo_cli_override(library))
    result = run_hook(
        USER_PROMPT_SUBMIT,
        json.dumps({"prompt": "python code review watering"}),
        env,
    )
    assert result.returncode == 0, result.stderr
    context = json.loads(result.stdout)["hookSpecificOutput"]["additionalContext"]
    assert "python-patterns" in context
    assert "gardening-basics" not in context


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
    assert "UNLIMITED_SKILLS_NO_AUTOSERVE" in context
    assert prompt not in context  # privacy: no raw prompt echo


def test_user_prompt_submit_autoserve_starts_missing_local_daemon(monkeypatch: pytest.MonkeyPatch) -> None:
    module = load_user_prompt_module()
    calls: list[tuple[list[str], dict]] = []
    monkeypatch.delenv("UNLIMITED_SKILLS_NO_AUTOSERVE", raising=False)
    endpoint = ("127.0.0.1", 8765, "http://127.0.0.1:8765")
    monkeypatch.setattr(module, "_daemon_state", lambda command, endpoint=None: "missing")
    monkeypatch.setattr(module, "_daemon_endpoints", lambda command: [endpoint])
    monkeypatch.setattr(module, "_claim_daemon_launch", lambda command, url: (True, None))
    monkeypatch.setattr(module, "_write_daemon_state", lambda *args, **kwargs: None)
    monkeypatch.setattr(module.subprocess, "Popen", lambda command, **kwargs: calls.append((command, kwargs)))

    state = module._ensure_warm_daemon(["unlimited-skills"])

    assert state == "starting"
    assert len(calls) == 1
    assert calls[0][0] == [
        "unlimited-skills", "serve", "--host", "127.0.0.1", "--port", "8765", "--log-level", "warning"
    ]
    assert calls[0][1]["stdin"] is subprocess.DEVNULL
    assert calls[0][1]["stdout"] is subprocess.DEVNULL
    assert calls[0][1]["stderr"] is subprocess.DEVNULL
    assert calls[0][1].get("start_new_session") is True or calls[0][1].get("creationflags", 0) != 0


@pytest.mark.parametrize("state", ["ready", "incompatible", "external_or_invalid"])
def test_user_prompt_submit_autoserve_never_replaces_running_or_refused_endpoint(
    monkeypatch: pytest.MonkeyPatch, state: str
) -> None:
    module = load_user_prompt_module()
    monkeypatch.delenv("UNLIMITED_SKILLS_NO_AUTOSERVE", raising=False)
    monkeypatch.setattr(module, "_daemon_state", lambda command, endpoint=None: state)
    monkeypatch.setattr(module, "_daemon_endpoints", lambda command: [("127.0.0.1", 8765, "http://127.0.0.1:8765")])
    monkeypatch.setattr(
        module.subprocess,
        "Popen",
        lambda *args, **kwargs: pytest.fail(f"unexpected daemon launch for {state}"),
    )

    assert module._ensure_warm_daemon(["unlimited-skills"]) == state


def test_user_prompt_submit_autoserve_cooldown_prevents_spawn_storm(monkeypatch: pytest.MonkeyPatch) -> None:
    module = load_user_prompt_module()
    monkeypatch.delenv("UNLIMITED_SKILLS_NO_AUTOSERVE", raising=False)
    endpoint = ("127.0.0.1", 8765, "http://127.0.0.1:8765")
    monkeypatch.setattr(module, "_daemon_state", lambda command, endpoint=None: "missing")
    monkeypatch.setattr(module, "_daemon_endpoints", lambda command: [endpoint])
    monkeypatch.setattr(module, "_claim_daemon_launch", lambda command, url: (False, Path("launch")))
    monkeypatch.setattr(
        module.subprocess,
        "Popen",
        lambda *args, **kwargs: pytest.fail("cooldown must suppress duplicate daemon launch"),
    )

    assert module._ensure_warm_daemon(["unlimited-skills"]) == "warming"


def test_user_prompt_submit_autoserve_emergency_override(monkeypatch: pytest.MonkeyPatch) -> None:
    module = load_user_prompt_module()
    monkeypatch.setenv("UNLIMITED_SKILLS_NO_AUTOSERVE", "1")
    monkeypatch.setattr(module, "_daemon_state", lambda *args: pytest.fail("disabled autoserve must not probe the port"))
    monkeypatch.setattr(module.subprocess, "Popen", lambda *args, **kwargs: pytest.fail("autoserve is disabled"))

    assert module._ensure_warm_daemon(["unlimited-skills"]) == "disabled"


@pytest.mark.parametrize(
    "url",
    [
        "https://127.0.0.1:8765",
        "http://example.com:8765",
        "http://user:pass@127.0.0.1:8765",
        "http://127.0.0.1:8765/nested",
        "http://127.0.0.1:8765?next=remote",
    ],
)
def test_user_prompt_submit_autoserve_rejects_non_local_or_malformed_endpoint(
    monkeypatch: pytest.MonkeyPatch, url: str
) -> None:
    module = load_user_prompt_module()
    monkeypatch.setenv("UNLIMITED_SKILLS_WARM_DAEMON_URL", url)
    assert module._daemon_endpoint(["unlimited-skills"]) is None


def test_user_prompt_submit_autoserve_requires_matching_root_and_model(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    module = load_user_prompt_module()
    root = tmp_path / "library"
    command = ["unlimited-skills", "--root", str(root)]
    payload = {
        "ok": True,
        "service": "unlimited-skills",
        "protocol": "warm-search-v1",
        "runtime_contract_version": module.RUNTIME_CONTRACT_VERSION,
        "root": str(root),
        "model": module.DEFAULT_EMBED_MODEL,
    }

    assert module._daemon_identity_matches(payload, command) is True
    assert module._daemon_identity_matches({**payload, "root": str(tmp_path / "other")}, command) is False
    assert module._daemon_identity_matches({**payload, "model": "wrong-model"}, command) is False


def test_autoserve_rolls_over_from_legacy_listener_to_versioned_fallback(
    monkeypatch: pytest.MonkeyPatch
) -> None:
    module = load_user_prompt_module()
    preferred = ("127.0.0.1", 8765, "http://127.0.0.1:8765")
    fallback = ("127.0.0.1", 20555, "http://127.0.0.1:20555")
    launched: list[list[str]] = []
    monkeypatch.delenv("UNLIMITED_SKILLS_NO_AUTOSERVE", raising=False)
    monkeypatch.setattr(module, "_daemon_endpoints", lambda command: [preferred, fallback])
    monkeypatch.setattr(
        module,
        "_daemon_state",
        lambda command, endpoint=None: "incompatible" if endpoint == preferred else "missing",
    )
    monkeypatch.setattr(module, "_claim_daemon_launch", lambda command, url: (True, None))
    monkeypatch.setattr(module, "_write_daemon_state", lambda *args, **kwargs: None)
    monkeypatch.setattr(module.subprocess, "Popen", lambda command, **kwargs: launched.append(command))

    assert module._ensure_warm_daemon(["unlimited-skills"]) == "starting"
    assert launched[0][-6:] == ["--host", "127.0.0.1", "--port", "20555", "--log-level", "warning"]


def test_user_prompt_submit_derives_distinct_ports_for_distinct_roots(tmp_path: Path) -> None:
    from unlimited_skills.daemon_endpoint import warm_daemon_url

    module = load_user_prompt_module()
    first = tmp_path / "first" / "library"
    second = tmp_path / "second" / "library"
    first_url = module._daemon_endpoint(["unlimited-skills", "--root", str(first)])[2]
    second_url = module._daemon_endpoint(["unlimited-skills", "--root", str(second)])[2]

    assert first_url == warm_daemon_url(first)
    assert second_url == warm_daemon_url(second)
    assert first_url != second_url


def test_session_start_primary_daemon_ensure_runs_before_contract(
    monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    module = load_session_start_module()
    calls: list[list[str]] = []
    command = ["unlimited-skills"]
    monkeypatch.setattr(module, "resolve_cli_command", lambda: command)
    monkeypatch.setattr(module, "_ensure_lexical_index_manifest", lambda value: "ready")
    monkeypatch.setattr(module, "_ensure_warm_daemon", lambda value: calls.append(value) or "starting")
    monkeypatch.setattr(module, "_maybe_autoheal", lambda value: None)
    monkeypatch.setattr(module, "_record_money_event", lambda *args: None)

    assert module.main() == 0
    assert calls == [command]
    assert "Unlimited Skills Library" in capsys.readouterr().out


def test_session_start_primes_configured_business_provider_detached(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = load_session_start_module()
    config = tmp_path / "provider.json"
    config.write_text("{}", encoding="utf-8")
    monkeypatch.setenv("UNLIMITED_SKILLS_CONTEXT_PROVIDER_CONFIG", str(config))
    monkeypatch.delenv("UNLIMITED_SKILLS_NO_BUSINESS_CONTEXT", raising=False)
    calls = []
    monkeypatch.setattr(module.subprocess, "Popen", lambda command, **kwargs: calls.append((command, kwargs)))
    state = module._prime_business_context(["python", "-m", "unlimited_skills"])
    assert state == "starting"
    assert calls[0][0][-3:] == ["context", "doctor", "--json"]
    assert calls[0][1]["stdout"] is subprocess.DEVNULL


def test_hook_starts_detached_reindex_for_legacy_index_without_manifest(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    module = load_user_prompt_module()
    root = tmp_path / "library"
    root.mkdir()
    (root / module.LEXICAL_INDEX_NAME).write_text("[]", encoding="utf-8")
    command = ["unlimited-skills", "--root", str(root)]
    launched: list[tuple[list[str], dict]] = []
    monkeypatch.setattr(module, "_claim_daemon_launch", lambda *_args: (True, None))
    monkeypatch.setattr(module.subprocess, "Popen", lambda args, **kwargs: launched.append((args, kwargs)))

    assert module._ensure_lexical_index_manifest(command) == "started"
    assert launched[0][0] == [*command, "reindex", "--no-native-sync"]
    assert launched[0][1]["stdin"] is subprocess.DEVNULL
    assert launched[0][1].get("start_new_session") is True or launched[0][1].get("creationflags", 0) != 0


def test_hook_does_not_reindex_when_manifest_exists(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    module = load_user_prompt_module()
    root = tmp_path / "library"
    root.mkdir()
    (root / module.LEXICAL_INDEX_NAME).write_text("[]", encoding="utf-8")
    (root / module.LEXICAL_INDEX_MANIFEST_NAME).write_text("{}", encoding="utf-8")
    monkeypatch.setattr(
        module.subprocess,
        "Popen",
        lambda *_args, **_kwargs: pytest.fail("a manifest-backed index must not trigger repair"),
    )
    assert module._ensure_lexical_index_manifest(["unlimited-skills", "--root", str(root)]) == "ready"


def test_autoserve_launch_claim_is_cross_process_idempotent(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    module = load_user_prompt_module()
    monkeypatch.setenv("UNLIMITED_SKILLS_HOME", str(tmp_path / "home"))
    command = ["unlimited-skills", "--root", str(tmp_path / "library")]
    url = module._daemon_endpoint(command)[2]

    first, marker = module._claim_daemon_launch(command, url)
    second, same_marker = module._claim_daemon_launch(command, url)

    assert first is True
    assert second is False
    assert marker == same_marker
    assert marker is not None and marker.is_file()


def test_daemon_running_state_preserves_started_pid(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    module = load_user_prompt_module()
    monkeypatch.setenv("UNLIMITED_SKILLS_HOME", str(tmp_path / "home"))
    command = ["unlimited-skills", "--root", str(tmp_path / "library")]
    url = module._daemon_endpoint(command)[2]

    module._write_daemon_state(command, url, "starting", 4321)
    module._write_daemon_state(command, url, "running")

    state_path = module._launch_marker(command, url).with_suffix(".json")
    state = json.loads(state_path.read_text(encoding="utf-8"))
    assert state["status"] == "running"
    assert state["pid"] == 4321


def test_user_prompt_submit_rescues_mixed_language_weak_match(tmp_path: Path) -> None:
    library = make_library(tmp_path)
    for index in range(8):
        decoy = library / "local" / "skills" / f"decoy-{index}" / "SKILL.md"
        decoy.parent.mkdir(parents=True)
        decoy.write_text(
            f"---\nname: decoy-{index}\ndescription: Unrelated fixture topic {index}.\n---\n",
            encoding="utf-8",
        )
    save_index(library)
    env = hook_env(
        tmp_path,
        UNLIMITED_SKILLS_CLI=repo_cli_override(library),
        UNLIMITED_SKILLS_NO_VECTOR_FALLBACK="1",
    )
    prompt = "проверить python api"
    result = run_hook(USER_PROMPT_SUBMIT, json.dumps({"prompt": prompt}), env)
    assert result.returncode == 0, result.stderr
    context = json.loads(result.stdout)["hookSpecificOutput"]["additionalContext"]
    assert "English" in context and "unlimited-skills suggest" in context
    assert "Relevant skill available: python-patterns" in context


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
    [
        ("SessionStart", "session_start.py"),
        ("UserPromptSubmit", "user_prompt_submit.py"),
        ("PreCompact", "pre_compact.py"),
        ("Stop", "stop.py"),
    ],
)
def test_hook_manifest_registers_both_hooks(event: str, script: str) -> None:
    payload = json.loads((HOOKS_DIR / "hooks.json").read_text(encoding="utf-8"))
    entries = payload["hooks"][event]
    command = entries[0]["hooks"][0]["command"]
    assert script in command
    assert "${CLAUDE_PLUGIN_ROOT}" in command
    assert (HOOKS_DIR / script).is_file()


def test_stop_hook_never_promotes_model_written_prose_to_memory(tmp_path: Path) -> None:
    captured = tmp_path / "candidate.json"
    stub = tmp_path / "stub_cli.py"
    stub.write_text(
        "import pathlib, sys\n"
        f"pathlib.Path({str(captured)!r}).write_text(sys.stdin.read(), encoding='utf-8')\n",
        encoding="utf-8",
    )
    env = hook_env(
        tmp_path,
        UNLIMITED_SKILLS_CLI=f'"{Path(sys.executable).as_posix()}" "{stub.as_posix()}"',
        UNLIMITED_SKILLS_CONTEXT_PROVIDER_CONFIG=str(stub),
        UNLIMITED_SKILLS_NO_BUSINESS_CONTEXT="",
    )
    final = (
        "Completed release 0.6.7 in PR #240 at commit 6c8a2b7. "
        "Verification finished with 120 tests passed and the public artifact checked."
    )
    payload = {
        "hook_event_name": "Stop",
        "session_id": "raw-session-must-not-leak",
        "prompt_id": "raw-prompt-must-not-leak",
        "cwd": str(tmp_path),
        "stop_hook_active": False,
        "last_assistant_message": final,
        "background_tasks": [],
        "session_crons": [],
    }
    result = run_hook(STOP, json.dumps(payload), env)
    assert result.returncode == 0
    assert not captured.exists()


@pytest.mark.parametrize(
    "overrides",
    [
        {"stop_hook_active": True},
        {"background_tasks": [{"id": "still-running"}]},
        {"session_crons": [{"id": "wake-later"}]},
        {"last_assistant_message": "Short status"},
        {"last_assistant_message": "Completed and published the requested change in PR #240, but no independent checker result is available yet."},
    ],
)
def test_stop_hook_does_not_submit_non_final_or_recursive_turns(tmp_path: Path, overrides: dict) -> None:
    captured = tmp_path / "candidate.json"
    stub = tmp_path / "stub_cli.py"
    stub.write_text(
        "import pathlib, sys\n"
        f"pathlib.Path({str(captured)!r}).write_text(sys.stdin.read(), encoding='utf-8')\n",
        encoding="utf-8",
    )
    env = hook_env(
        tmp_path,
        UNLIMITED_SKILLS_CLI=f'"{Path(sys.executable).as_posix()}" "{stub.as_posix()}"',
        UNLIMITED_SKILLS_CONTEXT_PROVIDER_CONFIG=str(stub),
        UNLIMITED_SKILLS_NO_BUSINESS_CONTEXT="",
    )
    payload = {
        "hook_event_name": "Stop",
        "session_id": "session",
        "prompt_id": "prompt",
        "cwd": str(tmp_path),
        "stop_hook_active": False,
        "last_assistant_message": "Completed a sufficiently long task outcome with concrete verification evidence and a durable result.",
        "background_tasks": [],
        "session_crons": [],
        **overrides,
    }
    result = run_hook(STOP, json.dumps(payload), env)
    assert result.returncode == 0
    assert not captured.exists()


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
