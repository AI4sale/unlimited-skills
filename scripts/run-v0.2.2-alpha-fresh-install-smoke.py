from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path


def run(command: list[str], *, cwd: Path, env: dict[str, str]) -> None:
    print("+ " + " ".join(command), flush=True)
    subprocess.run(command, cwd=cwd, env=env, check=True)


def main() -> int:
    repo = Path(__file__).resolve().parents[1]
    with tempfile.TemporaryDirectory(prefix="uls-v022-fresh-") as temp:
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
        sample = library / "local" / "skills" / "fresh-smoke" / "SKILL.md"
        sample.parent.mkdir(parents=True)
        sample.write_text(
            "---\nname: fresh-smoke\ndescription: Fresh install smoke skill.\n---\n\n# fresh-smoke\n",
            encoding="utf-8",
        )
        run([sys.executable, "-m", "pip", "install", "-e", "."], cwd=repo, env=env)
        run([sys.executable, "-m", "unlimited_skills.cli", "--root", str(library), "reindex", "--no-native-sync"], cwd=repo, env=env)
        run([sys.executable, "-m", "unlimited_skills.cli", "--root", str(library), "search", "fresh smoke", "--mode", "lexical", "--no-native-sync"], cwd=repo, env=env)
        run([sys.executable, "-m", "unlimited_skills.cli", "--root", str(library), "view", "fresh-smoke", "--no-native-sync"], cwd=repo, env=env)
    print("fresh install smoke passed")
    print("production hosted calls: none")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
