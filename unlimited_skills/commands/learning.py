"""Learning Loop command wrappers."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def _emit(payload: dict) -> int:
    from ..learning_loop import assert_privacy_safe

    assert_privacy_safe(payload)
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


def cmd_learning_doctor(args: argparse.Namespace) -> int:
    from ..learning_loop import learning_doctor

    root = Path(args.root).expanduser()
    return _emit(learning_doctor(root))


def cmd_improvement_candidates(args: argparse.Namespace) -> int:
    from ..learning_loop import build_improvement_candidates

    root = Path(args.root).expanduser()
    candidates = [candidate.to_json() for candidate in build_improvement_candidates(root)]
    payload = {
        "schema_version": 1,
        "status": "ok",
        "candidate_count": len(candidates),
        "candidates": candidates,
        "message": "No improvement candidates found." if not candidates else "Improvement candidates generated from local feedback.",
        "privacy": {
            "local_only": True,
            "prompts_included": False,
            "raw_queries_included": False,
            "raw_notes_included": False,
            "skill_bodies_included": False,
            "local_paths_included": False,
            "tokens_included": False,
            "keys_included": False,
        },
    }
    return _emit(payload)


def cmd_apply_candidate(args: argparse.Namespace) -> int:
    from ..learning_loop import dry_run_candidate

    if not args.dry_run:
        print("apply-candidate currently supports --dry-run only; no files were modified.", file=__import__("sys").stderr)
        return 2
    root = Path(args.root).expanduser()
    return _emit(dry_run_candidate(root, args.candidate_id))
