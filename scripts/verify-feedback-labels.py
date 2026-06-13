from __future__ import annotations

import re
import sys
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import yaml


ROOT = Path(__file__).resolve().parents[1]
LABELS_PATH = ROOT / ".github" / "labels.yml"
ISSUE_TEMPLATE_DIR = ROOT / ".github" / "ISSUE_TEMPLATE"
DOC_PATHS = [
    ROOT / "docs" / "adoption" / "feedback-labels.md",
    ROOT / "docs" / "adoption" / "feedback-triage-workflow.md",
    ROOT / "docs" / "adoption" / "feedback-to-backlog-routing.md",
    ROOT / "docs" / "feedback.md",
]
FEEDBACK_TEMPLATE_FILES = [
    "first-value-feedback.yml",
    "install-friction.yml",
    "skill-not-invoked.yml",
    "mcp-savings-report.yml",
]
ALLOWED_CATEGORIES = {"feedback", "severity", "needs", "backlog", "outcome"}
LABEL_RE = re.compile(r"`([a-z][a-z0-9-]*:[a-z0-9][a-z0-9-]*)`")
COLOR_RE = re.compile(r"^[0-9A-Fa-f]{6}$")


def read_yaml(path: Path) -> object:
    with path.open("r", encoding="utf-8") as handle:
        return yaml.safe_load(handle)


def label_names_from_manifest() -> tuple[dict[str, dict[str, str]], list[str]]:
    raw = read_yaml(LABELS_PATH)
    errors: list[str] = []
    labels: dict[str, dict[str, str]] = {}
    if not isinstance(raw, list):
        return {}, [".github/labels.yml must contain a list of label objects"]

    for index, item in enumerate(raw, start=1):
        if not isinstance(item, dict):
            errors.append(f"label entry {index} is not an object")
            continue
        name = str(item.get("name", "")).strip()
        color = str(item.get("color", "")).strip()
        description = str(item.get("description", "")).strip()
        category = str(item.get("category", "")).strip()
        if not name:
            errors.append(f"label entry {index} is missing name")
            continue
        if name in labels:
            errors.append(f"duplicate label: {name}")
        if not color or not COLOR_RE.match(color):
            errors.append(f"{name}: color must be a six-character hex value")
        if not description:
            errors.append(f"{name}: description is required")
        if category not in ALLOWED_CATEGORIES:
            errors.append(f"{name}: category must be one of {sorted(ALLOWED_CATEGORIES)}")
        labels[name] = {
            "color": color,
            "description": description,
            "category": category,
        }
    return labels, errors


def documented_labels() -> set[str]:
    labels: set[str] = set()
    for path in DOC_PATHS:
        text = path.read_text(encoding="utf-8", errors="replace")
        labels.update(LABEL_RE.findall(text))
    return labels


def template_labels() -> dict[str, set[str]]:
    labels_by_template: dict[str, set[str]] = {}
    for path in sorted(ISSUE_TEMPLATE_DIR.glob("*.yml")):
        raw = read_yaml(path)
        labels: set[str] = set()
        if isinstance(raw, dict):
            raw_labels = raw.get("labels", [])
            if isinstance(raw_labels, str):
                labels.update(part.strip() for part in raw_labels.split(",") if part.strip())
            elif isinstance(raw_labels, list):
                labels.update(str(label).strip() for label in raw_labels if str(label).strip())

            for link in raw.get("contact_links", []) or []:
                if not isinstance(link, dict):
                    continue
                url = str(link.get("url", ""))
                parsed = urlparse(url)
                query_labels = parse_qs(parsed.query).get("labels", [])
                for value in query_labels:
                    labels.update(part.strip() for part in value.split(",") if part.strip())
        if labels:
            labels_by_template[path.name] = labels
    return labels_by_template


def verify() -> list[str]:
    manifest, errors = label_names_from_manifest()
    manifest_names = set(manifest)

    docs_labels = documented_labels()
    missing_from_manifest = sorted(docs_labels - manifest_names)
    if missing_from_manifest:
        errors.append(f"labels documented but missing from .github/labels.yml: {missing_from_manifest}")

    labels_by_template = template_labels()
    template_label_union = set().union(*labels_by_template.values()) if labels_by_template else set()
    missing_template_labels = sorted(template_label_union - manifest_names)
    if missing_template_labels:
        errors.append(f"issue template labels missing from .github/labels.yml: {missing_template_labels}")

    for template_file in FEEDBACK_TEMPLATE_FILES:
        labels = labels_by_template.get(template_file, set())
        if not any(label.startswith("feedback:") for label in labels):
            errors.append(f"{template_file}: missing feedback:* label")
        if not any(label.startswith("severity:") for label in labels):
            errors.append(f"{template_file}: missing severity:* label")
        if not any(label.startswith("needs:") for label in labels):
            errors.append(f"{template_file}: missing needs:* label")

    docs_feedback_labels = {label for label in docs_labels if label.startswith("feedback:")}
    for label in docs_feedback_labels:
        if manifest.get(label, {}).get("category") != "feedback":
            errors.append(f"{label}: documented feedback label must have category feedback")

    return errors


def main() -> int:
    errors = verify()
    if errors:
        print("Feedback label verification failed:")
        for error in errors:
            print(f"- {error}")
        return 1
    print("Feedback label verification passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
