from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path


WATCHED_LOCAL_DIRS = ("local", "registry")


def snapshot(root: Path) -> dict[str, list[str]]:
    data: dict[str, list[str]] = {}
    for name in WATCHED_LOCAL_DIRS:
        base = root / name
        if not base.exists():
            data[name] = []
            continue
        data[name] = sorted(str(path.relative_to(root)).replace("\\", "/") for path in base.rglob("*") if path.is_file())
    return data


def run(command: list[str], *, cwd: Path, env: dict[str, str]) -> None:
    print("+ " + " ".join(command), flush=True)
    subprocess.run(command, cwd=cwd, env=env, check=True)


def write_skill(root: Path, rel: str, name: str) -> None:
    path = root / rel / "SKILL.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"---\nname: {name}\ndescription: Upgrade smoke skill.\n---\n\n# {name}\n", encoding="utf-8")


def main() -> int:
    repo = Path(__file__).resolve().parents[1]
    with tempfile.TemporaryDirectory(prefix="uls-v022-upgrade-") as temp:
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
                "PYTHONPATH": str(repo),
            }
        )
        write_skill(library, "local/skills/v020-local", "v020-local")
        write_skill(library, "registry/ecc/skills/v020-registry", "v020-registry")
        (library / ".unlimited-skills-index.json").write_text(json.dumps({"version": "0.2.0", "skills": []}), encoding="utf-8")
        before = snapshot(library)

        run([sys.executable, "-m", "unlimited_skills.cli", "--root", str(library), "reindex", "--no-native-sync"], cwd=repo, env=env)
        run([sys.executable, "-m", "unlimited_skills.cli", "--root", str(library), "list", "--no-native-sync"], cwd=repo, env=env)
        run([sys.executable, "-m", "unlimited_skills.cli", "--root", str(library), "where", "v020-local", "--no-native-sync"], cwd=repo, env=env)
        after = snapshot(library)

    if before != after:
        raise SystemExit(f"upgrade smoke changed local/registry files unexpectedly: before={before} after={after}")
    print("upgrade smoke passed")
    print("synthetic source: v0.2.0-style registry/local library")
    print("destructive migration: not observed")
    print("production hosted calls: none")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
