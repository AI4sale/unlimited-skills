"""Build and clean-install smoke for the v0.6.3 Learning Loop alpha package.

The smoke builds the distribution, installs the wheel into fresh virtual
environments, reuses the frozen v0.6 package checks, and proves the v0.6.3
Learning Loop Free/Registered/Team/Business/Enterprise command ladder from the
installed wheel.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import shutil
import subprocess
import tempfile
import venv
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
VERSION = "0.6.3"


def load_v060_smoke():
    path = ROOT / "scripts" / "run-v060-alpha-package-smoke.py"
    spec = importlib.util.spec_from_file_location("run_v060_alpha_package_smoke", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load package smoke runner: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.VERSION = VERSION
    return module


def _json(text: str) -> dict[str, Any]:
    payload = json.loads(text)
    if not isinstance(payload, dict):
        raise RuntimeError("expected JSON object")
    return payload


def clean_install_learning_loop_tier_smoke(smoke050, wheel: Path, work: Path) -> dict[str, Any]:
    env_dir = work / "venv-learning-loop"
    venv.EnvBuilder(with_pip=True).create(env_dir)
    py = smoke050.venv_python(env_dir)
    cli = smoke050.venv_script(env_dir, "unlimited-skills")
    smoke050.run([str(py), "-m", "pip", "install", str(wheel)], cwd=work)

    library = work / "library"
    skill_file = library / "local" / "skills" / "python-patterns" / "SKILL.md"
    skill_file.parent.mkdir(parents=True, exist_ok=True)
    skill_file.write_text(
        "---\nname: python-patterns\ndescription: Python implementation patterns.\n---\n\n# python-patterns\n",
        encoding="utf-8",
    )

    forbidden = [
        "v063 private prompt needle",
        "v063 raw customer task needle",
        "v063 operator secret note",
        str(library),
        str(skill_file),
    ]

    def run_cli(args: list[str]) -> str:
        return smoke050.run([str(cli), "--root", str(library), *args], cwd=work).stdout

    version = smoke050.run([str(cli), "--version"], cwd=work).stdout.strip()
    run_cli(["reindex"])
    for verdict in ("wrong", "missed", "rejected"):
        run_cli(
            [
                "feedback",
                "record",
                "python-patterns",
                "--verdict",
                verdict,
                "--query",
                "v063 private prompt needle",
                "--notes",
                "v063 operator secret note",
            ]
        )

    doctor = _json(run_cli(["learning", "doctor"]))
    candidates = _json(run_cli(["improvement-candidates"]))
    candidate_items = candidates.get("candidates") if isinstance(candidates.get("candidates"), list) else []
    candidate_id = candidate_items[0]["candidate_id"]

    before = skill_file.read_text(encoding="utf-8")
    dry_run = _json(run_cli(["apply-candidate", "--dry-run", str(candidate_id)]))
    after = skill_file.read_text(encoding="utf-8")

    artifacts = work / "learning-artifacts"
    artifacts.mkdir(parents=True, exist_ok=True)
    registered = artifacts / "registered-learning-export.json"
    team = artifacts / "team-learning-rollup.json"
    business_json = artifacts / "business-learning-admin.json"
    business_csv = artifacts / "business-learning-admin.csv"
    pack = artifacts / "enterprise-learning-evidence-pack"
    tampered = artifacts / "enterprise-learning-evidence-pack-tampered"

    export_status = _json(run_cli(["learning", "export", "--out", str(registered), "--json-status"]))
    team_status = _json(run_cli(["learning", "team-rollup", "--input", str(registered), "--out", str(team), "--json-status"]))
    run_cli(["learning", "admin-export", "--input", str(team), "--json", str(business_json), "--csv", str(business_csv)])
    run_cli(["learning", "evidence-pack", "--input", str(business_json), "--out", str(pack)])
    verify_pack = _json(run_cli(["learning", "verify-evidence-pack", "--input", str(pack), "--json"]))
    shutil.copytree(pack, tampered)
    (tampered / "non-mutation-proof.json").write_text('{"mutation_supported": true}', encoding="utf-8")
    tampered_proc = subprocess.run(
        [str(cli), "--root", str(library), "learning", "verify-evidence-pack", "--input", str(tampered), "--json"],
        cwd=work,
        text=True,
        capture_output=True,
        encoding="utf-8",
        errors="replace",
        timeout=180,
    )
    tampered_payload = _json(tampered_proc.stdout)

    combined = json.dumps(
        {
            "doctor": doctor,
            "candidates": candidates,
            "dry_run": dry_run,
            "export_status": export_status,
            "team_status": team_status,
            "verify_pack": verify_pack,
            "tampered_payload": tampered_payload,
        },
        ensure_ascii=False,
        sort_keys=True,
    )
    return {
        "version_output": version,
        "free_doctor_inspected": doctor.get("message") == "Learning state inspected.",
        "free_doctor_feedback_count": doctor.get("feedback_count"),
        "free_candidate_count": len(candidate_items),
        "free_dry_run_written": dry_run.get("written"),
        "free_dry_run_mutated_files": dry_run.get("mutated_files"),
        "free_skill_file_unchanged": before == after,
        "registered_export_written": registered.is_file() and registered.stat().st_size > 0,
        "team_rollup_written": team.is_file() and team.stat().st_size > 0,
        "business_json_written": business_json.is_file() and business_json.stat().st_size > 0,
        "business_csv_written": business_csv.is_file() and business_csv.stat().st_size > 0,
        "enterprise_manifest_written": (pack / "manifest.json").is_file(),
        "enterprise_verify_ok": verify_pack.get("ok") is True,
        "enterprise_tamper_returncode": tampered_proc.returncode,
        "enterprise_tamper_ok": tampered_payload.get("ok"),
        "contains_forbidden_needles": {needle: needle in combined for needle in forbidden},
    }


def verify_learning_loop_tier(report: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    tier = report.get("clean_install_learning_loop_tiers") or {}
    if tier.get("version_output") != f"unlimited-skills {VERSION}":
        errors.append("installed CLI version output mismatch for v0.6.3")
    for key in (
        "free_doctor_inspected",
        "free_skill_file_unchanged",
        "registered_export_written",
        "team_rollup_written",
        "business_json_written",
        "business_csv_written",
        "enterprise_manifest_written",
        "enterprise_verify_ok",
    ):
        if tier.get(key) is not True:
            errors.append(f"Learning Loop clean install tier smoke missing expected proof: {key}")
    if not isinstance(tier.get("free_candidate_count"), int) or tier.get("free_candidate_count") < 1:
        errors.append("Learning Loop clean install tier smoke must produce at least one candidate")
    if not isinstance(tier.get("free_doctor_feedback_count"), int) or tier.get("free_doctor_feedback_count") < 3:
        errors.append("Learning Loop clean install doctor must see the feedback fixture rows")
    if tier.get("free_dry_run_written") is not False:
        errors.append("apply-candidate dry-run must report written=false")
    if tier.get("free_dry_run_mutated_files") != []:
        errors.append("apply-candidate dry-run must report mutated_files=[]")
    if tier.get("enterprise_tamper_returncode") == 0 or tier.get("enterprise_tamper_ok") is not False:
        errors.append("Enterprise evidence pack tamper check must fail closed")
    leaked = [needle for needle, present in (tier.get("contains_forbidden_needles") or {}).items() if present]
    if leaked:
        errors.append("Learning Loop tier outputs leaked forbidden raw data: " + ", ".join(leaked))
    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--keep-temp", action="store_true")
    args = parser.parse_args(argv)

    smoke060 = load_v060_smoke()
    smoke053 = smoke060.load_v053_smoke()
    smoke052 = smoke053.load_v052_smoke()
    smoke050 = smoke052.load_v050_smoke()
    tmp = Path(tempfile.mkdtemp(prefix="uls-v063-package-smoke-"))
    try:
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
            "clean_install_roi_receipt": smoke060.clean_install_roi_receipt_smoke(smoke050, wheel, tmp / "roi"),
            "clean_install_learning_loop_tiers": clean_install_learning_loop_tier_smoke(smoke050, wheel, tmp / "learning"),
        }
        report["errors"] = smoke060.verify(report, smoke053, smoke052, smoke050)
        report["errors"].extend(verify_learning_loop_tier(report))
        report["ok"] = not report["errors"]
        if args.json:
            print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
        else:
            print("v0.6.3-alpha package smoke: " + ("PASS" if report["ok"] else "FAIL"))
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
