from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path


def run(command: list[str], *, cwd: Path, env: dict[str, str]) -> str:
    print("+ " + " ".join(command), flush=True)
    completed = subprocess.run(command, cwd=cwd, env=env, check=True, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    if completed.stdout:
        print(completed.stdout, end="" if completed.stdout.endswith("\n") else "\n")
    return completed.stdout


def main() -> int:
    repo = Path(__file__).resolve().parents[1]
    with tempfile.TemporaryDirectory(prefix="uls-v030-packaging-") as temp:
        temp_root = Path(temp)
        home = temp_root / "home"
        library = temp_root / "library"
        home.mkdir()
        env = os.environ.copy()
        env.update(
            {
                "HOME": str(home),
                "USERPROFILE": str(home),
                "UNLIMITED_SKILLS_HOME": str(home / ".unlimited-skills"),
                "UNLIMITED_SKILLS_DISABLE_NATIVE_SYNC": "1",
                "PIP_CACHE_DIR": str(temp_root / "pip-cache"),
                "PYTHONPATH": str(repo),
            }
        )
        sample = library / "local" / "skills" / "packaging-smoke" / "SKILL.md"
        sample.parent.mkdir(parents=True)
        sample.write_text(
            "---\nname: packaging-smoke\ndescription: v0.3 packaging smoke skill.\n---\n\n# packaging-smoke\n",
            encoding="utf-8",
        )
        run([sys.executable, "scripts/verify-v0.3.0-alpha-package-assets.py"], cwd=repo, env=env)
        run([sys.executable, "-m", "pip", "install", "-e", "."], cwd=repo, env=env)
        version = run([sys.executable, "-m", "unlimited_skills.cli", "--version"], cwd=repo, env=env)
        if "0.3." not in version:
            raise SystemExit(f"unexpected CLI version output: {version}")
        run([sys.executable, "-m", "unlimited_skills.cli", "--root", str(library), "reindex", "--no-native-sync"], cwd=repo, env=env)
        run([sys.executable, "-m", "unlimited_skills.cli", "--root", str(library), "search", "packaging smoke", "--mode", "lexical", "--no-native-sync"], cwd=repo, env=env)
        run([sys.executable, "-m", "unlimited_skills.cli", "--root", str(library), "view", "packaging-smoke", "--no-native-sync"], cwd=repo, env=env)
    print("v0.3.0-alpha packaging smoke passed")
    print("production hosted calls: none")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
