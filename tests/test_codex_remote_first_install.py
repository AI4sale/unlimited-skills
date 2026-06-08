from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]


def test_codex_powershell_installer_generates_remote_first_router_without_raw_token(tmp_path: Path) -> None:
    powershell = shutil.which("powershell") or shutil.which("powershell.exe") or shutil.which("pwsh") or shutil.which("pwsh.exe")
    if not powershell:
        pytest.skip("PowerShell is not available in this environment.")

    codex_home = tmp_path / ".codex"
    install_root = codex_home / ".unlimited-skills"
    raw_token = "uls_hub_codex_secret"
    completed = subprocess.run(
        [
            powershell,
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(ROOT / "scripts" / "install-codex.ps1"),
            "-RepoRoot",
            str(ROOT),
            "-CodexHome",
            str(codex_home),
            "-InstallRoot",
            str(install_root),
            "-Python",
            sys.executable,
            "-SkipPipInstall",
            "-NoAgentsPatch",
            "-RemoteFirst",
            "-RemoteHubUrl",
            "http://127.0.0.1:8766",
            "-HubToken",
            raw_token,
            "-RemoteFallback",
            "hub_required",
        ],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )

    output = completed.stdout + completed.stderr
    assert completed.returncode == 0, output
    router_text = (codex_home / "skills" / "unlimited-skills" / "SKILL.md").read_text(encoding="utf-8")
    remote_config = json.loads((install_root / "remote.json").read_text(encoding="utf-8"))
    assert "remote resolve" in router_text
    assert "--agent codex" in router_text
    assert "hub_required" in router_text
    assert raw_token not in router_text
    assert raw_token not in output
    assert remote_config["token"] == raw_token
