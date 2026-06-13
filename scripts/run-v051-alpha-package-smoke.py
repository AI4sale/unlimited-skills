"""Build and clean-install smoke for the v0.5.1 adoption tools package.

This extends the v0.5.0 package smoke with the adoption commands that must be
available to PyPI users before marketplace/listing traffic is widened.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import shutil
import tempfile
import venv
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
VERSION = "0.5.1"


def load_v050_smoke():
    path = ROOT / "scripts" / "run-v050-alpha-package-smoke.py"
    spec = importlib.util.spec_from_file_location("run_v050_alpha_package_smoke", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load package smoke runner: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.VERSION = VERSION
    return module


def clean_install_adoption_tools_smoke(module, wheel: Path, work: Path) -> dict[str, Any]:
    env_dir = work / "venv-adoption"
    venv.EnvBuilder(with_pip=True).create(env_dir)
    py = module.venv_python(env_dir)
    cli = module.venv_script(env_dir, "unlimited-skills")
    module.run([str(py), "-m", "pip", "install", str(wheel)], cwd=work)

    project_root = work / "project"
    project_root.mkdir()
    claude_config = work / "claude.json"
    library = work / "library"

    mcp_install = module.run(
        [
            str(cli),
            "mcp",
            "install",
            "--claude-code",
            "--dry-run",
            "--json",
            "--project-root",
            str(project_root),
            "--claude-config",
            str(claude_config),
        ],
        cwd=work,
    )
    feedback_prepare = module.run(
        [
            str(cli),
            "--root",
            str(library),
            "feedback",
            "prepare",
            "--format",
            "json",
        ],
        cwd=work,
    )
    mcp_payload = json.loads(mcp_install.stdout)
    feedback_payload = json.loads(feedback_prepare.stdout)
    return {
        "mcp_install_action": mcp_payload.get("action"),
        "mcp_install_dry_run": mcp_payload.get("dry_run"),
        "mcp_install_scope": mcp_payload.get("scope"),
        "mcp_install_has_redacted_diff": bool(mcp_payload.get("redacted_diff")),
        "feedback_schema_version": feedback_payload.get("schema_version"),
        "feedback_report_type": feedback_payload.get("report_type"),
        "feedback_upload_available": feedback_payload.get("upload_available"),
        "feedback_local_only": feedback_payload.get("local_only"),
        "feedback_hosted_calls": feedback_payload.get("hosted_calls"),
        "feedback_issue_templates": sorted(
            item.get("issue_type")
            for item in feedback_payload.get("issue_template_mapping", [])
            if isinstance(item, dict) and item.get("issue_type")
        ),
    }


def verify(report: dict[str, Any], module) -> list[str]:
    errors = list(module.verify(report))
    adoption = report.get("clean_install_adoption_tools") or {}
    if adoption.get("mcp_install_action") != "install":
        errors.append("clean install mcp install --claude-code must report install action")
    if adoption.get("mcp_install_dry_run") is not True:
        errors.append("clean install mcp install --claude-code must run as dry-run in smoke")
    if adoption.get("mcp_install_scope") != "project":
        errors.append("clean install mcp install --claude-code must default to project scope")
    if adoption.get("feedback_schema_version") != 1:
        errors.append("clean install feedback prepare must emit schema_version 1")
    if adoption.get("feedback_report_type") != "feedback-prepare-report":
        errors.append("clean install feedback prepare report_type mismatch")
    if adoption.get("feedback_upload_available") is not False:
        errors.append("clean install feedback prepare must not offer upload")
    if adoption.get("feedback_local_only") is not True:
        errors.append("clean install feedback prepare must report local_only true")
    if adoption.get("feedback_hosted_calls") is not False:
        errors.append("clean install feedback prepare must not make hosted calls")
    for template in ("first_value", "install_friction", "skill_not_invoked", "mcp_savings"):
        if template not in adoption.get("feedback_issue_templates", []):
            errors.append(f"clean install feedback prepare missing issue template mapping: {template}")
    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--keep-temp", action="store_true")
    args = parser.parse_args(argv)

    module = load_v050_smoke()
    tmp = Path(tempfile.mkdtemp(prefix="uls-v051-package-smoke-"))
    try:
        dist_dir = tmp / "dist"
        dist_dir.mkdir()
        wheel, sdist = module.build_dist(dist_dir)
        report = {
            "schema_version": 1,
            "version": VERSION,
            "dist": module.inspect_dist(wheel, sdist),
            "clean_install": module.clean_install_smoke(wheel, tmp / "install"),
            "clean_install_adoption_tools": clean_install_adoption_tools_smoke(module, wheel, tmp / "adoption"),
        }
        report["errors"] = verify(report, module)
        report["ok"] = not report["errors"]
        if args.json:
            print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
        else:
            print("v0.5.1-alpha package smoke: " + ("PASS" if report["ok"] else "FAIL"))
            for error in report["errors"]:
                print(f"- {error}")
        return 0 if report["ok"] else 1
    finally:
        if args.keep_temp:
            print(f"kept temp: {tmp}")
        else:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
