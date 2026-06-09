from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SUPPORTED_CHANNELS = ("stable", "beta", "canary")
UNSUPPORTED_CHANNEL_PATTERNS = [
    re.compile(r"stable\s*[,/]\s*beta\s*[,/]\s*dev", re.IGNORECASE),
    re.compile(r"allowed_channels[^\n]+dev", re.IGNORECASE),
    re.compile(r"choices=\[[^\]]*['\"]dev['\"]", re.IGNORECASE),
    re.compile(r"release\s+pin\s+dev", re.IGNORECASE),
    re.compile(r"--channel\s+dev", re.IGNORECASE),
]
CHANNEL_SCAN_PATHS = [
    ROOT / "README.md",
    ROOT / "CHANGELOG.md",
    ROOT / "SECURITY.md",
    ROOT / "docs",
    ROOT / "scripts",
    ROOT / "tests",
    ROOT / "unlimited_skills",
]


def run(command: list[str]) -> None:
    print("+ " + " ".join(command), flush=True)
    subprocess.run(command, cwd=ROOT, check=True)


def iter_text_files(paths: list[Path]) -> list[Path]:
    files: list[Path] = []
    for path in paths:
        if path.is_file():
            files.append(path)
        elif path.is_dir():
            files.extend(
                item
                for item in path.rglob("*")
                if item.is_file() and item.suffix.lower() in {".md", ".py", ".json", ".yml", ".yaml", ".toml"}
            )
    return sorted(path for path in files if path.name != "run-v0.2.2-alpha-cross-repo-smoke.py")


def assert_channel_consistency() -> None:
    offenders: list[str] = []
    for path in iter_text_files(CHANNEL_SCAN_PATHS):
        text = path.read_text(encoding="utf-8", errors="replace")
        for pattern in UNSUPPORTED_CHANNEL_PATTERNS:
            if pattern.search(text):
                offenders.append(f"{path.relative_to(ROOT)}:{pattern.pattern}")
    if offenders:
        raise SystemExit("unsupported dev release-channel references found:\n" + "\n".join(offenders))
    print("channel naming decision: stable/beta/canary")
    print("unsupported dev release-channel references: none")


def assert_no_private_material_in_release_artifacts() -> None:
    patterns = {
        "pem_private_key": r"-----BEGIN [A-Z ]*PRIVATE KEY-----",
        "openssh_private_key": r"-----BEGIN OPENSSH PRIVATE KEY-----",
        "github_pat": r"gh[pousr]_[A-Za-z0-9_]{20,}",
        "openai_key": r"sk-[A-Za-z0-9_\-]{20,}",
        "raw_uls_token": r"uls_(?:hub|token|license)_[A-Za-z0-9_\-]{12,}",
        "device_private_key_assignment": r"device_private_key\s*[:=]\s*[A-Za-z0-9_\-]{12,}",
    }
    release_files = list((ROOT / "docs" / "releases").glob("v0.2.2-alpha*")) + [
        ROOT / "README.md",
        ROOT / "SECURITY.md",
        ROOT / "CHANGELOG.md",
    ]
    offenders: list[str] = []
    for path in release_files:
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        for name, pattern in patterns.items():
            if re.search(pattern, text, re.IGNORECASE):
                offenders.append(f"{path.relative_to(ROOT)}:{name}")
    if offenders:
        raise SystemExit("possible private material in release artifacts:\n" + "\n".join(offenders))
    print("raw token/private key release scan: passed")


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the v0.2.2-alpha public/private registry integration smoke gate.")
    parser.add_argument("--registry-url", default="", help="Local private production registry URL.")
    parser.add_argument("--fixture-mode", action="store_true", help="Run against the bundled production registry fixture.")
    parser.add_argument("--temp-home", action="store_true", help="Kept for release checklist compatibility; child E2E always uses temp HOME.")
    args = parser.parse_args()

    if args.registry_url and args.fixture_mode:
        raise SystemExit("--registry-url and --fixture-mode are mutually exclusive")
    if not args.registry_url and not args.fixture_mode:
        raise SystemExit("Pass either --fixture-mode or --registry-url http://127.0.0.1:<port>.")

    assert_channel_consistency()
    assert_no_private_material_in_release_artifacts()

    if args.registry_url:
        run([sys.executable, "scripts/run-production-registry-contract-e2e.py", "--registry-url", args.registry_url.rstrip("/"), "--temp-home"])
    else:
        run([sys.executable, "scripts/run-production-registry-contract-e2e.py", "--fixture-mode", "--temp-home"])
    run([sys.executable, "scripts/verify-v0.2.2-alpha-release.py"])
    run([sys.executable, "scripts/verify-v0.2.2-alpha-publication.py"])

    print("cross-repo smoke passed")
    print("signed release channel verification: covered by production registry contract E2E")
    print("rollback smoke: covered by production registry contract E2E")
    print("production hosted calls: none")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
