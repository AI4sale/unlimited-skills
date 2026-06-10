from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(f"v0.3.6-alpha baseline smoke failed: {message}")


def main() -> int:
    print("Running v0.3.6-alpha catalog browser baseline smoke")
    cli = read(ROOT / "unlimited_skills" / "cli.py")
    docs = "\n".join(
        read(path)
        for path in (
            ROOT / "README.md",
            ROOT / "docs" / "catalog-browser.md",
            ROOT / "docs" / "known-limitations.md",
        )
        if path.exists()
    ).lower()
    for command in ("browse", "search", "filters", "preview", "install"):
        require(
            re.search(rf"catalog_{command}\s*=\s*catalog_sub\.add_parser\(\"{command}\"", cli) is not None,
            f"missing catalog {command} parser",
        )
    for phrase in (
        "catalog browse",
        "catalog search",
        "metadata-only",
        "registration",
        "signed",
    ):
        require(phrase in docs, f"missing catalog browser docs phrase: {phrase}")
    print("v0.3.6-alpha catalog browser baseline smoke passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
