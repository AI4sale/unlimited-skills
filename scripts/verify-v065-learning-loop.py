"""Verify O065 learning loop ranking and privacy contracts."""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from unlimited_skills import cli  # noqa: E402
from unlimited_skills.learning_loop import learning_doctor  # noqa: E402
from unlimited_skills.search_core import (  # noqa: E402
    candidate_sources,
    save_index,
    shared_candidate_family,
    task_summary_hash,
)


def _write_skill(root: Path, name: str, description: str, body: str = "") -> None:
    skill_dir = root / "registry" / "ecc" / "skills" / name
    skill_dir.mkdir(parents=True, exist_ok=True)
    (skill_dir / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: {description}\n---\n\n# {name}\n\n{body}\n",
        encoding="utf-8",
    )


def build_fixture(root: Path) -> Path:
    _write_skill(root, "social-publisher", "Publish social posts, LinkedIn updates, and replies.")
    _write_skill(root, "content-engine", "Plan and draft content posts, newsletters, editorial assets, and launch articles.")
    _write_skill(root, "marketing-campaign", "Launch marketing campaigns, messaging, and GTM copy.")
    _write_skill(root, "router-upgrade-maintenance", "Repair stale launchers after pip upgrade and package refresh.")
    _write_skill(root, "inject-refresh", "Refresh router inject artifacts, CLAUDE.md, AGENTS.md, and agent hooks.")
    _write_skill(root, "incident-debugger", "Debug production incidents, outages, logs, and failures.")
    _write_skill(root, "oauth-debugger", "Debug OAuth authentication callbacks, token exchange, and login failures.")
    _write_skill(root, "manual-decoy", "Debug delta epsilon workflow incidents.")
    _write_skill(root, "manual-target", "Debug delta epsilon workflow.")
    _write_skill(root, "manual-no-query-decoy", "Repair phi chi omega stale deployment errors.")
    _write_skill(root, "manual-no-query-target", "Repair phi chi omega stale deployment incident.")
    save_index(root)
    return root


def _names(root: Path, query: str, limit: int = 5) -> list[str]:
    return [hit.name for hit in shared_candidate_family(root, query, limit)]


def _hit(root: Path, query: str, name: str):
    return next((hit for hit in shared_candidate_family(root, query, 10) if hit.name == name), None)


def _run_cli(argv: list[str]) -> tuple[int, Any]:
    buffer = StringIO()
    with redirect_stdout(buffer):
        rc = cli.main(argv)
    text = buffer.getvalue().strip()
    try:
        payload = json.loads(text) if text else None
    except json.JSONDecodeError:
        payload = text
    return rc, payload


def _rank(names: list[str], target: str) -> int | None:
    return names.index(target) + 1 if target in names else None


def _privacy_scan(root: Path) -> dict[str, Any]:
    learning_dir = root / ".learning"
    text = "\n".join(
        path.read_text(encoding="utf-8", errors="replace")
        for path in sorted(learning_dir.glob("*.jsonl"))
    )
    forbidden = [
        "write linkedin launch article",
        "write linkedin launch post",
        "debug delta epsilon workflow incident",
        "repair phi chi omega stale deployment incident",
        "repair phi chi omega deployment incident",
        "operator private note",
        str(root),
    ]
    leaks = [needle for needle in forbidden if needle and needle in text]
    return {
        "ok": not leaks,
        "leaks": leaks,
        "query_token_hashes_present": "query_token_hashes" in text,
        "raw_query_phrases_absent": all(phrase not in text for phrase in forbidden[:6]),
    }


