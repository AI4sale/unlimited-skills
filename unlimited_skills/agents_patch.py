from __future__ import annotations

import argparse
import os
import re
import shutil
from datetime import datetime
from pathlib import Path

UNLIMITED_START = "<!-- BEGIN UNLIMITED SKILLS -->"
UNLIMITED_END = "<!-- END UNLIMITED SKILLS -->"
ECC_START = "<!-- BEGIN ECC -->"
ECC_END = "<!-- END ECC -->"

UNLIMITED_BLOCK_RE = re.compile(
    rf"(?s){re.escape(UNLIMITED_START)}.*?{re.escape(UNLIMITED_END)}"
)
ECC_BLOCK_RE = re.compile(
    rf"(?s)\ufeff?\s*{re.escape(ECC_START)}.*?{re.escape(ECC_END)}\s*"
)


def patch_agents_text(text: str, unlimited_block: str) -> str:
    block = unlimited_block.strip() + "\n"
    has_unlimited = bool(UNLIMITED_BLOCK_RE.search(text))
    has_ecc = bool(ECC_BLOCK_RE.search(text))

    if has_unlimited:
        text = UNLIMITED_BLOCK_RE.sub(lambda _match: block.rstrip(), text, count=1)
        text = ECC_BLOCK_RE.sub("\n", text)
    elif has_ecc:
        text = ECC_BLOCK_RE.sub(lambda _match: block.rstrip(), text, count=1)
    elif text.strip():
        text = text.rstrip() + "\n\n" + block.rstrip()
    else:
        text = block.rstrip()

    return text.strip() + "\n"


def _backup_path(path: Path, timestamp: str | None = None) -> Path:
    stamp = timestamp or datetime.now().strftime("%Y%m%d_%H%M%S")
    backup = path.with_name(f"Agents_md_{stamp}.back")
    if not backup.exists():
        return backup
    index = 2
    while True:
        candidate = path.with_name(f"Agents_md_{stamp}_{index}.back")
        if not candidate.exists():
            return candidate
        index += 1


def patch_agents_file(path: Path, unlimited_block: str, *, backup: bool = True) -> Path | None:
    path.parent.mkdir(parents=True, exist_ok=True)
    old_text = path.read_text(encoding="utf-8", errors="replace") if path.is_file() else ""
    new_text = patch_agents_text(old_text, unlimited_block)

    backup_file: Path | None = None
    if backup and path.is_file() and old_text != new_text:
        backup_file = _backup_path(path)
        shutil.copy2(path, backup_file)

    path.write_text(new_text, encoding="utf-8")
    return backup_file


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Patch AGENTS.md with the Unlimited Skills managed block.")
    parser.add_argument("agents_file", type=Path)
    parser.add_argument("--no-backup", action="store_true")
    args = parser.parse_args(argv)

    block = os.environ.get("AGENTS_BLOCK", "")
    if not block.strip():
        raise SystemExit("AGENTS_BLOCK environment variable is required.")

    backup_file = patch_agents_file(args.agents_file, block, backup=not args.no_backup)
    if backup_file:
        print(f"Backed up AGENTS.md: {backup_file}")
    print(f"Patched AGENTS.md: {args.agents_file}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
