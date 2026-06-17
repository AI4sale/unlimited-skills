from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from unlimited_skills import cli, suggest
from unlimited_skills.search_core import save_index

REPO_ROOT = Path(__file__).resolve().parents[1]
USER_PROMPT_SUBMIT = REPO_ROOT / "plugin" / "hooks" / "user_prompt_submit.py"

RU_LINKEDIN_PROMPT = "\u043d\u0430\u043f\u0438\u0448\u0438 \u043f\u043e\u0441\u0442 \u0434\u043b\u044f \u043b\u0438\u043d\u043a\u0435\u0434\u0438\u043d"
EN_LINKEDIN_RETRIEVAL_QUERY = "linkedin social content post marketing"
EXPECTED_LINKEDIN_FAMILY = {"marketing-campaign", "social-publisher", "content-engine"}


def _write_skill(root: Path, name: str, description: str, body: str = "") -> None:
    skill_dir = root / "registry" / "ecc" / name
    skill_dir.mkdir(parents=True, exist_ok=True)
    (skill_dir / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: {description}\n---\n\n# {name}\n\n{body}\n",
        encoding="utf-8",
    )


@pytest.fixture()
def linkedin_library(tmp_path: Path) -> Path:
    root = tmp_path / "library"
    _write_skill(root, "marketing-campaign", "Launch marketing campaigns, messaging, and GTM copy.")
    _write_skill(root, "social-publisher", "Publish social posts, LinkedIn updates, and replies.")
    _write_skill(root, "content-engine", "Plan and draft content posts, newsletters, and editorial assets.")
    save_index(root)
    return root


def _run_hook(prompt: str, root: Path, tmp_path: Path) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env["CLAUDE_HOME"] = str(tmp_path / "claude-home")
    env["UNLIMITED_SKILLS_INSTALL_ROOT"] = str(tmp_path / "install-root")
    env["UNLIMITED_SKILLS_NO_VECTOR_FALLBACK"] = "1"
    env["UNLIMITED_SKILLS_NO_AUTOSERVE"] = "1"
    env["UNLIMITED_SKILLS_CLI"] = f'"{Path(sys.executable).as_posix()}" -m unlimited_skills --root "{root.as_posix()}"'
    env["PYTHONPATH"] = str(REPO_ROOT) + os.pathsep + env.get("PYTHONPATH", "")
    return subprocess.run(
        [sys.executable, str(USER_PROMPT_SUBMIT)],
        input=json.dumps({"prompt": prompt}, ensure_ascii=False),
        capture_output=True,
        encoding="utf-8",
        errors="replace",
        env=env,
        timeout=60,
        cwd=str(REPO_ROOT),
    )


def test_direct_hybrid_retrieval_finds_linkedin_candidate_family(linkedin_library: Path) -> None:
    hits = cli.hybrid_search(
        linkedin_library,
        EN_LINKEDIN_RETRIEVAL_QUERY,
        limit=8,
        model=cli.DEFAULT_EMBED_MODEL,
    )
    names = {hit.name for hit in hits}
    assert EXPECTED_LINKEDIN_FAMILY <= names


@pytest.mark.xfail(
    strict=True,
    reason=(
        "C065-GATE-AUDIT-01: suggest can prove the library has the expected "
        "LinkedIn/social/content family via English retrieval, but raw "
        "non-English suggest still returns zero candidates."
    ),
)
def test_suggest_should_not_return_zero_when_retrieval_family_exists(
    linkedin_library: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    direct_names = {
        hit.name
        for hit in cli.hybrid_search(
            linkedin_library,
            EN_LINKEDIN_RETRIEVAL_QUERY,
            limit=8,
            model=cli.DEFAULT_EMBED_MODEL,
        )
    }
    assert EXPECTED_LINKEDIN_FAMILY <= direct_names

    rc = suggest.main([RU_LINKEDIN_PROMPT, "--root", str(linkedin_library), "--json", "--card", "--limit", "3"])
    payload = json.loads(capsys.readouterr().out)

    assert rc == 0
    candidate_names = {candidate["name"] for candidate in payload["top_3_skill_candidates"]}
    assert len(candidate_names) >= 3
    assert EXPECTED_LINKEDIN_FAMILY <= candidate_names


@pytest.mark.xfail(
    strict=True,
    reason=(
        "C065-GATE-AUDIT-01: UserPromptSubmit emits a non-English re-query "
        "instruction, not retrieved candidates, even when an equivalent "
        "English retrieval query has candidates."
    ),
)
def test_user_prompt_submit_should_deliver_candidates_when_retrieval_family_exists(
    linkedin_library: Path,
    tmp_path: Path,
) -> None:
    direct_names = {
        hit.name
        for hit in cli.hybrid_search(
            linkedin_library,
            EN_LINKEDIN_RETRIEVAL_QUERY,
            limit=8,
            model=cli.DEFAULT_EMBED_MODEL,
        )
    }
    assert EXPECTED_LINKEDIN_FAMILY <= direct_names

    result = _run_hook(RU_LINKEDIN_PROMPT, linkedin_library, tmp_path)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip(), "hook must inject retrieved candidates, not zero-candidate silence"
    context = json.loads(result.stdout)["hookSpecificOutput"]["additionalContext"]
    assert sum(1 for name in EXPECTED_LINKEDIN_FAMILY if name in context) >= 3