def build_report(root: Path) -> dict[str, Any]:
    build_fixture(root)
    exact_query = "write linkedin launch article"
    similar_query = "write linkedin launch post"
    rejected_query = "write social media content"
    manual_query = "debug delta epsilon workflow incident"
    manual_no_query = "repair phi chi omega stale deployment incident"
    manual_no_query_similar = "repair phi chi omega deployment incident"

    before_exact = _names(root, exact_query)
    before_similar = _names(root, similar_query)
    before_rejected = _names(root, rejected_query)
    before_manual = _names(root, manual_query)
    before_manual_no_query = _names(root, manual_no_query_similar)

    accepted_target = "marketing-campaign"
    rejected_target = "marketing-campaign"
    manual_target = "manual-target"
    manual_no_query_target = "manual-no-query-target"

    _run_cli(["--root", str(root), "feedback", "record", accepted_target, "--query", exact_query, "--verdict", "accepted", "--notes", "operator private note"])
    after_exact = _names(root, exact_query)
    after_similar = _names(root, similar_query)
    accepted_hit = _hit(root, similar_query, accepted_target)

    _run_cli(["--root", str(root), "feedback", "record", rejected_target, "--query", rejected_query, "--verdict", "wrong"])
    after_rejected = _names(root, rejected_query)
    rejected_hit = _hit(root, rejected_query, rejected_target)

    _run_cli(["--root", str(root), "search", manual_query, "--mode", "lexical", "--json", "--no-native-sync"])
    _run_cli(["--root", str(root), "view", manual_target, "--no-native-sync"])
    _run_cli(["--root", str(root), "use", manual_target, "--query", manual_query, "--task", "debug login", "--no-native-sync"])
    after_manual = _names(root, manual_query)
    manual_hit = _hit(root, manual_query, manual_target)

    _run_cli(["--root", str(root), "search", manual_no_query, "--mode", "lexical", "--json", "--no-native-sync"])
    _run_cli(["--root", str(root), "view", manual_no_query_target, "--no-native-sync"])
    _run_cli(["--root", str(root), "use", manual_no_query_target, "--no-native-sync"])
    after_manual_no_query = _names(root, manual_no_query_similar)
    manual_no_query_hit = _hit(root, manual_no_query_similar, manual_no_query_target)

    doctor = learning_doctor(root)
    privacy = _privacy_scan(root)
    rows = {
        "accepted_exact": {
            "query_summary_hash": task_summary_hash(exact_query),
            "before": before_exact,
            "after": after_exact,
            "target": accepted_target,
            "rank_before": _rank(before_exact, accepted_target),
            "rank_after": _rank(after_exact, accepted_target),
        },
        "accepted_similar": {
            "before": before_similar,
            "after": after_similar,
            "target": accepted_target,
            "rank_before": _rank(before_similar, accepted_target),
            "rank_after": _rank(after_similar, accepted_target),
            "sources": list(candidate_sources(accepted_hit)) if accepted_hit else [],
        },
        "rejected_wrong": {
            "before": before_rejected,
            "after": after_rejected,
            "target": rejected_target,
            "rank_before": _rank(before_rejected, rejected_target),
            "rank_after": _rank(after_rejected, rejected_target),
            "sources": list(candidate_sources(rejected_hit)) if rejected_hit else [],
        },
        "manual_search_view_use": {
            "before": before_manual,
            "after": after_manual,
            "target": manual_target,
            "rank_before": _rank(before_manual, manual_target),
            "rank_after": _rank(after_manual, manual_target),
            "sources": list(candidate_sources(manual_hit)) if manual_hit else [],
        },
        "manual_search_view_use_without_query": {
            "query_on_use": False,
            "before": before_manual_no_query,
            "after": after_manual_no_query,
            "target": manual_no_query_target,
            "rank_before": _rank(before_manual_no_query, manual_no_query_target),
            "rank_after": _rank(after_manual_no_query, manual_no_query_target),
            "sources": list(candidate_sources(manual_no_query_hit)) if manual_no_query_hit else [],
        },
    }
    failures = []
    if not (rows["accepted_exact"]["rank_after"] and rows["accepted_exact"]["rank_before"] and rows["accepted_exact"]["rank_after"] < rows["accepted_exact"]["rank_before"]):
        failures.append({"id": "accepted_exact", "reason": "accepted_feedback_did_not_boost_exact_query"})
    if not (rows["accepted_similar"]["rank_after"] and rows["accepted_similar"]["rank_before"] and rows["accepted_similar"]["rank_after"] < rows["accepted_similar"]["rank_before"]):
        failures.append({"id": "accepted_similar", "reason": "accepted_feedback_did_not_boost_similar_query"})
    if "learning_boost" not in rows["accepted_similar"]["sources"]:
        failures.append({"id": "accepted_similar", "reason": "learning_boost_source_missing"})
    if not (rows["rejected_wrong"]["rank_after"] and rows["rejected_wrong"]["rank_before"] and rows["rejected_wrong"]["rank_after"] > rows["rejected_wrong"]["rank_before"]):
        failures.append({"id": "rejected_wrong", "reason": "wrong_feedback_did_not_demote"})
    if "learning_demotion" not in rows["rejected_wrong"]["sources"]:
        failures.append({"id": "rejected_wrong", "reason": "learning_demotion_source_missing"})
    if not (rows["manual_search_view_use"]["rank_after"] and rows["manual_search_view_use"]["rank_before"] and rows["manual_search_view_use"]["rank_after"] < rows["manual_search_view_use"]["rank_before"]):
        failures.append({"id": "manual_search_view_use", "reason": "manual_use_did_not_boost_exact_query"})
    if "learning_boost" not in rows["manual_search_view_use"]["sources"]:
        failures.append({"id": "manual_search_view_use", "reason": "manual_learning_boost_source_missing"})
    if not (rows["manual_search_view_use_without_query"]["rank_after"] and rows["manual_search_view_use_without_query"]["rank_before"] and rows["manual_search_view_use_without_query"]["rank_after"] < rows["manual_search_view_use_without_query"]["rank_before"]):
        failures.append({"id": "manual_search_view_use_without_query", "reason": "manual_use_without_query_did_not_boost_similar_query"})
    if "learning_boost" not in rows["manual_search_view_use_without_query"]["sources"]:
        failures.append({"id": "manual_search_view_use_without_query", "reason": "manual_use_without_query_learning_boost_source_missing"})
    for key in (
        "learning_events_count",
        "last_learning_event_type",
        "accepted_events_count",
        "rejected_wrong_events_count",
        "learning_boost_active",
        "learning_demotion_active",
        "last_query_fingerprint_present",
        "privacy_ok",
    ):
        if key not in doctor:
            failures.append({"id": "learning_doctor", "reason": f"missing_{key}"})
    if not privacy["ok"] or not privacy["query_token_hashes_present"] or not privacy["raw_query_phrases_absent"]:
        failures.append({"id": "privacy", "reason": "learning_log_privacy_failure", "details": privacy})
    return {
        "ok": not failures,
        "schema_version": "v065-learning-loop-v1",
        "root": str(root),
        "rows": rows,
        "doctor": doctor,
        "privacy": privacy,
        "failures": failures,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--root",
        default="",
        help="Existing library root for installed-library smoke metadata. The verifier still uses an isolated fixture.",
    )
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    with tempfile.TemporaryDirectory(prefix="uls-v065-learning-loop-") as tmp:
        report = build_report(Path(tmp) / "library")
        if args.root:
            installed_root = Path(args.root).expanduser()
            report["installed_library_smoke"] = {
                "root": str(installed_root),
                "root_present": installed_root.exists(),
                "mutated": False,
            }
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        status = "PASS" if report["ok"] else "FAIL"
        print(f"C065 learning-loop verifier: {status} ({len(report['failures'])} failures)")
        for name, row in report["rows"].items():
            print(f"- {name}: before={row['before'][:3]} after={row['after'][:3]}")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
