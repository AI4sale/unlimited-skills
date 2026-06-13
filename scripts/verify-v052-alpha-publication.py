"""Verify the v0.5.2-alpha adoption instrumentation publication gate."""

from __future__ import annotations

import argparse
import importlib.util
import json
import re
import subprocess
import sys
import tomllib
import venv
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
RELEASE = "v0.5.2-alpha"
VERSION = "0.5.2"
MANIFEST = ROOT / "docs" / "releases" / "v0.5.2-alpha.release-manifest.json"
REQUIRED_DOCS = [
    ROOT / "docs" / "releases" / "v0.5.2-alpha.md",
    ROOT / "docs" / "releases" / "v0.5.2-alpha-checklist.md",
    ROOT / "docs" / "releases" / "v0.5.2-alpha-pypi-publishing.md",
    ROOT / "docs" / "feedback.md",
    ROOT / "docs" / "adoption" / "support-response-pack.md",
    ROOT / "docs" / "adoption" / "first-week-adoption-measurement.md",
    ROOT / "docs" / "adoption" / "public-alpha-signal-rollup-template.md",
    MANIFEST,
]


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def fail(message: str) -> None:
    raise SystemExit(f"{RELEASE} verification failed: {message}")


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


def run_cmd(args: list[str], *, cwd: Path, timeout: int = 300) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args,
        cwd=cwd,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
    )


def venv_python(root: Path) -> Path:
    return root / ("Scripts/python.exe" if sys.platform.startswith("win") else "bin/python")


def venv_script(root: Path, name: str) -> Path:
    return root / (f"Scripts/{name}.exe" if sys.platform.startswith("win") else f"bin/{name}")


def git_head() -> str:
    return run_git(["rev-parse", "HEAD"]).stdout.strip()


def tag_exists(tag: str) -> bool:
    return run_git(["rev-parse", "--verify", "--quiet", f"refs/tags/{tag}"], check=False).returncode == 0


def assert_clean_worktree() -> None:
    status = run_git(["status", "--short"]).stdout.strip()
    require(not status, "working tree must be clean for publication verification")


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


