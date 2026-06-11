from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def run(command: list[str]) -> None:
    print("+ " + " ".join(command), flush=True)
    completed = subprocess.run(command, cwd=ROOT, text=True, encoding="utf-8", errors="replace")
    if completed.returncode != 0:
        raise SystemExit(completed.returncode)


def current_sha() -> str:
    completed = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    return completed.stdout.strip()


def run_cli(command: list[str], *, cwd: Path = ROOT) -> subprocess.CompletedProcess[str]:
    completed = subprocess.run(
        [sys.executable, "-m", "unlimited_skills.cli", *command],
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    return completed


def assert_usage_snapshot_cli() -> None:
    with tempfile.TemporaryDirectory(prefix="uls-v041-reliability-") as temp_name:
        temp = Path(temp_name)
        root = temp / "library"
        out = temp / "usage-snapshot.json"
        result = run_cli(["--root", str(root), "skillops", "usage-snapshot", "--json", "--out", str(out)])
        payload = json.loads(result.stdout)
        if payload.get("schema_version") != 1 or payload.get("snapshot_type") != "skillops-usage-snapshot":
            raise SystemExit("usage-snapshot JSON proof failed")
        if not out.is_file():
            raise SystemExit("usage-snapshot --out proof failed")
        explain = run_cli(["--root", str(root), "skillops", "usage-snapshot", "explain"])
        explain_text = explain.stdout.lower()
        if "local-only" not in explain_text or "does not call hosted services" not in explain_text:
            raise SystemExit("usage-snapshot explain proof failed")
        print("usage-snapshot command proof: passed", flush=True)


def main() -> int:
    sha = current_sha()
    print("Running v0.4.1-alpha reliability smoke", flush=True)
    run([sys.executable, "-m", "pytest", "tests/test_install_rollback.py", "tests/test_vector_sidecar.py", "tests/test_skillops_usage_snapshot.py", "tests/test_support_bundle.py", "-q"])
    assert_usage_snapshot_cli()
    run([sys.executable, "scripts/verify-v041-alpha-reliability.py", "--expected-sha", sha, "--allow-newer-package"])
    print("v0.4.1-alpha reliability smoke passed", flush=True)
    print(f"tag target sha: {sha}", flush=True)
    print("production hosted calls: not used", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
