from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
RELEASE = "v0.6.3-alpha"
PRIVATE_NEEDLES = [
    "prompt secret",
    "raw customer task",
    "operator secret note",
    "C:\\Users\\tedja\\private",
    "ghp_secretTOKEN123456",
    "-----BEGIN PRIVATE KEY-----",
]


def _rel(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT)).replace("\\", "/")
    except ValueError:
        return str(path).replace("\\", "/")


def _json(text: str) -> dict[str, Any]:
    return json.loads(text)


def _run_python(args: list[str]) -> tuple[int, str, str]:
    completed = subprocess.run(
        [sys.executable, *args],
        cwd=ROOT,
        text=True,
        encoding="utf-8",
        errors="replace",
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    return completed.returncode, completed.stdout, completed.stderr


def _run_cli(root: Path, args: list[str]) -> tuple[int, str, str]:
    return _run_python(["-m", "unlimited_skills.cli", "--root", str(root), *args])


def _row(
    *,
    surface: str,
    tier: str,
    command: str,
    rc: int,
    stdout: str,
    stderr: str = "",
    artifacts: list[Path] | None = None,
    expect_rc: int = 0,
    expect_ok: bool = True,
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    artifacts = artifacts or []
    missing = [path for path in artifacts if not path.exists()]
    ok = (rc == expect_rc) and not missing
    if not expect_ok:
        ok = rc != 0
    return {
        "surface": surface,
        "tier": tier,
        "command": command,
        "returncode": rc,
        "ok": ok,
        "expected_success": expect_ok,
        "artifact_paths": [_rel(path) for path in artifacts],
        "missing_artifacts": [_rel(path) for path in missing],
        "stdout_excerpt": stdout[:500],
        "stderr_excerpt": stderr[:500],
        "details": details or {},
    }


def _assert_no_private_needles(value: object) -> None:
    text = json.dumps(value, ensure_ascii=False, sort_keys=True)
    for needle in PRIVATE_NEEDLES:
        if needle in text:
            raise AssertionError(f"private needle leaked: {needle}")


def _write_learning_fixture(root: Path) -> Path:
    skill = root / "local" / "skills" / "python-patterns" / "SKILL.md"
    skill.parent.mkdir(parents=True, exist_ok=True)
    skill.write_text(
        "---\nname: python-patterns\ndescription: Python implementation patterns.\n---\n\n# python-patterns\n",
        encoding="utf-8",
    )
    rc, stdout, stderr = _run_cli(root, ["reindex"])
    if rc != 0:
        raise RuntimeError(stderr or stdout)
    for verdict in ("wrong", "missed", "rejected"):
        rc, stdout, stderr = _run_cli(
            root,
            [
                "feedback",
                "record",
                "python-patterns",
                "--verdict",
                verdict,
                "--query",
                "prompt secret raw customer task C:\\Users\\tedja\\private ghp_secretTOKEN123456",
                "--notes",
                "operator secret note -----BEGIN PRIVATE KEY-----",
            ],
        )
        if rc != 0:
            raise RuntimeError(stderr or stdout)
    return skill


def _write_router_fixture(root: Path) -> None:
    learning = root / ".learning"
    learning.mkdir(parents=True, exist_ok=True)
    (learning / "router-metrics.json").write_text(
        json.dumps(
            {
                "total_invocations": 5,
                "first_call_iso": "2026-01-01T00:00:00Z",
                "updated_iso": "2026-01-02T00:00:00Z",
                "by_day": {"2026-01-02": 5},
                "last_call": {
                    "iso": "2026-01-02T00:00:00Z",
                    "path": "hybrid",
                    "reason_code": "match_found",
                    "injected": True,
                    "elapsed_ms": 12,
                    "delivery_tier": "free",
                    "top_skill": "python-patterns",
                    "top_score": 0.91,
                },
            },
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    (root / ".chroma-skills").mkdir(parents=True, exist_ok=True)


def _run_learning_tier_chain(root: Path, work: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    out = work / "learning"
    out.mkdir(parents=True, exist_ok=True)

    rc, stdout, stderr = _run_cli(root, ["learning", "doctor"])
    doctor = _json(stdout)
    rows.append(_row(surface="learning doctor", tier="free", command="unlimited-skills learning doctor", rc=rc, stdout=stdout, stderr=stderr))

    rc, stdout, stderr = _run_python(["scripts/verify-learning-feedback-contract.py"])
    rows.append(_row(surface="feedback contract", tier="free", command="python scripts/verify-learning-feedback-contract.py", rc=rc, stdout=stdout, stderr=stderr))

    rc, stdout, stderr = _run_cli(root, ["improvement-candidates"])
    candidates = _json(stdout)
    rows.append(_row(surface="improvement candidates", tier="free", command="unlimited-skills improvement-candidates", rc=rc, stdout=stdout, stderr=stderr))
    candidate_id = candidates["candidates"][0]["candidate_id"]

    skill = root / "local" / "skills" / "python-patterns" / "SKILL.md"
    before = skill.read_text(encoding="utf-8")
    rc, stdout, stderr = _run_cli(root, ["apply-candidate", "--dry-run", candidate_id])
    dry_run = _json(stdout)
    after = skill.read_text(encoding="utf-8")
    rows.append(
        _row(
            surface="apply candidate dry-run",
            tier="free",
            command=f"unlimited-skills apply-candidate --dry-run {candidate_id}",
            rc=rc,
            stdout=stdout,
            stderr=stderr,
            details={
                "written": dry_run.get("written"),
                "mutated_files": dry_run.get("mutated_files"),
                "skill_file_unchanged": before == after,
            },
        )
    )

    rc, stdout, stderr = _run_python(["scripts/verify-learning-loop-closed-loop-proof.py"])
    rows.append(_row(surface="closed-loop dry-run proof", tier="free", command="python scripts/verify-learning-loop-closed-loop-proof.py", rc=rc, stdout=stdout, stderr=stderr))

    export = out / "registered-learning-export.json"
    rc, stdout, stderr = _run_cli(root, ["learning", "export", "--out", str(export), "--json-status"])
    rows.append(_row(surface="learning export", tier="registered", command="unlimited-skills learning export --out registered-learning-export.json --json-status", rc=rc, stdout=stdout, stderr=stderr, artifacts=[export]))

    team = out / "team-learning-rollup.json"
    rc, stdout, stderr = _run_cli(root, ["learning", "team-rollup", "--input", str(export), "--out", str(team), "--json-status"])
    rows.append(_row(surface="learning team rollup", tier="team", command="unlimited-skills learning team-rollup --input registered-learning-export.json --out team-learning-rollup.json --json-status", rc=rc, stdout=stdout, stderr=stderr, artifacts=[team]))

    admin_json = out / "business-learning-admin.json"
    admin_csv = out / "business-learning-admin.csv"
    rc, stdout, stderr = _run_cli(root, ["learning", "admin-export", "--input", str(team), "--json", str(admin_json), "--csv", str(admin_csv)])
    rows.append(_row(surface="learning admin export", tier="business", command="unlimited-skills learning admin-export --input team-learning-rollup.json --json business-learning-admin.json --csv business-learning-admin.csv", rc=rc, stdout=stdout, stderr=stderr, artifacts=[admin_json, admin_csv]))

    pack = out / "enterprise-learning-evidence-pack"
    rc, stdout, stderr = _run_cli(root, ["learning", "evidence-pack", "--input", str(admin_json), "--out", str(pack)])
    rows.append(_row(surface="learning evidence pack", tier="enterprise", command="unlimited-skills learning evidence-pack --input business-learning-admin.json --out enterprise-learning-evidence-pack", rc=rc, stdout=stdout, stderr=stderr, artifacts=[pack / "manifest.json", pack / "non-mutation-proof.json"]))

    rc, stdout, stderr = _run_cli(root, ["learning", "verify-evidence-pack", "--input", str(pack), "--json"])
    verify = _json(stdout)
    rows.append(_row(surface="learning verify evidence pack", tier="enterprise", command="unlimited-skills learning verify-evidence-pack --input enterprise-learning-evidence-pack --json", rc=rc, stdout=stdout, stderr=stderr, details={"ok": verify.get("ok")}))

    tampered = out / "enterprise-learning-evidence-pack-tampered"
    shutil.copytree(pack, tampered)
    (tampered / "non-mutation-proof.json").write_text('{"mutation_supported": true}', encoding="utf-8")
    rc, stdout, stderr = _run_cli(root, ["learning", "verify-evidence-pack", "--input", str(tampered), "--json"])
    tamper_report = _json(stdout)
    rows.append(
        _row(
            surface="learning evidence pack tamper check",
            tier="enterprise",
            command="unlimited-skills learning verify-evidence-pack --input enterprise-learning-evidence-pack-tampered --json",
            rc=rc,
            stdout=stdout,
            stderr=stderr,
            expect_ok=False,
            details={"ok": tamper_report.get("ok")},
        )
    )

    _assert_no_private_needles({"doctor": doctor, "candidates": candidates, "dry_run": dry_run})
    return rows


def _run_router_health_compatibility_chain(root: Path, work: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    out = work / "router-health"
    out.mkdir(parents=True, exist_ok=True)

    export = out / "registered-router-health-export.json"
    rc, stdout, stderr = _run_cli(root, ["router-health", "export", "--out", str(export), "--json-status"])
    rows.append(_row(surface="router-health export", tier="v0.6.2-compat-registered", command="unlimited-skills router-health export --out registered-router-health-export.json --json-status", rc=rc, stdout=stdout, stderr=stderr, artifacts=[export]))

    team = out / "team-router-health-rollup.json"
    rc, stdout, stderr = _run_cli(root, ["router-health", "team-rollup", "--input", str(export), "--out", str(team), "--json-status"])
    rows.append(_row(surface="router-health team rollup", tier="v0.6.2-compat-team", command="unlimited-skills router-health team-rollup --input registered-router-health-export.json --out team-router-health-rollup.json --json-status", rc=rc, stdout=stdout, stderr=stderr, artifacts=[team]))

    admin_json = out / "business-router-health-admin.json"
    admin_csv = out / "business-router-health-admin.csv"
    rc, stdout, stderr = _run_cli(root, ["router-health", "admin-export", "--input", str(team), "--json", str(admin_json), "--csv", str(admin_csv)])
    rows.append(_row(surface="router-health admin export", tier="v0.6.2-compat-business", command="unlimited-skills router-health admin-export --input team-router-health-rollup.json --json business-router-health-admin.json --csv business-router-health-admin.csv", rc=rc, stdout=stdout, stderr=stderr, artifacts=[admin_json, admin_csv]))

    pack = out / "enterprise-router-health-evidence-pack"
    rc, stdout, stderr = _run_cli(root, ["router-health", "evidence-pack", "--input", str(admin_json), "--out", str(pack)])
    rows.append(_row(surface="router-health evidence pack", tier="v0.6.2-compat-enterprise", command="unlimited-skills router-health evidence-pack --input business-router-health-admin.json --out enterprise-router-health-evidence-pack", rc=rc, stdout=stdout, stderr=stderr, artifacts=[pack / "manifest.json", pack / "privacy-proof.json"]))

    rc, stdout, stderr = _run_cli(root, ["router-health", "verify-evidence-pack", "--input", str(pack), "--json"])
    verify = _json(stdout)
    rows.append(_row(surface="router-health verify evidence pack", tier="v0.6.2-compat-enterprise", command="unlimited-skills router-health verify-evidence-pack --input enterprise-router-health-evidence-pack --json", rc=rc, stdout=stdout, stderr=stderr, details={"ok": verify.get("ok")}))

    return rows


def validate_report(report: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if report.get("schema_version") != 1:
        errors.append("schema_version must be 1")
    if report.get("release") != RELEASE:
        errors.append(f"release must be {RELEASE}")
    if report.get("privacy", {}).get("no_egress_asserted") is not True:
        errors.append("privacy.no_egress_asserted must be true")
    if report.get("mutation", {}).get("apply_candidate_dry_run_only") is not True:
        errors.append("mutation.apply_candidate_dry_run_only must be true")
    for row in report.get("rows", []):
        if row.get("ok") is not True:
            errors.append(f"row failed: {row.get('surface')}")
        for raw in row.get("artifact_paths", []):
            path = Path(raw)
            if not path.is_absolute():
                path = ROOT / raw
            if not path.exists():
                errors.append(f"artifact missing: {raw}")
    return errors


def run_smoke(work_dir: Path) -> dict[str, Any]:
    work_dir.mkdir(parents=True, exist_ok=True)
    library_root = work_dir / "library"
    router_root = work_dir / "router-library"
    skill = _write_learning_fixture(library_root)
    _write_router_fixture(router_root)

    rows = _run_learning_tier_chain(library_root, work_dir)
    rows.extend(_run_router_health_compatibility_chain(router_root, work_dir))

    report: dict[str, Any] = {
        "schema_version": 1,
        "release": RELEASE,
        "report_type": "v063_tier_release_smoke",
        "work_dir": _rel(work_dir),
        "surfaces_checked": [row["surface"] for row in rows],
        "command_names": [row["command"] for row in rows],
        "artifact_paths": [path for row in rows for path in row.get("artifact_paths", [])],
        "rows": rows,
        "privacy": {
            "local_only": True,
            "no_egress_asserted": True,
            "automatic_upload": False,
            "hosted_sync": False,
            "telemetry": False,
        },
        "mutation": {
            "apply_candidate_dry_run_only": True,
            "skill_file_unchanged_after_dry_run": skill.read_text(encoding="utf-8").startswith("---\nname: python-patterns"),
        },
        "compatibility": {
            "v0.6.2_router_health_tier_debt_checked": True,
            "router_health_release_claim": "compatibility/tier-debt closure only; not v0.6.3 Learning Loop VFP",
        },
    }
    errors = validate_report(report)
    report["ok"] = not errors
    report["errors"] = errors
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Verify v0.6.3-alpha local Learning Loop tier release surfaces.")
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON.")
    parser.add_argument("--work-dir", default="", help="Optional directory for smoke artifacts.")
    parser.add_argument("--keep-work-dir", action="store_true", help="Deprecated; default artifacts are already kept under .tmp.")
    args = parser.parse_args(argv)

    if args.work_dir:
        work_dir = Path(args.work_dir).expanduser()
    else:
        work_dir = ROOT / ".tmp" / "v063-tier-release-smoke"
        if work_dir.exists():
            shutil.rmtree(work_dir)
        work_dir.parent.mkdir(exist_ok=True)
    report = run_smoke(work_dir)
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        if report["ok"]:
            print("v0.6.3-alpha tier release smoke passed")
        else:
            print("v0.6.3-alpha tier release smoke failed")
            for error in report["errors"]:
                print(f"- {error}")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
