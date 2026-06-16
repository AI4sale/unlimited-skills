"""Import shim for scripts/verify-v064-alpha-release-execution.py."""

from __future__ import annotations

import importlib.util
from pathlib import Path

_PATH = Path(__file__).with_name("verify-v064-alpha-release-execution.py")
_SPEC = importlib.util.spec_from_file_location("verify_v064_alpha_release_execution_impl", _PATH)
if _SPEC is None or _SPEC.loader is None:
    raise RuntimeError(f"Unable to load release execution verifier: {_PATH}")
_MODULE = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MODULE)

main = _MODULE.main

if __name__ == "__main__":
    raise SystemExit(main())
