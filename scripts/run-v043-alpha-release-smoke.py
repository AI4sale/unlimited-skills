from __future__ import annotations

import subprocess
import sys
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


def tag_target(tag: str) -> str | None:
    completed = subprocess.run(
        ["git", "rev-parse", "--verify", "--quiet", f"{tag}^{{commit}}"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if completed.returncode != 0:
        return None
    return completed.stdout.strip()


def main() -> int:
    sha = current_sha()
    published_tag_sha = tag_target("v0.4.3-alpha")
    print("Running v0.4.3-alpha MCP upstream enforcement publication smoke", flush=True)
    run([sys.executable, "scripts/run-v0.2x-smoke-tests.py"])
    run([sys.executable, "scripts/run-v042-alpha-release-smoke.py"])
    run([sys.executable, "scripts/run-v043-alpha-mcp-enforcement-smoke.py", "--fixture-mode", "--json"])
    run(
        [
            sys.executable,
            "scripts/verify-v043-alpha-mcp-enforcement.py",
            "--expected-sha",
            sha,
            "--allow-newer-package",
        ]
    )
    publication_command = [
        sys.executable,
        "scripts/verify-v043-alpha-publication.py",
        "--expected-sha",
        sha,
        "--allow-newer-package",
    ]
    if published_tag_sha:
        publication_command.extend(
            [
                "--allow-existing-tag",
                "--expected-tag-sha",
                published_tag_sha,
            ]
        )
    run(publication_command)
    print("v0.4.3-alpha MCP upstream enforcement publication smoke passed", flush=True)
    print(f"tag target sha: {sha}", flush=True)
    if published_tag_sha:
        print(f"published v0.4.3-alpha tag target sha: {published_tag_sha}", flush=True)
        print("tag status: already published by Codex after verifier", flush=True)
    else:
        print("tag status: pending Codex publication after verifier", flush=True)
    print("production hosted calls: blocked by fixture-mode release commands", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
