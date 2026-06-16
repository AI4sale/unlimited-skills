"""Import shim for scripts/run-v064-alpha-package-smoke.py."""

from __future__ import annotations

import importlib.util
from pathlib import Path

_PATH = Path(__file__).with_name("run-v064-alpha-package-smoke.py")
_SPEC = importlib.util.spec_from_file_location("run_v064_alpha_package_smoke_impl", _PATH)
if _SPEC is None or _SPEC.loader is None:
    raise RuntimeError(f"Unable to load package smoke runner: {_PATH}")
_MODULE = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MODULE)

main = _MODULE.main
verify_report = _MODULE.verify_report

if __name__ == "__main__":
    raise SystemExit(main())
