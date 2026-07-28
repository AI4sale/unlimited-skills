from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CONTRACT_ROOT = ROOT / "contracts" / "fleet" / "v1"
MANIFEST_PATH = CONTRACT_ROOT / "contract-manifest.json"


def digest(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def build_manifest() -> dict:
    files = {
        path.relative_to(CONTRACT_ROOT).as_posix(): digest(path)
        for path in sorted(CONTRACT_ROOT.rglob("*.json"))
        if path != MANIFEST_PATH
    }
    return {
        "bundle_revision": 2,
        "compatibility": "v1-additive-optional-only",
        "contract_id": "unlimited-skills.fleet-wire",
        "files": files,
        "major_version": 1,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()
    rendered = json.dumps(
        build_manifest(),
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
    ) + "\n"
    if args.write:
        MANIFEST_PATH.write_bytes(rendered.encode("utf-8"))
    elif not MANIFEST_PATH.is_file() or MANIFEST_PATH.read_text(encoding="utf-8") != rendered:
        print(json.dumps({"ok": False, "reason": "contract_manifest_drift"}))
        return 1
    print(
        json.dumps(
            {
                "ok": True,
                "manifest_sha256": "sha256:"
                + hashlib.sha256(rendered.encode("utf-8")).hexdigest(),
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
