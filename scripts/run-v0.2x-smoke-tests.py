from __future__ import annotations

import argparse
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path


WATCHED_HOME_DIRS = (
    ".unlimited-skills",
    ".hermes",
    ".codex/skills",
    ".codex/.unlimited-skills",
)
VOLATILE_HOME_FILES = {
    ".unlimited-skills/library/.learning/events.jsonl",
    ".unlimited-skills/library/.unlimited-skills-index.json",
    ".codex/.unlimited-skills/library/.learning/events.jsonl",
    ".codex/.unlimited-skills/library/.unlimited-skills-index.json",
}


def _is_volatile_home_file(home: Path, path: Path) -> bool:
    try:
        rel = path.relative_to(home).as_posix()
    except ValueError:
        return False
    return rel in VOLATILE_HOME_FILES


def snapshot_real_home(home: Path) -> dict[str, tuple[bool, dict[str, int]]]:
    snapshot: dict[str, tuple[bool, dict[str, int]]] = {}
    for name in WATCHED_HOME_DIRS:
        path = home / name
        if not path.exists():
            snapshot[name] = (False, {})
            continue
        files: dict[str, int] = {}
        for item in path.rglob("*"):
            if not item.is_file():
                continue
            if _is_volatile_home_file(home, item):
                continue
            rel = item.relative_to(home).as_posix()
            files[rel] = item.stat().st_size
        snapshot[name] = (True, files)
    return snapshot


def assert_real_home_unchanged(home: Path, before: dict[str, tuple[bool, dict[str, int]]]) -> None:
    after = snapshot_real_home(home)
    changed: list[str] = []
    for name, old in before.items():
        new = after.get(name, (False, {}))
        old_exists, old_files = old
        new_exists, new_files = new
        if old_exists != new_exists or old_files != new_files:
            changed.append(name)
    if changed:
        raise SystemExit(f"Smoke suite appears to have mutated real HOME entries: {', '.join(changed)}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run v0.2.x release smoke tests in an isolated HOME.")
    parser.add_argument("--pytest-args", default="", help="Extra arguments appended to pytest.")
    args = parser.parse_args(argv)

    repo = Path(__file__).resolve().parents[1]
    real_home = Path.home()
    before = snapshot_real_home(real_home)
    started = time.time()
    with tempfile.TemporaryDirectory(prefix="uls-v02x-smoke-") as temp:
        temp_root = Path(temp)
        smoke_home = temp_root / "home"
        smoke_library = temp_root / "library"
        smoke_home.mkdir(parents=True, exist_ok=True)
        env = os.environ.copy()
        env.update(
            {
                "HOME": str(smoke_home),
                "USERPROFILE": str(smoke_home),
                "CODEX_HOME": str(smoke_home / ".codex"),
                "CLAUDE_HOME": str(smoke_home / ".claude"),
                "OPENCLAW_HOME": str(smoke_home / ".openclaw"),
                "UNLIMITED_SKILLS_HOME": str(smoke_home / ".unlimited-skills"),
                "UNLIMITED_SKILLS_SMOKE_ROOT": str(smoke_library),
                "UNLIMITED_SKILLS_DISABLE_NATIVE_SYNC": "1",
                "HERMES_HOME": str(smoke_home / ".hermes"),
                "PYTHONPATH": str(repo),
            }
        )
        command = [sys.executable, "-m", "pytest", "tests/smoke/test_v02x_release_smoke.py", "-q"]
        if args.pytest_args:
            command.extend(args.pytest_args.split())
        print("Running v0.2.x smoke suite", flush=True)
        print(f"Repo: {repo}", flush=True)
        print(f"Temp HOME: {smoke_home}", flush=True)
        print(f"Temp library: {smoke_library}", flush=True)
        print("Production hosted registry calls: disabled by tests", flush=True)
        completed = subprocess.run(command, cwd=repo, env=env, check=False)
    assert_real_home_unchanged(real_home, before)
    elapsed = time.time() - started
    print(f"Smoke suite finished in {elapsed:.1f}s with exit code {completed.returncode}")
    return int(completed.returncode)


if __name__ == "__main__":
    raise SystemExit(main())
