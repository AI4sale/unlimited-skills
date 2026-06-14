"""Verify the v0.6.1-alpha contract freeze and ROI receipt publication gate."""

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
RELEASE = "v0.6.1-alpha"
VERSION = "0.6.1"
MANIFEST = ROOT / "docs" / "releases" / "v0.6.0-alpha.release-manifest.json"
FROZEN_CONTRACTS = ROOT / "scripts" / "verify-v06-frozen-contracts.py"
REQUIRED_DOCS = [
    ROOT / "docs" / "releases" / "v0.6.0-alpha.md",
    ROOT / "docs" / "releases" / "v0.6.0-alpha-checklist.md",
    ROOT / "docs" / "releases" / "v0.6.0-alpha-pypi-publishing.md",
    ROOT / "docs" / "releases" / "v0.6-contract-freeze-spec.md",
    ROOT / "docs" / "releases" / "v0.6-local-roi-receipt-spec.md",
    ROOT / "docs" / "roi-receipt.md",
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
    return subprocess.run(["git", *args], cwd=ROOT, check=check, capture_output=True, text=True, encoding="utf-8", errors="replace")


def run_cmd(args: list[str], *, cwd: Path, timeout: int = 300) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, cwd=cwd, check=False, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout)


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
    path = ROOT / "scripts" / "run-v060-alpha-package-smoke.py"
    spec = importlib.util.spec_from_file_location("run_v060_alpha_package_smoke", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load package smoke runner: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def run_package_smoke() -> dict[str, Any]:
    module = load_package_smoke()
    smoke053 = module.load_v053_smoke()
    smoke052 = smoke053.load_v052_smoke()
    smoke050 = smoke052.load_v050_smoke()
    import tempfile

    with tempfile.TemporaryDirectory(prefix="uls-v060-verifier-") as tmp_dir:
        tmp = Path(tmp_dir)
        dist_dir = tmp / "dist"
        dist_dir.mkdir()
        wheel, sdist = smoke050.build_dist(dist_dir)
        report = {
            "schema_version": 1,
            "version": VERSION,
            "dist": smoke050.inspect_dist(wheel, sdist),
            "clean_install": smoke050.clean_install_smoke(wheel, tmp / "install"),
            "clean_install_adoption_tools": smoke052.clean_install_adoption_tools_smoke(smoke050, wheel, tmp / "adoption"),
            "signal_rollup_fixture": smoke052.signal_rollup_fixture_smoke(tmp / "rollup"),
            "clean_install_local_event_privacy": smoke053.clean_install_local_event_privacy_smoke(smoke050, wheel, tmp / "privacy"),
            "clean_install_roi_receipt": module.clean_install_roi_receipt_smoke(smoke050, wheel, tmp / "roi"),
        }
        report["errors"] = module.verify(report, smoke053, smoke052, smoke050)
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
    require(git.get("publication_branch") == "codex/v061-learning-summary-json", "publication branch mismatch")
    require(git.get("tag") == RELEASE, "manifest tag mismatch")
    require(git.get("tag_status") == "blocked_until_pypi_upload_and_post_publish_smoke", "manifest must keep the release tag blocked until PyPI smoke passes")
    requirements = payload.get("adoption_toolchain_requirements") if isinstance(payload.get("adoption_toolchain_requirements"), dict) else {}
    for key in (
        "claude_code_mcp_installer",
        "feedback_prepare",
        "support_response_pack",
        "first_week_measurement",
        "signal_rollup_generator",
        "effectiveness_v2_instrumentation",
        "privacy_gate_followup",
        "local_event_privacy_hardening",
        "contract_freeze",
        "local_roi_receipt",
        "package_smoke",
    ):
        require(requirements.get(key) is True, f"manifest adoption requirement must be true: {key}")
    excluded = payload.get("excluded_prs") if isinstance(payload.get("excluded_prs"), list) else []
    require(119 in excluded, "#119 must be explicitly excluded from v0.6.1")
    return payload


def assert_docs() -> None:
    for path in REQUIRED_DOCS:
        require(path.is_file(), f"missing required doc: {path.relative_to(ROOT)}")
    public_text = "\n".join(read(path) for path in REQUIRED_DOCS + [ROOT / "README.md", ROOT / "CHANGELOG.md"] if path.exists()).lower()
    for required in (
        "v0.6.1-alpha",
        "unlimited-skills==0.6.1",
        "contract freeze",
        "privacy-safe local roi receipt",
        "unlimited-skills roi receipt",
        "local-only",
        "aggregate-only",
        "not telemetry",
        "not a benchmark guarantee",
        "not a paid roi promise",
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
        "action": "Publish unlimited-skills 0.6.1 through the manual Trusted Publishing workflow, then rerun the post-publish smoke.",
        "fallback": "Keep v0.6.1-alpha tag and GitHub prerelease blocked; do not mark the package release as published.",
        "details": details or {},
    }


def frozen_contract_blocker(reason: str, details: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "code": reason,
        "owner": "release owner",
        "action": "Fix the frozen v0.6 public contract drift, then rerun verify-v06-frozen-contracts.py and the publication verifier.",
        "fallback": "Keep release tag and GitHub prerelease guidance blocked; do not publish or tag until the frozen-contract harness passes.",
        "details": details or {},
    }


def run_frozen_contracts() -> dict[str, Any]:
    result = run_cmd([sys.executable, str(FROZEN_CONTRACTS), "--json"], cwd=ROOT)
    details: dict[str, Any] = {
        "command": f"{sys.executable} {FROZEN_CONTRACTS.relative_to(ROOT)} --json",
        "returncode": result.returncode,
    }
    if result.stdout.strip():
        try:
            payload = json.loads(result.stdout)
            rows = payload.get("rows") if isinstance(payload.get("rows"), list) else []
            failing_rows = [row for row in rows if isinstance(row, dict) and row.get("status") != "pass"]
            return {
                "ok": result.returncode == 0 and payload.get("ok") is True,
                "status_counts": payload.get("status_counts", {}),
                "surfaces": [row.get("surface") for row in rows if isinstance(row, dict)],
                "failing_rows": failing_rows,
                "blocker": None
                if result.returncode == 0 and payload.get("ok") is True
                else frozen_contract_blocker(
                    "release_blocked_frozen_contract_drift",
                    {
                        "status_counts": payload.get("status_counts", {}),
                        "failing_rows": failing_rows,
                    },
                ),
            }
        except json.JSONDecodeError:
            details["stdout_tail"] = result.stdout[-1200:]
    details["stderr_tail"] = result.stderr[-1200:]
    return {
        "ok": False,
        "status_counts": {},
        "surfaces": [],
        "failing_rows": [],
        "blocker": frozen_contract_blocker("release_blocked_frozen_contract_harness_failed", details),
    }


def published_install_smoke() -> dict[str, Any]:
    import tempfile

    with tempfile.TemporaryDirectory(prefix="uls-v060-pypi-smoke-") as tmp_dir:
        tmp = Path(tmp_dir)
        env_dir = tmp / "venv"
        venv.EnvBuilder(with_pip=True).create(env_dir)
        py = venv_python(env_dir)
        cli = venv_script(env_dir, "unlimited-skills")
        install = run_cmd([str(py), "-m", "pip", "install", "--no-cache-dir", f"unlimited-skills=={VERSION}"], cwd=tmp)
        if install.returncode != 0:
            return {"ok": False, "blocker": release_blocker("release_blocked_pypi_unavailable", {"step": "pip_install", "returncode": install.returncode, "stderr_tail": install.stderr[-1200:]})}
        missing_claude = tmp / "missing-claude.json"
        checks = {
            "version": run_cmd([str(cli), "--version"], cwd=tmp),
            "quickstart": run_cmd([str(cli), "quickstart", "--json", "--claude-config", str(missing_claude), "--timeout", "2"], cwd=tmp),
            "feedback_prepare": run_cmd([str(cli), "feedback", "prepare", "--format", "json"], cwd=tmp),
            "mcp_savings": run_cmd([str(cli), "mcp", "savings", "--json", "--claude-config", str(missing_claude), "--timeout", "2"], cwd=tmp),
            "mcp_install": run_cmd([str(cli), "mcp", "install", "--claude-code", "--dry-run", "--json", "--project-root", str(tmp / "project"), "--claude-config", str(missing_claude)], cwd=tmp),
            "learning_summary": run_cmd([str(cli), "learning-summary", "--events", "--json"], cwd=tmp),
            "roi_receipt_markdown": run_cmd([str(cli), "roi", "receipt"], cwd=tmp),
            "roi_receipt_json": run_cmd([str(cli), "roi", "receipt", "--format", "json"], cwd=tmp),
            "roi_receipt_since": run_cmd([str(cli), "roi", "receipt", "--since", "7d"], cwd=tmp),
        }
        failures = [{"step": step, "returncode": result.returncode, "stderr_tail": result.stderr[-600:]} for step, result in checks.items() if result.returncode != 0]
        if failures:
            return {"ok": False, "blocker": release_blocker("release_blocked_pypi_smoke_failed", {"failures": failures})}
        return {
            "ok": True,
            "version_output": checks["version"].stdout.strip(),
            "roi_receipt_json_type": json.loads(checks["roi_receipt_json"].stdout).get("report_type"),
            "roi_receipt_markdown_has_notice": "not telemetry, not a benchmark guarantee, and not a paid ROI promise" in checks["roi_receipt_markdown"].stdout,
        }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--expected-sha", help="Expected release commit SHA")
    parser.add_argument("--package-availability", choices=("prepublish", "local", "not-published", "published"), default="prepublish")
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
    frozen_contracts = run_frozen_contracts()

    package_availability = "prepublish" if args.package_availability in {"local", "not-published"} else args.package_availability
    blocker: dict[str, Any] | None = None if frozen_contracts.get("ok") else dict(frozen_contracts.get("blocker") or frozen_contract_blocker("release_blocked_frozen_contract_drift"))
    published_smoke: dict[str, Any] | None = None
    if package_availability == "published":
        published_smoke = published_install_smoke()
        if not published_smoke.get("ok") and blocker is None:
            blocker = dict(published_smoke.get("blocker") or release_blocker("release_blocked_pypi_unavailable"))

    privacy = package_smoke["clean_install_local_event_privacy"]
    roi = package_smoke["clean_install_roi_receipt"]
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
            "privacy_event_count": privacy["event_count"],
            "privacy_feedback_count": privacy["feedback_count"],
            "privacy_no_forbidden_needles": not any(privacy["contains_forbidden_needles"].values()),
            "roi_receipt_json_schema_valid": roi["json_report_type"] == "local_roi_receipt" and roi["json_schema_version"] == 1,
            "roi_receipt_forbidden_field_scan": not any(roi["contains_forbidden_needles"].values()),
            "roi_receipt_markdown_notice": roi["markdown_has_notice"],
            "roi_receipt_out_no_path_leak": not roi["out_status_path_leak"],
            "roi_receipt_since_7d": roi["since_7d"],
            "roi_receipt_legacy_unavailable": roi["legacy_unavailable"],
        },
        "frozen_contracts": {
            "ok": frozen_contracts.get("ok") is True,
            "status_counts": frozen_contracts.get("status_counts", {}),
            "surfaces": frozen_contracts.get("surfaces", []),
            "failing_rows": frozen_contracts.get("failing_rows", []),
        },
    }
    if published_smoke and published_smoke.get("ok") and blocker is None:
        report["published_install_smoke"] = published_smoke
        report["tag_command"] = f"git tag -a {RELEASE} {git_head()} -m \"{RELEASE}\""
    else:
        if published_smoke and published_smoke.get("ok"):
            report["published_install_smoke"] = published_smoke
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
