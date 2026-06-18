from __future__ import annotations

import importlib.util
import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = REPO_ROOT / "scripts" / "verify-v065-learning-loop.py"
spec = importlib.util.spec_from_file_location("verify_v065_learning_loop", SCRIPT_PATH)
learning_loop = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(learning_loop)


def test_learning_loop_verifier_passes_fixture(tmp_path: Path) -> None:
    report = learning_loop.build_report(tmp_path / "library")
    assert report["ok"] is True, json.dumps(report, ensure_ascii=False, indent=2)
    assert report["doctor"]["learning_boost_active"] is True
    assert report["doctor"]["learning_demotion_active"] is True
    assert report["privacy"]["ok"] is True


def test_learning_loop_privacy_rejects_raw_query_tokens(tmp_path: Path) -> None:
    root = tmp_path / "library"
    learning_loop.build_fixture(root)
    unsafe = root / ".learning"
    unsafe.mkdir(parents=True, exist_ok=True)
    (unsafe / "feedback.jsonl").write_text(
        json.dumps({"name": "content-engine", "verdict": "accepted", "query": "write linkedin launch article"}) + "\n",
        encoding="utf-8",
    )
    privacy = learning_loop._privacy_scan(root)
    assert privacy["ok"] is False
