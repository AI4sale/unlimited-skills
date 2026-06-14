"""Build and clean-install smoke for the v0.6.2 non-English routing hotfix."""

from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VERSION = "0.6.2"


def load_v060_smoke():
    path = ROOT / "scripts" / "run-v060-alpha-package-smoke.py"
    spec = importlib.util.spec_from_file_location("run_v060_alpha_package_smoke", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load package smoke runner: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.VERSION = VERSION
    return module


def load_v053_smoke():
    return load_v060_smoke().load_v053_smoke()


def clean_install_roi_receipt_smoke(smoke050, wheel: Path, work: Path) -> dict:
    return load_v060_smoke().clean_install_roi_receipt_smoke(smoke050, wheel, work)


def verify(report: dict, smoke053, smoke052, smoke050) -> list[str]:
    return load_v060_smoke().verify(report, smoke053, smoke052, smoke050)


def main(argv: list[str] | None = None) -> int:
    return load_v060_smoke().main(argv)


if __name__ == "__main__":
    raise SystemExit(main())
