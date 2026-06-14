from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "fixtures" / "learning-loop" / "closed-loop-proof-feedback.jsonl"
PRIVATE_NEEDLES = [
    "prompt secret",
    "raw customer task",
    "operator secret note",
    "C:\\Users\\tedja\\private",
    "ghp_secretTOKEN123456",
    "-----BEGIN PRIVATE KEY-----",
]


def _run(args: list[str]) -> tuple[int, str, str]:
    completed = subprocess.run(
        [sys.executable, "-m", "unlimited_skills.cli", *args],
        cwd=ROOT,
        text=True,
        encoding="utf-8",
        errors="replace",
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    return completed.returncode, completed.stdout, completed.stderr


def _json(stdout: str) -> dict[str, Any]:
    return json.loads(stdout)


def _assert_private_needles_absent(value: object) -> None:
    text = json.dumps(value, ensure_ascii=False, sort_keys=True)
    for needle in PRIVATE_NEEDLES:
        if needle in text:
            raise AssertionError(f"private needle leaked: {needle}")
    if ":\\" in text or ":/" in text:
        raise AssertionError("local path marker leaked")


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="us-learning-loop-proof-") as tmp:
        root = Path(tmp) / "library"
        skill_id = "skill-1a2b3c4d5e6f"
        skill = root / "local" / "skills" / skill_id / "SKILL.md"
        skill.parent.mkdir(parents=True, exist_ok=True)
        skill.write_text(
            f"---\nname: {skill_id}\ndescription: Synthetic implementation patterns.\n---\n\n# {skill_id}\n",
            encoding="utf-8",
        )
        rc, stdout, stderr = _run(["--root", str(root), "reindex"])
        if rc != 0:
            raise RuntimeError(stderr or stdout)

        raw_query = "prompt secret raw customer task C:\\Users\\tedja\\private ghp_secretTOKEN123456"
        raw_notes = "operator secret note -----BEGIN PRIVATE KEY-----"
        rc, stdout, stderr = _run(
            [
                "--root",
                str(root),
                "feedback",
                "record",
                skill_id,
                "--verdict",
                "wrong",
                "--query",
                raw_query,
                "--notes",
                raw_notes,
            ]
        )
        if rc != 0:
            raise RuntimeError(stderr or stdout)
        stored_feedback = _json(stdout)

        rc, stdout, stderr = _run(["--root", str(root), "learning", "doctor"])
        if rc != 0:
            raise RuntimeError(stderr or stdout)
        doctor = _json(stdout)

        rc, stdout, stderr = _run(["--root", str(root), "improvement-candidates"])
        if rc != 0:
            raise RuntimeError(stderr or stdout)
        candidates = _json(stdout)
        candidate_id = candidates["candidates"][0]["candidate_id"]

        before = skill.read_text(encoding="utf-8")
        rc, stdout, stderr = _run(["--root", str(root), "apply-candidate", "--dry-run", candidate_id])
        if rc != 0:
            raise RuntimeError(stderr or stdout)
        dry_run = _json(stdout)
        after = skill.read_text(encoding="utf-8")

        proof = {
            "schema_version": 1,
            "report_type": "learning_loop_closed_loop_proof",
            "feedback_input": {
                "skill_label": "opaque synthetic local skill id",
                "verdict": "wrong",
                "raw_query_stored": False,
                "raw_notes_stored": False,
            },
            "stored_feedback_row": stored_feedback,
            "learning_doctor": {
                "feedback_count": doctor["feedback_count"],
                "feedback_outcomes": doctor["feedback_outcomes"],
                "candidate_count": doctor["candidate_count"],
                "candidate_ids": doctor["candidate_ids"],
                "privacy": doctor["privacy"],
            },
            "improvement_candidates": candidates,
            "dry_run_preview": dry_run,
            "verification": {
                "fixture": str(FIXTURE.relative_to(ROOT)).replace("\\", "/"),
                "dry_run_written_false": dry_run.get("written") is False,
                "dry_run_mutated_files_empty": dry_run.get("mutated_files") == [],
                "skill_file_unchanged": before == after,
                "local_only": True,
            },
        }
        _assert_private_needles_absent(proof)
        if not proof["verification"]["dry_run_written_false"] or not proof["verification"]["skill_file_unchanged"]:
            raise AssertionError("dry-run mutation boundary failed")
        fixture_target = root / ".learning" / "closed-loop-proof-feedback.jsonl"
        fixture_target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(FIXTURE, fixture_target)
        print(json.dumps(proof, ensure_ascii=False, indent=2, sort_keys=True))
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
