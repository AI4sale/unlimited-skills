from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
LABELS_PATH = ROOT / ".github" / "labels.yml"


def load_desired() -> dict[str, dict[str, str]]:
    raw = yaml.safe_load(LABELS_PATH.read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        raise SystemExit(".github/labels.yml must contain a list")
    labels: dict[str, dict[str, str]] = {}
    for item in raw:
        if not isinstance(item, dict) or "name" not in item:
            raise SystemExit("Each label entry must contain name, color, description, and category")
        labels[str(item["name"])] = {
            "color": str(item.get("color", "")),
            "description": str(item.get("description", "")),
            "category": str(item.get("category", "")),
        }
    return labels


def load_existing(offline: bool) -> dict[str, dict[str, str]]:
    if offline:
        return {}
    result = subprocess.run(
        ["gh", "label", "list", "--limit", "500", "--json", "name,color,description"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    raw = json.loads(result.stdout)
    return {
        str(item["name"]): {
            "color": str(item.get("color", "")),
            "description": str(item.get("description", "")),
        }
        for item in raw
    }


def plan_changes(
    desired: dict[str, dict[str, str]], existing: dict[str, dict[str, str]]
) -> list[tuple[str, str, dict[str, str]]]:
    changes: list[tuple[str, str, dict[str, str]]] = []
    for name, target in desired.items():
        current = existing.get(name)
        if current is None:
            changes.append(("create", name, target))
            continue
        if (
            current.get("color", "").lstrip("#").lower() != target["color"].lower()
            or current.get("description", "") != target["description"]
        ):
            changes.append(("update", name, target))
    return changes


def apply_change(action: str, name: str, label: dict[str, str]) -> None:
    if action == "create":
        subprocess.run(
            [
                "gh",
                "label",
                "create",
                name,
                "--color",
                label["color"],
                "--description",
                label["description"],
            ],
            cwd=ROOT,
            check=True,
        )
    elif action == "update":
        subprocess.run(
            [
                "gh",
                "label",
                "edit",
                name,
                "--color",
                label["color"],
                "--description",
                label["description"],
            ],
            cwd=ROOT,
            check=True,
        )


def main() -> int:
    parser = argparse.ArgumentParser(description="Dry-run or apply GitHub label sync.")
    parser.add_argument("--apply", action="store_true", help="Mutate GitHub labels. Default is dry-run.")
    parser.add_argument("--dry-run", action="store_true", help="Print planned changes without mutating labels.")
    parser.add_argument(
        "--offline",
        action="store_true",
        help="Do not call gh; compare desired labels against an empty remote state.",
    )
    args = parser.parse_args()
    if args.apply and args.dry_run:
        raise SystemExit("Choose either --apply or --dry-run, not both")

    desired = load_desired()
    existing = load_existing(args.offline)
    changes = plan_changes(desired, existing)

    mode = "apply" if args.apply else "dry-run"
    print(f"GitHub label sync {mode}: {len(changes)} planned change(s)")
    for action, name, label in changes:
        print(f"- {action} {name} color={label['color']} description={label['description']}")
        if args.apply:
            apply_change(action, name, label)

    if not args.apply:
        print("No GitHub labels were changed. Pass --apply to mutate labels.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
