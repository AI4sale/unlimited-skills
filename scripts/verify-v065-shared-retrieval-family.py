"""Compatibility wrapper for the O065 shared retrieval-family verifier."""

from __future__ import annotations

import importlib.util
from pathlib import Path


SCRIPT_PATH = Path(__file__).with_name("verify-v065-shared-candidate-family.py")
spec = importlib.util.spec_from_file_location("verify_v065_shared_candidate_family", SCRIPT_PATH)
module = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(module)


if __name__ == "__main__":
    raise SystemExit(module.main())