def load_package_smoke():
    path = ROOT / "scripts" / "run-v052-alpha-package-smoke.py"
    spec = importlib.util.spec_from_file_location("run_v052_alpha_package_smoke", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load package smoke runner: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def run_package_smoke() -> dict[str, Any]:
    module = load_package_smoke()
    smoke050 = module.load_v050_smoke()
    import tempfile

    with tempfile.TemporaryDirectory(prefix="uls-v052-verifier-") as tmp_dir:
        tmp = Path(tmp_dir)
        dist_dir = tmp / "dist"
        dist_dir.mkdir()
        wheel, sdist = smoke050.build_dist(dist_dir)
        report = {
            "schema_version": 1,
            "version": VERSION,
            "dist": smoke050.inspect_dist(wheel, sdist),
            "clean_install": smoke050.clean_install_smoke(wheel, tmp / "install"),
            "clean_install_adoption_tools": module.clean_install_adoption_tools_smoke(smoke050, wheel, tmp / "adoption"),
            "signal_rollup_fixture": module.signal_rollup_fixture_smoke(tmp / "rollup"),
        }
        report["errors"] = module.verify(report, smoke050)
        report["ok"] = not report["errors"]
        return report


def assert_metadata() -> None:
    require(package_version() == VERSION, f"pyproject version must be {VERSION}")
    require(init_version() == VERSION, f"__version__ must be {VERSION}")
    require(plugin_versions() == (VERSION, VERSION), "Claude plugin and marketplace versions must match package version")


def assert_manifest() -> dict[str, Any]:
    require(MANIFEST.is_file(), f"missing manifest: {MANIFEST.relative_to(ROOT)}")
    payload = json.loads(read(MANIFEST))
    require(payload.get("release") == RELEASE, "manifest release mismatch")
    require(payload.get("package_version") == VERSION, "manifest package version mismatch")
    git = payload.get("git") if isinstance(payload.get("git"), dict) else {}
    require(git.get("publication_branch") == "release/v0.5.2-alpha-adoption-instrumentation", "publication branch mismatch")
    require(git.get("tag") == RELEASE, "manifest tag mismatch")
    require(
        git.get("tag_status") == "blocked_until_pypi_upload_and_post_publish_smoke",
        "manifest must keep the release tag blocked until PyPI smoke passes",
    )
    requirements = payload.get("adoption_toolchain_requirements") if isinstance(payload.get("adoption_toolchain_requirements"), dict) else {}
    for key in (
        "claude_code_mcp_installer",
        "feedback_prepare",
        "support_response_pack",
        "first_week_measurement",
        "signal_rollup_generator",
        "effectiveness_v2_instrumentation",
        "privacy_gate_followup",
        "package_smoke",
    ):
        require(requirements.get(key) is True, f"manifest adoption requirement must be true: {key}")
    excluded = payload.get("excluded_prs") if isinstance(payload.get("excluded_prs"), list) else []
    require(119 in excluded, "#119 must be explicitly excluded from v0.5.2")
    return payload


def assert_docs() -> None:
    for path in REQUIRED_DOCS:
        require(path.is_file(), f"missing required doc: {path.relative_to(ROOT)}")
    public_text = "\n".join(read(path) for path in REQUIRED_DOCS + [ROOT / "README.md", ROOT / "CHANGELOG.md"] if path.exists()).lower()
    for required in (
        "v0.5.1-alpha",
        "v0.5.2-alpha",
        "unlimited-skills mcp install --claude-code",
        "unlimited-skills feedback prepare",
        "learning-summary --events",
        "generate-public-alpha-signal-rollup.py",
        "first-week adoption",
        "no telemetry",
        "no paid",
        "no hosted",
        "no team readiness",
    ):
        require(required in public_text, f"public docs missing required wording: {required}")
    require("#119" in public_text, "public docs must state #119 is excluded/background")


def release_blocker(reason: str, details: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "code": reason,
        "owner": "PyPI account / GitHub Trusted Publisher setup",
        "action": "Publish unlimited-skills 0.5.2 through the manual Trusted Publishing workflow, then rerun the post-publish smoke.",
        "fallback": "Keep v0.5.2-alpha tag and GitHub prerelease blocked; do not mark the package release as published.",
        "details": details or {},
    }


def published_install_smoke() -> dict[str, Any]:
    import tempfile

    with tempfile.TemporaryDirectory(prefix="uls-v052-pypi-smoke-") as tmp_dir:
        tmp = Path(tmp_dir)
        env_dir = tmp / "venv"
        venv.EnvBuilder(with_pip=True).create(env_dir)
        py = venv_python(env_dir)
        cli = venv_script(env_dir, "unlimited-skills")
        install = run_cmd([str(py), "-m", "pip", "install", "--no-cache-dir", f"unlimited-skills=={VERSION}"], cwd=tmp)
        if install.returncode != 0:
            return {
                "ok": False,
                "blocker": release_blocker(
                    "release_blocked_pypi_unavailable",
                    {"step": "pip_install", "package": f"unlimited-skills=={VERSION}", "returncode": install.returncode, "stderr_tail": install.stderr[-1200:]},
                ),
            }
        project_root = tmp / "project"
        project_root.mkdir()
        claude_config = tmp / "claude.json"
        missing_claude = tmp / "missing-claude.json"
        version = run_cmd([str(cli), "--version"], cwd=tmp)
        quickstart = run_cmd([str(cli), "quickstart", "--json", "--claude-config", str(missing_claude), "--timeout", "2"], cwd=tmp)
        suggest = run_cmd([str(cli), "suggest", "review a pull request for security issues", "--json"], cwd=tmp)
        mcp_install = run_cmd([str(cli), "mcp", "install", "--claude-code", "--dry-run", "--json", "--project-root", str(project_root), "--claude-config", str(claude_config)], cwd=tmp)
        feedback = run_cmd([str(cli), "feedback", "prepare", "--format", "json"], cwd=tmp)
        learning_root = tmp / "learning"
        events = learning_root / ".learning"
        events.mkdir(parents=True, exist_ok=True)
        (events / "events.jsonl").write_text(
            '{"ts":1.0,"type":"suggest","payload":{"delivery_tier":3,"injected":true,"score_bucket":"high","margin_bucket":"clear","session_correlation_id":"abc123"}}\n'
            '{"ts":2.0,"type":"skill_used","payload":{"session_correlation_id":"abc123"}}\n',
            encoding="utf-8",
        )
        learning = run_cmd([str(cli), "--root", str(learning_root), "learning-summary", "--events"], cwd=tmp)
        savings = run_cmd([str(cli), "mcp", "savings", "--json", "--claude-config", str(missing_claude), "--timeout", "2"], cwd=tmp)
        failed = [
            {"step": "version", "result": version},
            {"step": "quickstart", "result": quickstart},
            {"step": "suggest", "result": suggest},
            {"step": "mcp_install", "result": mcp_install},
            {"step": "feedback_prepare", "result": feedback},
            {"step": "learning_summary_events", "result": learning},
            {"step": "mcp_savings", "result": savings},
        ]
        failures = [
            {"step": item["step"], "returncode": item["result"].returncode, "stderr_tail": item["result"].stderr[-600:]}
            for item in failed
            if item["result"].returncode != 0
        ]
        if failures:
            return {"ok": False, "blocker": release_blocker("release_blocked_pypi_smoke_failed", {"failures": failures})}
        return {"ok": True, "version_output": version.stdout.strip(), "learning_summary_events": json.loads(learning.stdout)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--expected-sha", help="Expected release commit SHA")
    parser.add_argument(
        "--package-availability",
        choices=("prepublish", "local", "not-published", "published"),
        default="prepublish",
    )
    parser.add_argument("--allow-existing-tag", action="store_true")
    parser.add_argument("--allow-dirty", action="store_true", help="Development-only mode for testing before committing.")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    if not args.allow_dirty:
        assert_clean_worktree()
    assert_metadata()
    manifest = assert_manifest()
    assert_docs()
    if args.expected_sha:
        require(re.fullmatch(r"[0-9a-f]{40}", args.expected_sha) is not None, "--expected-sha must be 40 lowercase hex")
        require(git_head() == args.expected_sha, f"current checkout {git_head()} does not match expected SHA {args.expected_sha}")
    if not args.allow_existing_tag:
        require(not tag_exists(RELEASE), f"tag {RELEASE} already exists locally")
    package_smoke = run_package_smoke()
    require(package_smoke.get("ok") is True, "package smoke failed: " + ", ".join(package_smoke.get("errors") or []))

    package_availability = "prepublish" if args.package_availability in {"local", "not-published"} else args.package_availability
    blocker: dict[str, Any] | None = None
    published_smoke: dict[str, Any] | None = None
    if package_availability == "published":
        published_smoke = published_install_smoke()
        if not published_smoke.get("ok"):
            blocker = dict(published_smoke.get("blocker") or release_blocker("release_blocked_pypi_unavailable"))

    report = {
        "schema_version": 1,
        "status": "blocked" if blocker else "passed",
        "release": RELEASE,
        "version": VERSION,
        "package_availability": package_availability,
        "current_checkout_sha": git_head(),
        "manifest": str(MANIFEST.relative_to(ROOT)),
        "required_prs": manifest.get("required_prs", {}),
        "excluded_prs": manifest.get("excluded_prs", []),
        "package_smoke": {
            "wheel_skill_count": package_smoke["dist"]["wheel_skill_count"],
            "quickstart_skill_count": package_smoke["clean_install"]["quickstart_library"]["skill_count"],
            "version_output": package_smoke["clean_install"]["version_output"],
            "suggest_candidates": package_smoke["clean_install"]["suggest_candidates"],
            "mcp_install_action": package_smoke["clean_install_adoption_tools"]["mcp_install_action"],
            "feedback_report_type": package_smoke["clean_install_adoption_tools"]["feedback_report_type"],
            "effectiveness_suggest_count": package_smoke["clean_install_adoption_tools"]["effectiveness_suggest_count"],
            "signal_rollup_fixture": package_smoke["signal_rollup_fixture"]["created"],
        },
    }
    if published_smoke and published_smoke.get("ok"):
        report["published_install_smoke"] = published_smoke
        report["tag_command"] = f"git tag -a {RELEASE} {git_head()} -m \"{RELEASE}\""
    else:
        report["tag_status"] = "blocked_until_pypi_upload_and_post_publish_smoke"
    if blocker:
        report["blocker"] = blocker
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        if blocker:
            print(f"{RELEASE} verification blocked: {blocker['code']}")
            print(json.dumps(blocker, ensure_ascii=False, indent=2, sort_keys=True))
            return 1
        print(f"{RELEASE} verification passed")
        print(json.dumps(report["package_smoke"], ensure_ascii=False, indent=2, sort_keys=True))
        if "tag_command" in report:
            print("tag command:")
            print(report["tag_command"])
        else:
            print("tag blocked until PyPI upload and post-publish smoke")
    return 1 if blocker else 0


if __name__ == "__main__":
    raise SystemExit(main())
