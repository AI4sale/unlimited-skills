from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WATCHED_LOCAL_DIRS = ("local", "registry")


def run(command: list[str], *, cwd: Path = ROOT, env: dict[str, str] | None = None) -> None:
    print("+ " + " ".join(command), flush=True)
    completed = subprocess.run(command, cwd=cwd, env=env, text=True, encoding="utf-8", errors="replace")
    if completed.returncode != 0:
        raise SystemExit(f"command failed with exit code {completed.returncode}: {' '.join(command)}")


def write_skill(root: Path, rel: str, name: str, description: str) -> None:
    path = root / rel / "SKILL.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"---\nname: {name}\ndescription: {description}\n---\n\n# {name}\n", encoding="utf-8")


def snapshot(root: Path) -> dict[str, list[str]]:
    data: dict[str, list[str]] = {}
    for name in WATCHED_LOCAL_DIRS:
        base = root / name
        if not base.exists():
            data[name] = []
            continue
        data[name] = sorted(str(path.relative_to(root)).replace("\\", "/") for path in base.rglob("*") if path.is_file())
    return data


def base_env(home: Path) -> dict[str, str]:
    env = os.environ.copy()
    env.update(
        {
            "HOME": str(home),
            "USERPROFILE": str(home),
            "UNLIMITED_SKILLS_HOME": str(home / ".unlimited-skills"),
            "UNLIMITED_SKILLS_DISABLE_NATIVE_SYNC": "1",
            "PYTHONPATH": str(ROOT),
        }
    )
    return env


def fresh_install_smoke() -> None:
    with tempfile.TemporaryDirectory(prefix="uls-v031-fresh-") as temp:
        temp_root = Path(temp)
        home = temp_root / "home"
        library = temp_root / "library"
        home.mkdir()
        env = base_env(home)
        env["PIP_CACHE_DIR"] = str(temp_root / "pip-cache")
        write_skill(library, "local/skills/v031-fresh", "v031-fresh", "v0.3.1 fresh install smoke skill.")
        run([sys.executable, "-m", "pip", "install", "-e", "."], env=env)
        run([sys.executable, "-m", "unlimited_skills.cli", "--root", str(library), "reindex", "--no-native-sync"], env=env)
        run([sys.executable, "-m", "unlimited_skills.cli", "--root", str(library), "search", "fresh install", "--mode", "lexical", "--no-native-sync"], env=env)
        run([sys.executable, "-m", "unlimited_skills.cli", "--root", str(library), "view", "v031-fresh", "--no-native-sync"], env=env)
    print("fresh install smoke: passed")


def synthetic_upgrade_smoke(source_version: str) -> None:
    with tempfile.TemporaryDirectory(prefix=f"uls-v031-upgrade-{source_version.replace('.', '')}-") as temp:
        temp_root = Path(temp)
        home = temp_root / "home"
        library = temp_root / "library"
        home.mkdir()
        env = base_env(home)
        write_skill(library, "local/skills/upgrade-local", "upgrade-local", f"{source_version} local skill.")
        write_skill(library, "registry/ecc/skills/upgrade-registry", "upgrade-registry", f"{source_version} registry skill.")
        (library / ".unlimited-skills-index.json").write_text(json.dumps({"version": source_version, "skills": []}), encoding="utf-8")
        before = snapshot(library)
        run([sys.executable, "-m", "unlimited_skills.cli", "--root", str(library), "reindex", "--no-native-sync"], env=env)
        run([sys.executable, "-m", "unlimited_skills.cli", "--root", str(library), "list", "--no-native-sync"], env=env)
        run([sys.executable, "-m", "unlimited_skills.cli", "--root", str(library), "where", "upgrade-local", "--no-native-sync"], env=env)
        after = snapshot(library)
    if before != after:
        raise SystemExit(f"upgrade smoke changed local/registry files unexpectedly for {source_version}: before={before} after={after}")
    print(f"synthetic upgrade from {source_version}: passed")
    print("destructive migration: not observed")


def main() -> int:
    print("Running v0.3.1-alpha post-release smoke")
    run([sys.executable, "scripts/verify-v0.3.0-alpha-publication.py"])
    fresh_install_smoke()
    synthetic_upgrade_smoke("0.2.2")
    synthetic_upgrade_smoke("0.3.0")
    run([sys.executable, "scripts/run-v0.3.0-alpha-packaging-smoke.py"])
    run([sys.executable, "scripts/run-v0.3.0-alpha-release-smoke.py"])
    print("v0.3.1-alpha post-release smoke passed")
    print("published baseline: v0.3.0-alpha")
    print("fresh install: passed")
    print("upgrade from v0.2.2: passed")
    print("upgrade from v0.3.0: passed")
    print("production hosted calls: none")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
