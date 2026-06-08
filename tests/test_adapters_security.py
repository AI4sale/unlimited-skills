from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from unlimited_skills.adapters import install_pack, validate_pack_ref


def test_validate_pack_ref_rejects_git_option_injection() -> None:
    for ref in ("--upload-pack=calc", "-c", "../main", "feature..main", "refs/heads/main.lock"):
        with pytest.raises(RuntimeError):
            validate_pack_ref(ref)


def test_install_pack_rejects_unsafe_ref_before_git(tmp_path: Path) -> None:
    def fail_run(*args, **kwargs) -> subprocess.CompletedProcess[str]:
        raise AssertionError("git must not be invoked for an unsafe ref")

    with patch("subprocess.run", fail_run), pytest.raises(RuntimeError):
        install_pack(tmp_path / "library", "ecc", ref="--upload-pack=calc")


def test_validate_pack_ref_accepts_normal_branch_and_tag_refs() -> None:
    assert validate_pack_ref("main") == "main"
    assert validate_pack_ref("v0.2.0") == "v0.2.0"
    assert validate_pack_ref("feature/community-skills-v1") == "feature/community-skills-v1"
