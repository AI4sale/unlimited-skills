"""Build and clean-install smoke for the v0.5.3 local event privacy package.

This extends the v0.5.2 adoption instrumentation smoke with an installed-wheel
check for A4.10 local event privacy hardening. The smoke proves that the
packaged CLI persists privacy-safe local learning rows, not just that source
tests pass in the checkout.
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
VERSION = "0.5.3"


def load_v052_smoke():
    path = ROOT / "scripts" / "run-v052-alpha-package-smoke.py"
    spec = importlib.util.spec_from_file_location("run_v052_alpha_package_smoke", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load package smoke runner: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.VERSION = VERSION
    return module


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def clean_install_local_event_privacy_smoke(smoke050, wheel: Path, work: Path) -> dict[str, Any]:
    env_dir = work / "venv-privacy"
    venv.EnvBuilder(with_pip=True).create(env_dir)
    py = smoke050.venv_python(env_dir)
    cli = smoke050.venv_script(env_dir, "unlimited-skills")
    smoke050.run([str(py), "-m", "pip", "install", str(wheel)], cwd=work)

    library = work / "library"
    skill_file = library / "local" / "skills" / "privacy-smoke" / "SKILL.md"
    skill_file.parent.mkdir(parents=True, exist_ok=True)
    skill_file.write_text(
        (
            "---\n"
            "name: privacy-smoke\n"
            "description: Privacy-safe local event persistence smoke.\n"
            "---\n\n"
            "# Privacy Smoke\n\n"
            "Verify local event and feedback logs do not persist raw task data.\n"
        ),
        encoding="utf-8",
    )

    raw_query = "v053 private query needle aa-needle"
    raw_task = "v053 private task needle bb-needle"
    raw_notes = "v053 operator notes needle cc-needle"
    forbidden = [raw_query, raw_task, raw_notes, str(library), str(skill_file)]

    smoke050.run([str(cli), "--root", str(library), "reindex", "--no-native-sync", "--json"], cwd=work)
    smoke050.run([str(cli), "--root", str(library), "search", raw_query, "--mode", "lexical", "--json", "--no-native-sync"], cwd=work)
    smoke050.run([str(cli), "--root", str(library), "list", "--filter", raw_query, "--json", "--no-native-sync"], cwd=work)
    smoke050.run([str(cli), "--root", str(library), "view", "privacy-smoke", "--no-native-sync"], cwd=work)
    smoke050.run([str(cli), "--root", str(library), "use", "privacy-smoke", "--query", raw_query, "--task", raw_task, "--no-native-sync"], cwd=work)
    smoke050.run([str(cli), "--root", str(library), "feedback", "privacy-smoke", "--query", raw_query, "--verdict", "accepted", "--notes", raw_notes], cwd=work)

    event_path = library / ".learning" / "events.jsonl"
    feedback_path = library / ".learning" / "feedback.jsonl"
    event_text = event_path.read_text(encoding="utf-8")
    feedback_text = feedback_path.read_text(encoding="utf-8")
    combined = event_text + feedback_text
    event_rows = read_jsonl(event_path)
    feedback_rows = read_jsonl(feedback_path)
    search_payload = next(row["payload"] for row in event_rows if row["type"] == "search")
    use_payload = next(row["payload"] for row in event_rows if row["type"] == "skill_used")
    feedback_payload = feedback_rows[-1]
    return {
        "event_count": len(event_rows),
        "feedback_count": len(feedback_rows),
        "contains_forbidden_needles": {needle: needle in combined for needle in forbidden},
        "search_has_query": "query" in search_payload,
        "search_has_query_summary_hash": bool(search_payload.get("query_summary_hash")),
        "search_hit_has_path": any("path" in hit for hit in search_payload.get("hits", [])),
        "search_hit_has_score": any("score" in hit for hit in search_payload.get("hits", [])),
        "search_hit_has_score_bucket": all("score_bucket" in hit for hit in search_payload.get("hits", [])),
        "use_has_query": "query" in use_payload,
        "use_has_task": "task" in use_payload,
        "use_has_library_path": use_payload.get("library_path") == "local/skills/privacy-smoke/SKILL.md",
        "feedback_has_query": "query" in feedback_payload,
        "feedback_has_notes": "notes" in feedback_payload,
        "feedback_has_query_summary_hash": bool(feedback_payload.get("query_summary_hash")),
        "feedback_has_notes_bucket": feedback_payload.get("notes_length_bucket") in {"short", "medium", "long"},
    }


def verify(report: dict[str, Any], smoke052, smoke050) -> list[str]:
    errors = list(smoke052.verify(report, smoke050))
    privacy = report.get("clean_install_local_event_privacy") or {}
    if privacy.get("event_count", 0) < 3:
        errors.append("privacy smoke must persist search/view/use events")
    if privacy.get("feedback_count", 0) < 1:
        errors.append("privacy smoke must persist one feedback row")
    leaked = [needle for needle, present in (privacy.get("contains_forbidden_needles") or {}).items() if present]
    if leaked:
        errors.append("privacy smoke persisted forbidden raw data: " + ", ".join(leaked))
    for key in ("search_has_query", "search_hit_has_path", "search_hit_has_score", "use_has_query", "use_has_task", "feedback_has_query", "feedback_has_notes"):
        if privacy.get(key):
            errors.append(f"privacy smoke persisted forbidden field: {key}")
    for key in ("search_has_query_summary_hash", "search_hit_has_score_bucket", "use_has_library_path", "feedback_has_query_summary_hash", "feedback_has_notes_bucket"):
        if privacy.get(key) is not True:
            errors.append(f"privacy smoke missing expected safe field: {key}")
    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--keep-temp", action="store_true")
    args = parser.parse_args(argv)

    smoke052 = load_v052_smoke()
    smoke050 = smoke052.load_v050_smoke()
    tmp = Path(tempfile.mkdtemp(prefix="uls-v053-package-smoke-"))
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
            "clean_install_local_event_privacy": clean_install_local_event_privacy_smoke(smoke050, wheel, tmp / "privacy"),
        }
        report["errors"] = verify(report, smoke052, smoke050)
        report["ok"] = not report["errors"]
        if args.json:
            print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
        else:
            print("v0.5.3-alpha package smoke: " + ("PASS" if report["ok"] else "FAIL"))
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
