"""Build and clean-install smoke for the v0.6.4 Money Saved Meter package line."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import tempfile
import venv
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_VERSION = "0.6.4"
FIXTURE_DIR = ROOT / "tests" / "fixtures" / "money_saved_meter"


def venv_python(root: Path) -> Path:
    return root / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def venv_script(root: Path, name: str) -> Path:
    suffix = ".exe" if os.name == "nt" else ""
    return root / ("Scripts" if os.name == "nt" else "bin") / f"{name}{suffix}"


def run(args: list[str], *, cwd: Path, timeout: int = 300) -> subprocess.CompletedProcess[str]:
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


def require_ok(proc: subprocess.CompletedProcess[str], label: str) -> str:
    if proc.returncode != 0:
        raise RuntimeError(f"{label} failed:\nSTDOUT:\n{proc.stdout[-1200:]}\nSTDERR:\n{proc.stderr[-1200:]}")
    return proc.stdout


def load_json(text: str) -> dict[str, Any]:
    payload = json.loads(text)
    if not isinstance(payload, dict):
        raise RuntimeError("expected JSON object")
    return payload


def build_dist(dist_dir: Path) -> tuple[Path, Path]:
    require_ok(run(["python", "-m", "pip", "install", "--upgrade", "build", "twine"], cwd=ROOT), "install build tools")
    require_ok(run(["python", "-m", "build", "--outdir", str(dist_dir)], cwd=ROOT), "build dist")
    require_ok(run(["python", "-m", "twine", "check", str(dist_dir / "*")], cwd=ROOT), "twine check")
    wheels = sorted(dist_dir.glob("*.whl"))
    sdists = sorted(dist_dir.glob("*.tar.gz"))
    if len(wheels) != 1 or len(sdists) != 1:
        raise RuntimeError("expected exactly one wheel and one sdist")
    return wheels[0], sdists[0]


def clean_install_money_saved_tier_smoke(wheel: Path, work: Path) -> dict[str, Any]:
    env_dir = work / "venv-money-saved"
    venv.EnvBuilder(with_pip=True).create(env_dir)
    py = venv_python(env_dir)
    cli = venv_script(env_dir, "unlimited-skills")
    require_ok(run([str(py), "-m", "pip", "install", str(wheel)], cwd=work), "install wheel")

    library = work / "library"
    out = work / "money-saved"
    library.mkdir(parents=True, exist_ok=True)
    out.mkdir(parents=True, exist_ok=True)

    def run_cli(args: list[str], *, expect_success: bool = True) -> subprocess.CompletedProcess[str]:
        proc = run([str(cli), "--root", str(library), *args], cwd=work)
        if expect_success:
            require_ok(proc, "unlimited-skills " + " ".join(args))
        return proc

    version = require_ok(run([str(cli), "--version"], cwd=work), "version").strip()

    free_report = out / "free-money-saved-meter.json"
    registered = out / "registered-money-saved.json"
    team = out / "team-money-saved.json"
    admin_json = out / "business-money-saved-admin.json"
    admin_csv = out / "business-money-saved-admin.csv"
    evidence = out / "enterprise-money-saved-evidence-pack"
    tampered = out / "enterprise-money-saved-evidence-pack-tampered"

    run_cli(["money-saved", "meter", "--json", "--fixture-100-call", "--out", str(free_report), "--json-status"])
    run_cli([
        "money-saved",
        "registered-export",
        "--mcp-savings-json",
        str(FIXTURE_DIR / "100-call-mcp-savings.json"),
        "--audit-log",
        str(FIXTURE_DIR / "100-call-gateway-audit.jsonl"),
        "--target-calls",
        "100",
        "--out",
        str(registered),
        "--json-status",
    ])
    run_cli(["money-saved", "team-rollup", "--input", str(registered), "--alias", "member-a", "--out", str(team), "--json-status"])
    run_cli(["money-saved", "admin-export", "--input", str(team), "--json", str(admin_json), "--csv", str(admin_csv)])
    run_cli(["money-saved", "evidence-pack", "--input", str(admin_json), "--out", str(evidence)])
    verify = load_json(run_cli(["money-saved", "verify-evidence-pack", "--input", str(evidence), "--json"]).stdout)

    shutil.copytree(evidence, tampered)
    (tampered / "privacy-proof.json").write_text('{"tampered": true, "upload": true}\n', encoding="utf-8")
    tampered_proc = run_cli(["money-saved", "verify-evidence-pack", "--input", str(tampered), "--json"], expect_success=False)
    tampered_payload = load_json(tampered_proc.stdout)

    return {
        "version_output": version,
        "free_report_written": free_report.is_file(),
        "registered_export_written": registered.is_file(),
        "team_rollup_written": team.is_file(),
        "business_json_written": admin_json.is_file(),
        "business_csv_written": admin_csv.is_file(),
        "enterprise_manifest_written": (evidence / "manifest.json").is_file(),
        "enterprise_privacy_proof_written": (evidence / "privacy-proof.json").is_file(),
        "enterprise_measurement_proof_written": (evidence / "measurement-proof.json").is_file(),
        "enterprise_claim_boundary_proof_written": (evidence / "claim-boundary-proof.json").is_file(),
        "enterprise_verify_ok": verify.get("ok"),
        "enterprise_tamper_returncode": tampered_proc.returncode,
        "enterprise_tamper_ok": tampered_payload.get("ok"),
    }


def verify_report(report: dict[str, Any], expected_version: str = DEFAULT_VERSION) -> list[str]:
    errors: list[str] = []
    if report.get("version") != expected_version:
        errors.append("version mismatch")
    dist = report.get("dist") if isinstance(report.get("dist"), dict) else {}
    normalized = expected_version.replace("-", "_")
    if f"-{normalized}-" not in str(dist.get("wheel", "")):
        errors.append(f"wheel filename must include {expected_version}")
    tier = report.get("clean_install_money_saved_tiers") or {}
    if tier.get("version_output") != f"unlimited-skills {expected_version}":
        errors.append(f"installed CLI version output mismatch for {expected_version}")
    for key in (
        "free_report_written",
        "registered_export_written",
        "team_rollup_written",
        "business_json_written",
        "business_csv_written",
        "enterprise_manifest_written",
        "enterprise_privacy_proof_written",
        "enterprise_measurement_proof_written",
        "enterprise_claim_boundary_proof_written",
    ):
        if tier.get(key) is not True:
            errors.append(f"Money Saved clean install tier smoke missing expected proof: {key}")
    if tier.get("enterprise_verify_ok") is not True:
        errors.append("Enterprise evidence pack clean verify must return ok=true")
    if tier.get("enterprise_tamper_returncode") == 0 or tier.get("enterprise_tamper_ok") is not False:
        errors.append("Enterprise evidence pack tamper check must fail closed")
    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--expected-version", default=DEFAULT_VERSION)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--keep-temp", action="store_true")
    args = parser.parse_args(argv)

    tmp = Path(tempfile.mkdtemp(prefix="uls-v064-package-smoke-"))
    try:
        dist_dir = tmp / "dist"
        dist_dir.mkdir()
        wheel, sdist = build_dist(dist_dir)
        report = {
            "schema_version": 1,
            "version": args.expected_version,
            "dist": {"wheel": wheel.name, "sdist": sdist.name},
            "clean_install_money_saved_tiers": clean_install_money_saved_tier_smoke(wheel, tmp / "money-saved"),
        }
        report["errors"] = verify_report(report, args.expected_version)
        report["ok"] = not report["errors"]
        if args.json:
            print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
        else:
            print(f"v0.6.4 package smoke ({args.expected_version}): " + ("PASS" if report["ok"] else "FAIL"))
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
