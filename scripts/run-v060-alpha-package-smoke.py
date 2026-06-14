"""Build and clean-install smoke for the v0.6.0 contract freeze package.

This extends the v0.5.3 local event privacy package smoke with an
installed-wheel proof for the v0.6 privacy-safe local ROI receipt runtime. The
smoke proves that the package can generate Markdown and JSON receipts without
telemetry, upload, local path leakage, raw prompts, raw queries, raw events, or
paid ROI claims.
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
VERSION = "0.6.0"
NOTICE = (
    "This receipt is a local estimate from your own machine. It is not "
    "telemetry, not a benchmark guarantee, and not a paid ROI promise."
)


def load_v053_smoke():
    path = ROOT / "scripts" / "run-v053-alpha-package-smoke.py"
    spec = importlib.util.spec_from_file_location("run_v053_alpha_package_smoke", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load package smoke runner: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.VERSION = VERSION
    return module


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def clean_install_roi_receipt_smoke(smoke050, wheel: Path, work: Path) -> dict[str, Any]:
    env_dir = work / "venv-roi"
    venv.EnvBuilder(with_pip=True).create(env_dir)
    py = smoke050.venv_python(env_dir)
    cli = smoke050.venv_script(env_dir, "unlimited-skills")
    smoke050.run([str(py), "-m", "pip", "install", str(wheel)], cwd=work)

    library = work / "library"
    skill_file = library / "local" / "skills" / "roi-smoke" / "SKILL.md"
    skill_file.parent.mkdir(parents=True, exist_ok=True)
    skill_file.write_text(
        (
            "---\n"
            "name: roi-smoke\n"
            "description: Privacy-safe local ROI receipt smoke.\n"
            "---\n\n"
            "# ROI Smoke\n\n"
            "Verify local ROI receipts expose aggregate values only.\n"
        ),
        encoding="utf-8",
    )

    raw_query = "v060 private query needle aa-needle"
    raw_task = "v060 private task needle bb-needle"
    raw_notes = "v060 operator notes needle cc-needle"
    forbidden = [raw_query, raw_task, raw_notes, str(library), str(skill_file), "events.jsonl", "feedback.jsonl"]

    smoke050.run([str(cli), "--root", str(library), "reindex", "--no-native-sync", "--json"], cwd=work)
    smoke050.run([str(cli), "--root", str(library), "search", raw_query, "--mode", "lexical", "--json", "--no-native-sync"], cwd=work)
    smoke050.run([str(cli), "--root", str(library), "view", "roi-smoke", "--no-native-sync"], cwd=work)
    smoke050.run([str(cli), "--root", str(library), "use", "roi-smoke", "--query", raw_query, "--task", raw_task, "--no-native-sync"], cwd=work)
    smoke050.run([str(cli), "--root", str(library), "feedback", "roi-smoke", "--query", raw_query, "--verdict", "accepted", "--notes", raw_notes], cwd=work)
    legacy_dir = library / ".learning"
    legacy_dir.mkdir(parents=True, exist_ok=True)
    legacy_path = legacy_dir / "events.jsonl"
    with legacy_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps({"ts": 0.0, "type": "suggest", "payload": {"query": "legacy raw query must not appear"}}) + "\n")

    markdown = smoke050.run([str(cli), "--root", str(library), "roi", "receipt"], cwd=work).stdout
    json_result = smoke050.run([str(cli), "--root", str(library), "roi", "receipt", "--format", "json"], cwd=work)
    json_payload = json.loads(json_result.stdout)
    out_file = work / "roi-receipt.md"
    out_status = smoke050.run([str(cli), "--root", str(library), "roi", "receipt", "--format", "markdown", "--out", str(out_file)], cwd=work)
    since = smoke050.run([str(cli), "--root", str(library), "roi", "receipt", "--since", "7d"], cwd=work).stdout
    combined = markdown + json_result.stdout + out_file.read_text(encoding="utf-8", errors="replace") + since + out_status.stdout
    return {
        "markdown_has_title": "# Unlimited Skills local ROI receipt" in markdown,
        "markdown_has_notice": NOTICE in markdown,
        "json_report_type": json_payload.get("report_type"),
        "json_schema_version": json_payload.get("schema_version"),
        "json_notice": json_payload.get("privacy_notice"),
        "json_window_label": json_payload.get("window", {}).get("requested"),
        "out_written": out_file.is_file() and out_file.stat().st_size > 0,
        "out_status_path_leak": str(out_file) in out_status.stdout,
        "since_7d": "Window: 7d" in since,
        "legacy_unavailable": json_payload.get("window", {}).get("legacy_status") == "unavailable_legacy_logs",
        "contains_forbidden_needles": {needle: needle in combined for needle in forbidden},
    }


def verify(report: dict[str, Any], smoke053, smoke052, smoke050) -> list[str]:
    errors = list(smoke053.verify(report, smoke052, smoke050))
    roi = report.get("clean_install_roi_receipt") or {}
    for key in ("markdown_has_title", "markdown_has_notice", "out_written", "since_7d", "legacy_unavailable"):
        if roi.get(key) is not True:
            errors.append(f"ROI receipt smoke missing expected proof: {key}")
    if roi.get("json_report_type") != "local_roi_receipt":
        errors.append("ROI receipt JSON report_type mismatch")
    if roi.get("json_schema_version") != 1:
        errors.append("ROI receipt JSON schema_version mismatch")
    if roi.get("json_notice") != NOTICE:
        errors.append("ROI receipt JSON notice mismatch")
    if roi.get("json_window_label") != "all":
        errors.append("ROI receipt default JSON window must be all")
    if roi.get("out_status_path_leak"):
        errors.append("ROI receipt --out status leaked the local output path")
    leaked = [needle for needle, present in (roi.get("contains_forbidden_needles") or {}).items() if present]
    if leaked:
        errors.append("ROI receipt output leaked forbidden raw data: " + ", ".join(leaked))
    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--keep-temp", action="store_true")
    args = parser.parse_args(argv)

    smoke053 = load_v053_smoke()
    smoke052 = smoke053.load_v052_smoke()
    smoke050 = smoke052.load_v050_smoke()
    tmp = Path(tempfile.mkdtemp(prefix="uls-v060-package-smoke-"))
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
            "clean_install_roi_receipt": clean_install_roi_receipt_smoke(smoke050, wheel, tmp / "roi"),
        }
        report["errors"] = verify(report, smoke053, smoke052, smoke050)
        report["ok"] = not report["errors"]
        if args.json:
            print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
        else:
            print("v0.6.0-alpha package smoke: " + ("PASS" if report["ok"] else "FAIL"))
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
