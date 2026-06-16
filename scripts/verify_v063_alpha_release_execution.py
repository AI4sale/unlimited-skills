"""Import shim for scripts/verify-v063-alpha-release-execution.py."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any

_PATH = Path(__file__).with_name("verify-v063-alpha-release-execution.py")
_SPEC = importlib.util.spec_from_file_location("verify_v063_alpha_release_execution_impl", _PATH)
if _SPEC is None or _SPEC.loader is None:
    raise RuntimeError(f"Unable to load release execution verifier: {_PATH}")
_MODULE = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MODULE)

globals().update({name: getattr(_MODULE, name) for name in dir(_MODULE) if not name.startswith("__")})


def __getattr__(name: str) -> Any:
    return getattr(_MODULE, name)
