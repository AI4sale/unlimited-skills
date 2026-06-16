from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
RELEASE = "v0.6.4-alpha"
REPORT_TYPE = "v064_money_saved_tier_smoke"
FIXTURE_DIR = ROOT / "tests" / "fixtures" / "money_saved_meter"
PRIVATE_NEEDLES = [
    "raw prompt",
    "raw task",
    "skill body",
    "C:\\Users\\",
    "ghp_",
    "-----BEGIN PRIVATE KEY-----",
]
ASSERTED_OVERCLAIMS = [
    "exact tokens saved",
    "exact money saved",
    "bill reduction guaranteed",
    "guaranteed bill reduction",
]
EXPECTED_SURFACES = [
    "money-saved meter",
    "money-saved registered-export",
    "money-saved team-rollup",
    "money-saved admin-export",
    "money-saved evidence-pack",
    "money-saved verify-evidence-pack",
    "money-saved evidence-pack tamper check",
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
        ok = rc != 0 and not missing
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


def _path_from_report(raw: str) -> Path:
    path = Path(raw)
    return path if path.is_absolute() else ROOT / raw


def _iter_json_artifacts(report: dict[str, Any]) -> list[tuple[Path, dict[str, Any]]]:
    artifacts: list[tuple[Path, dict[str, Any]]] = []
    for row in report.get("rows", []):
        for raw in row.get("artifact_paths", []):
            path = _path_from_report(raw)
            if path.suffix.lower() != ".json" or not path.exists():
                continue
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if isinstance(payload, dict):
                artifacts.append((path, payload))
    return artifacts


def _scan_private_needles(value: Any) -> list[str]:
    hits: set[str] = set()

    def visit(raw: Any, *, key_path: tuple[str, ...] = ()) -> None:
        if any(key in {"forbidden_fields", "forbidden_claims", "non_claims"} for key in key_path):
            return
        if isinstance(raw, dict):
            for key, child in raw.items():
                visit(child, key_path=(*key_path, str(key)))
            return
        if isinstance(raw, list):
            for child in raw:
                visit(child, key_path=key_path)
            return
        if not isinstance(raw, str):
            return
        text = raw.lower()
        for needle in PRIVATE_NEEDLES:
            if needle.lower() in text:
                hits.add(needle)

    visit(value)
    return sorted(hits)


def _asserted_claim_errors(path: Path, value: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    claim_boundary = value.get("claim_boundary")
    if not isinstance(claim_boundary, dict):
        return errors
    allowed = claim_boundary.get("allowed_claims", [])
    if not isinstance(allowed, list):
        errors.append(f"{_rel(path)} claim_boundary.allowed_claims must be a list")
        return errors
    allowed_text = " ".join(str(item).lower() for item in allowed)
    for needle in ASSERTED_OVERCLAIMS:
        if needle in allowed_text:
            errors.append(f"{_rel(path)} asserts forbidden claim in allowed_claims: {needle}")
    return errors


def _boundary_errors(path: Path, value: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    private_hits = _scan_private_needles(value)
    if private_hits:
        errors.append(f"{_rel(path)} leaked private/sensitive needles: {private_hits}")

    dollars = value.get("dollars")
    if isinstance(dollars, dict) and dollars.get("enabled") is not False:
        errors.append(f"{_rel(path)} dollars.enabled must stay false")

    privacy = value.get("privacy")
    if isinstance(privacy, dict):
        if privacy.get("upload") not in (None, False):
            errors.append(f"{_rel(path)} privacy.upload must be false")
        for key in ("hosted_telemetry", "telemetry", "analytics", "network_access"):
            if privacy.get(key) not in (None, False):
                errors.append(f"{_rel(path)} privacy.{key} must be false")
        for key, raw in privacy.items():
            if str(key).endswith("_included") and raw is not False:
                errors.append(f"{_rel(path)} privacy.{key} must be false")

    delivery = value.get("delivery")
    if isinstance(delivery, dict):
        for key in ("network_fetch", "hosted_sync", "upload", "hosted_dashboard", "billing_or_entitlement", "telemetry", "dashboard"):
            if delivery.get(key) not in (None, False):
                errors.append(f"{_rel(path)} delivery.{key} must be false")

    measured = value.get("measured")
    estimated = value.get("estimated")
    if isinstance(measured, dict) and any("estimated_token" in str(key) for key in measured):
        errors.append(f"{_rel(path)} measured block must not contain estimated token fields")
    if isinstance(estimated, dict) and estimated.get("measurement_kind") not in (None, "estimated"):
        errors.append(f"{_rel(path)} estimated.measurement_kind must be estimated")

    estimates = value.get("estimates")
    if isinstance(estimates, dict):
        dollar_estimate = estimates.get("estimated_dollar_value")
        if isinstance(dollar_estimate, dict) and dollar_estimate.get("enabled") is not False:
            errors.append(f"{_rel(path)} estimates.estimated_dollar_value.enabled must be false")
        token_estimate = estimates.get("estimated_tokens_avoided")
        if isinstance(token_estimate, dict) and token_estimate.get("measurement_kind") != "estimated":
            errors.append(f"{_rel(path)} estimated_tokens_avoided must stay estimated")

    non_claims = value.get("non_claims")
    if isinstance(non_claims, dict):
        for key in ("exact_money", "exact_tokens", "bill_reduction"):
            if non_claims.get(key) is not False:
                errors.append(f"{_rel(path)} non_claims.{key} must be false")

    errors.extend(_asserted_claim_errors(path, value))
    return errors


def validate_report(report: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if report.get("schema_version") != 1:
        errors.append("schema_version must be 1")
    if report.get("release") != RELEASE:
        errors.append(f"release must be {RELEASE}")
    if report.get("report_type") != REPORT_TYPE:
        errors.append(f"report_type must be {REPORT_TYPE}")
    if report.get("privacy", {}).get("local_only") is not True:
        errors.append("privacy.local_only must be true")
    if report.get("privacy", {}).get("no_egress_asserted") is not True:
        errors.append("privacy.no_egress_asserted must be true")
    if report.get("claims", {}).get("dollars_disabled_by_default") is not True:
        errors.append("claims.dollars_disabled_by_default must be true")
    if report.get("claims", {}).get("exact_money_claims") is not False:
        errors.append("claims.exact_money_claims must be false")
    if report.get("claims", {}).get("exact_token_claims") is not False:
        errors.append("claims.exact_token_claims must be false")
    if report.get("claims", {}).get("bill_reduction_claims") is not False:
        errors.append("claims.bill_reduction_claims must be false")

    surfaces = [row.get("surface") for row in report.get("rows", [])]
    for surface in EXPECTED_SURFACES:
        if surface not in surfaces:
            errors.append(f"missing surface: {surface}")

    for row in report.get("rows", []):
        if row.get("ok") is not True:
            errors.append(f"row failed: {row.get('surface')}")
        for raw in row.get("artifact_paths", []):
            path = _path_from_report(raw)
            if not path.exists():
                errors.append(f"artifact missing: {raw}")
    tamper = next((row for row in report.get("rows", []) if row.get("surface") == "money-saved evidence-pack tamper check"), None)
    if not isinstance(tamper, dict):
        errors.append("tamper row missing")
    elif tamper.get("expected_success") is not False or tamper.get("returncode") == 0 or tamper.get("details", {}).get("ok") is not False:
        errors.append("tamper row must prove verifier fails closed with ok=false")

    for path, payload in _iter_json_artifacts(report):
        errors.extend(_boundary_errors(path, payload))

    return errors


def run_smoke(work_dir: Path) -> dict[str, Any]:
    if work_dir.exists():
        shutil.rmtree(work_dir)
    work_dir.mkdir(parents=True, exist_ok=True)
    library_root = work_dir / "library"
    library_root.mkdir(parents=True, exist_ok=True)
    out = work_dir / "money-saved"
    out.mkdir(parents=True, exist_ok=True)

    rows: list[dict[str, Any]] = []
    mcp_fixture = FIXTURE_DIR / "100-call-mcp-savings.json"
    audit_fixture = FIXTURE_DIR / "100-call-gateway-audit.jsonl"
    free_report = out / "free-money-saved-meter.json"
    registered = out / "registered-money-saved.json"
    team = out / "team-money-saved.json"
    admin_json = out / "business-money-saved-admin.json"
    admin_csv = out / "business-money-saved-admin.csv"
    evidence = out / "enterprise-money-saved-evidence-pack"
    tampered = out / "enterprise-money-saved-evidence-pack-tampered"

    rc, stdout, stderr = _run_cli(
        library_root,
        [
            "money-saved",
            "meter",
            "--json",
            "--fixture-100-call",
            "--out",
            str(free_report),
            "--json-status",
        ],
    )
    rows.append(_row(surface="money-saved meter", tier="free", command="unlimited-skills money-saved meter --json --fixture-100-call --out free-money-saved-meter.json --json-status", rc=rc, stdout=stdout, stderr=stderr, artifacts=[free_report]))

    rc, stdout, stderr = _run_cli(
        library_root,
        [
            "money-saved",
            "registered-export",
            "--mcp-savings-json",
            str(mcp_fixture),
            "--audit-log",
            str(audit_fixture),
            "--target-calls",
            "100",
            "--out",
            str(registered),
            "--json-status",
        ],
    )
    rows.append(_row(surface="money-saved registered-export", tier="registered", command="unlimited-skills money-saved registered-export --mcp-savings-json 100-call-mcp-savings.json --audit-log 100-call-gateway-audit.jsonl --target-calls 100 --out registered-money-saved.json --json-status", rc=rc, stdout=stdout, stderr=stderr, artifacts=[registered]))

    rc, stdout, stderr = _run_cli(
        library_root,
        [
            "money-saved",
            "team-rollup",
            "--input",
            str(registered),
            "--alias",
            "member-a",
            "--out",
            str(team),
            "--json-status",
        ],
    )
    rows.append(_row(surface="money-saved team-rollup", tier="team", command="unlimited-skills money-saved team-rollup --input registered-money-saved.json --alias member-a --out team-money-saved.json --json-status", rc=rc, stdout=stdout, stderr=stderr, artifacts=[team]))

    rc, stdout, stderr = _run_cli(
        library_root,
        [
            "money-saved",
            "admin-export",
            "--input",
            str(team),
            "--json",
            str(admin_json),
            "--csv",
            str(admin_csv),
        ],
    )
    rows.append(_row(surface="money-saved admin-export", tier="business", command="unlimited-skills money-saved admin-export --input team-money-saved.json --json business-money-saved-admin.json --csv business-money-saved-admin.csv", rc=rc, stdout=stdout, stderr=stderr, artifacts=[admin_json, admin_csv]))

    rc, stdout, stderr = _run_cli(
        library_root,
        [
            "money-saved",
            "evidence-pack",
            "--input",
            str(admin_json),
            "--out",
            str(evidence),
        ],
    )
    rows.append(_row(surface="money-saved evidence-pack", tier="enterprise", command="unlimited-skills money-saved evidence-pack --input business-money-saved-admin.json --out enterprise-money-saved-evidence-pack", rc=rc, stdout=stdout, stderr=stderr, artifacts=[evidence / "manifest.json", evidence / "privacy-proof.json", evidence / "measurement-proof.json", evidence / "claim-boundary-proof.json"]))

    rc, stdout, stderr = _run_cli(library_root, ["money-saved", "verify-evidence-pack", "--input", str(evidence), "--json"])
    verify = _json(stdout)
    rows.append(_row(surface="money-saved verify-evidence-pack", tier="enterprise", command="unlimited-skills money-saved verify-evidence-pack --input enterprise-money-saved-evidence-pack --json", rc=rc, stdout=stdout, stderr=stderr, details={"ok": verify.get("ok"), "checks": verify.get("checks", [])}))

    shutil.copytree(evidence, tampered)
    privacy = tampered / "privacy-proof.json"
    privacy.write_text('{"tampered": true, "upload": true}\n', encoding="utf-8")
    rc, stdout, stderr = _run_cli(library_root, ["money-saved", "verify-evidence-pack", "--input", str(tampered), "--json"])
    tamper_report = _json(stdout)
    rows.append(
        _row(
            surface="money-saved evidence-pack tamper check",
            tier="enterprise",
            command="unlimited-skills money-saved verify-evidence-pack --input enterprise-money-saved-evidence-pack-tampered --json",
            rc=rc,
            stdout=stdout,
            stderr=stderr,
            expect_ok=False,
            details={"ok": tamper_report.get("ok"), "checks": tamper_report.get("checks", [])},
        )
    )

    report: dict[str, Any] = {
        "schema_version": 1,
        "release": RELEASE,
        "report_type": REPORT_TYPE,
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
        "claims": {
            "exact_counts_stay_counts": True,
            "measured_bytes_stay_measured": True,
            "tokens_are_estimates": True,
            "dollars_disabled_by_default": True,
            "exact_money_claims": False,
            "exact_token_claims": False,
            "bill_reduction_claims": False,
            "hundred_call_frame_is_cadence_not_billing_math": True,
        },
    }
    errors = validate_report(report)
    report["ok"] = not errors
    report["errors"] = errors
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Verify v0.6.4 Money Saved Meter tier smoke surfaces.")
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON.")
    parser.add_argument("--work-dir", default="", help="Optional directory for smoke artifacts.")
    parser.add_argument("--keep-work-dir", action="store_true", help="Deprecated; artifacts are kept under .tmp by default.")
    args = parser.parse_args(argv)

    if args.work_dir:
        work_dir = Path(args.work_dir).expanduser()
    else:
        work_dir = ROOT / ".tmp" / "v064-money-saved-tier-smoke"
    report = run_smoke(work_dir)
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        if report["ok"]:
            print("v0.6.4 Money Saved tier smoke passed")
        else:
            print("v0.6.4 Money Saved tier smoke failed")
            for error in report["errors"]:
                print(f"- {error}")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
