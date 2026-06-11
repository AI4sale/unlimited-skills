from __future__ import annotations

import argparse
import json
import re
import subprocess
import tomllib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RELEASE = "v0.4.1-alpha"
VERSION = "0.4.1"
MANIFEST = ROOT / "docs" / "releases" / "v0.4.1-alpha.release-manifest.json"
RELEASE_DOCS = [
    ROOT / "docs" / "releases" / "v0.4.1-alpha.md",
    ROOT / "docs" / "releases" / "v0.4.1-alpha-checklist.md",
    ROOT / "docs" / "releases" / "v0.4.1-alpha-upgrade-notes.md",
    ROOT / "docs" / "releases" / "v0.4.1-alpha-known-issues.md",
    MANIFEST,
]
PUBLIC_DOCS = RELEASE_DOCS + [ROOT / "README.md", ROOT / "SECURITY.md", ROOT / "CHANGELOG.md"]
PRIVATE_MATERIAL_PATTERNS = {
    "pem_private_key": r"-----BEGIN [A-Z ]*PRIVATE KEY-----",
    "openssh_private_key": r"-----BEGIN OPENSSH PRIVATE KEY-----",
    "github_pat": r"gh[pousr]_[A-Za-z0-9_]{20,}",
    "openai_key": r"sk-[A-Za-z0-9_\-]{20,}",
    "raw_uls_token": r"uls_(?:hub|token|license)_[A-Za-z0-9_\-]{16,}",
    "prompt_body_field": r'"(?:prompt|prompts|task_text|customer_data)"\s*:\s*"[^"]+"',
}


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def fail(message: str) -> None:
    raise SystemExit(f"{RELEASE} publication verification failed: {message}")


def require(condition: bool, message: str) -> None:
    if not condition:
        fail(message)


def run_git(args: list[str], check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=ROOT,
        check=check,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )


def package_version() -> str:
    return str(tomllib.loads(read(ROOT / "pyproject.toml"))["project"]["version"])


def init_version() -> str:
    match = re.search(r'__version__\s*=\s*"([^"]+)"', read(ROOT / "unlimited_skills" / "__init__.py"))
    require(match is not None, "__version__ is missing")
    return str(match.group(1))


def plugin_versions() -> tuple[str, str]:
    plugin = json.loads(read(ROOT / "plugin" / ".claude-plugin" / "plugin.json"))
    marketplace = json.loads(read(ROOT / ".claude-plugin" / "marketplace.json"))
    return str(plugin["version"]), str(marketplace["plugins"][0]["version"])


def git_head() -> str:
    return run_git(["rev-parse", "HEAD"]).stdout.strip()


def tag_exists(tag: str) -> bool:
    return run_git(["rev-parse", "--verify", "--quiet", f"refs/tags/{tag}"], check=False).returncode == 0


def assert_clean_worktree() -> None:
    status = run_git(["status", "--short"]).stdout.strip()
    require(not status, "working tree must be clean before publication verification")


def assert_manifest() -> None:
    require(MANIFEST.is_file(), f"missing release manifest: {MANIFEST.relative_to(ROOT)}")
    payload = json.loads(read(MANIFEST))
    require(payload.get("release") == RELEASE, "manifest release mismatch")
    require(payload.get("package_version") == VERSION, "manifest package version mismatch")
    require(payload.get("distribution") == "github-clone-alpha", "GitHub clone must remain distribution path")
    git = payload.get("git") if isinstance(payload.get("git"), dict) else {}
    require(git.get("publication_branch") == "release/v0.4.1-alpha-reliability-publication", "publication branch mismatch")
    require(git.get("tag") == RELEASE, "manifest tag mismatch")
    require(git.get("tag_status") == "pending_release_owner_approval", "manifest must require release-owner tag approval")
    prs = payload.get("required_prs", {}) if isinstance(payload.get("required_prs"), dict) else {}
    public_numbers = [item.get("number") for item in prs.get("public", []) if isinstance(item, dict)]
    for number in (82, 83):
        require(number in public_numbers, f"manifest missing public PR #{number}")
    boundary = payload.get("safety_boundary", {}) if isinstance(payload.get("safety_boundary"), dict) else {}
    require(boundary.get("mit_local_core_registration_free") is True, "MIT local core must remain registration-free")
    for key in (
        "production_rollout",
        "production_hosted_calls",
        "automatic_telemetry",
        "automatic_rewriting",
        "auto_publish",
        "live_billing",
        "pypi",
        "full_catalog_distribution",
        "codex_pushes_tag",
    ):
        require(boundary.get(key) is False, f"safety boundary must disable {key}")


def assert_docs() -> None:
    for path in RELEASE_DOCS:
        require(path.is_file(), f"missing release doc: {path.relative_to(ROOT)}")
    text = "\n".join(read(path) for path in PUBLIC_DOCS if path.exists()).lower()
    for required in (
        "v0.4.1-alpha",
        "transactional install",
        "rollback manifest",
        "vectormodelmismatch",
        "cli split",
        "skillops usage-snapshot",
        "release owner",
        "no production hosted calls",
        "no live billing",
        "no pypi",
        "no full catalog distribution",
        "no automatic telemetry",
        "no automatic rewriting",
        "no auto-publish",
    ):
        require(required in text, f"docs missing required wording: {required}")


def assert_no_private_material() -> None:
    offenders: list[str] = []
    for path in PUBLIC_DOCS:
        if not path.exists():
            continue
        text = read(path)
        for name, pattern in PRIVATE_MATERIAL_PATTERNS.items():
            if re.search(pattern, text, re.IGNORECASE):
                offenders.append(f"{path.relative_to(ROOT)}:{name}")
    require(not offenders, "possible private material in public release docs: " + ", ".join(offenders))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Verify v0.4.1-alpha publication before release-owner tagging.")
    parser.add_argument("--expected-sha", help="Final tag target SHA to compare with the current checkout")
    args = parser.parse_args(argv)

    assert_clean_worktree()
    require(package_version() == VERSION, f"pyproject version must be {VERSION}")
    require(init_version() == VERSION, f"__version__ must be {VERSION}")
    require(plugin_versions() == (VERSION, VERSION), "Claude plugin and marketplace versions must match package version")
    require(not tag_exists(RELEASE), f"tag {RELEASE} already exists locally; Codex must not create the final tag")
    assert_manifest()
    assert_docs()
    assert_no_private_material()
    current_head = git_head()
    if args.expected_sha:
        require(re.fullmatch(r"[0-9a-f]{40}", args.expected_sha) is not None, "--expected-sha must be 40 lowercase hex")
        require(current_head == args.expected_sha, f"current checkout {current_head} does not match expected tag target {args.expected_sha}")
    print(f"{RELEASE} publication verification passed")
    print(f"manifest: {MANIFEST.relative_to(ROOT)}")
    print(f"current checkout sha: {current_head}")
    print("distribution path: GitHub clone")
    print("tag status: pending release-owner approval")
    print("production hosted calls: blocked by fixture-mode release commands")
    print("private key/token/payment-field scan: passed for public release docs")
    print("human tag command:")
    print(f"git tag -a {RELEASE} {current_head} -m \"{RELEASE}\"")
    print(f"git push origin {RELEASE}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
