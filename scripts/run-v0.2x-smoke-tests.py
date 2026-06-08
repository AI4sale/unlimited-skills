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


def snapshot_real_home(home: Path) -> dict[str, tuple[bool, int, float]]:
    snapshot: dict[str, tuple[bool, int, float]] = {}
    for name in WATCHED_HOME_DIRS:
        path = home / name
        if not path.exists():
            snapshot[name] = (False, 0, 0.0)
            continue
        files = [item for item in path.rglob("*") if item.is_file()]
        newest = max((item.stat().st_mtime for item in files), default=path.stat().st_mtime)
        snapshot[name] = (True, len(files), newest)
    return snapshot


def assert_real_home_unchanged(home: Path, before: dict[str, tuple[bool, int, float]]) -> None:
    after = snapshot_real_home(home)
    changed: list[str] = []
    for name, old in before.items():
        new = after.get(name, (False, 0, 0.0))
        old_exists, old_count, old_mtime = old
        new_exists, new_count, new_mtime = new
        if old_exists != new_exists or old_count != new_count or new_mtime > old_mtime + 0.001:
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
