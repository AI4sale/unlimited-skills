#!/usr/bin/env python3
"""Generate the Router Inject v2 routable-skill inventory snapshot.

The output is deliberately small: counts, collection splits, and domain buckets
only. It never emits skill bodies, local absolute paths, prompts, secrets, or
tokens.
"""

from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from unlimited_skills.frontmatter import split_frontmatter


REPO_ROOT = Path(__file__).resolve().parents[1]
DOMAIN_MAP = REPO_ROOT / "docs" / "router-inject-domain-map.json"
SNAPSHOT_JSON = REPO_ROOT / "docs" / "router-inventory-snapshot.json"
SNAPSHOT_MD = REPO_ROOT / "docs" / "router-inventory-snapshot.md"
AGENTS_MD = REPO_ROOT / "AGENTS.md"
WORD_RE = re.compile(r"[a-z0-9][a-z0-9_+.#/-]*")
SNAPSHOT_TOLERANCE = 0

IGNORED_PARTS = {
    ".chroma-skills",
    ".git",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    "__pycache__",
    "node_modules",
}


@dataclass(frozen=True)
class RoutableSkill:
    name: str
    description: str
    collection: str
    rel_parts: tuple[str, ...]


def _skill_identity(name: str) -> str:
    return re.sub(r"[^a-z0-9._-]+", "-", str(name or "").strip().lower()).strip("-")


def _collection_for(rel_parts: tuple[str, ...]) -> str:
    if len(rel_parts) >= 3 and rel_parts[0] == "packs":
        return rel_parts[1]
    if len(rel_parts) >= 2 and rel_parts[0] in {"skills", "plugin"}:
        return "local"
    return rel_parts[0] if rel_parts else "local"


def _include_skill(rel_parts: tuple[str, ...]) -> bool:
    if any(part in IGNORED_PARTS for part in rel_parts):
        return False
    if rel_parts and rel_parts[0] == "examples":
        return False
    return bool(rel_parts and rel_parts[-1] == "SKILL.md" and rel_parts[0] in {"packs", "skills", "plugin"})


def _first_body_line(body: str) -> str:
    for line in body.splitlines():
        stripped = line.strip(" #\t")
        if stripped:
            return stripped[:240]
    return ""


def iter_routable_skills(root: Path = REPO_ROOT) -> Iterable[RoutableSkill]:
    candidates: list[tuple[tuple[int, str], str, RoutableSkill]] = []
    for skill_file in sorted(root.rglob("SKILL.md")):
        rel = skill_file.relative_to(root)
        rel_parts = rel.parts
        if not _include_skill(rel_parts):
            continue
        text = skill_file.read_text(encoding="utf-8", errors="replace")
        meta, body = split_frontmatter(text, lower_keys=True)
        name = meta.get("name") or skill_file.parent.name
        description = meta.get("description") or _first_body_line(body)
        collection = _collection_for(rel_parts)
        priority = {"ecc": 10, "superpowers": 20, "local": 30}.get(collection, 50)
        skill = RoutableSkill(name=name, description=description, collection=collection, rel_parts=rel_parts)
        candidates.append(((priority, "/".join(rel_parts).lower()), _skill_identity(name), skill))

    seen: set[str] = set()
    for _priority, identity, skill in sorted(candidates, key=lambda item: item[0]):
        if identity in seen:
            continue
        seen.add(identity)
        yield skill


def _tokens_for(skill: RoutableSkill) -> set[str]:
    text = " ".join([skill.name, skill.description, " ".join(skill.rel_parts)])
    tokens: set[str] = set()
    for match in WORD_RE.finditer(text.lower()):
        raw = match.group(0).strip("-_/")
        if len(raw) > 1:
            tokens.add(raw)
        for part in re.split(r"[-_/]+", raw):
            if len(part) > 1:
                tokens.add(part)
    return tokens


def load_domain_map(path: Path = DOMAIN_MAP) -> list[dict[str, object]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    domains = payload.get("domains")
    if not isinstance(domains, list):
        raise ValueError(f"{path} must contain a domains list")
    names = [str(item.get("domain") or "") for item in domains if isinstance(item, dict)]
    if "other/uncategorized" not in names:
        raise ValueError("domain map must include other/uncategorized")
    return domains


def build_snapshot(root: Path = REPO_ROOT, domain_map: Path = DOMAIN_MAP) -> dict[str, object]:
    skills = list(iter_routable_skills(root))
    domains = load_domain_map(domain_map)
    domain_counts = {str(item["domain"]): 0 for item in domains}
    collection_counts: dict[str, int] = {}

    for skill in skills:
        collection_counts[skill.collection] = collection_counts.get(skill.collection, 0) + 1
        skill_tokens = _tokens_for(skill)
        matched = False
        for item in domains:
            domain = str(item["domain"])
            if domain == "other/uncategorized":
                continue
            tokens = {str(token).lower() for token in item.get("tokens", []) if str(token).strip()}
            if skill_tokens & tokens:
                domain_counts[domain] += 1
                matched = True
                break
        if not matched:
            domain_counts["other/uncategorized"] += 1

    domain_rows = [
        {
            "domain": str(item["domain"]),
            "routable_skills": domain_counts[str(item["domain"])],
            "availability": _availability(domain_counts[str(item["domain"])]),
        }
        for item in domains
    ]
    return {
        "schema_version": 1,
        "generated_by": "scripts/generate-router-inventory.py",
        "count_basis": "repo SKILL.md inventory; bundled packs plus router/plugin skills; examples excluded; deduplicated by normalized skill name",
        "drift_tolerance": SNAPSHOT_TOLERANCE,
        "total_routable_skills": len(skills),
        "collections": dict(sorted(collection_counts.items())),
        "domains": domain_rows,
        "privacy": {
            "contains_skill_bodies": False,
            "contains_local_absolute_paths": False,
            "contains_prompts_or_secrets": False,
        },
    }


def _availability(count: int) -> str:
    if count <= 0:
        return "empty"
    if count < 5:
        return "sparse"
    if count < 20:
        return "present"
    return "broad"


def render_markdown(snapshot: dict[str, object]) -> str:
    collections = snapshot["collections"]
    domains = snapshot["domains"]
    if not isinstance(collections, dict) or not isinstance(domains, list):
        raise TypeError("invalid snapshot shape")
    lines = [
        "# Router Inject v2 Inventory Snapshot",
        "",
        f"Generated by: `{snapshot['generated_by']}`",
        f"Count basis: {snapshot['count_basis']}",
        f"Drift tolerance: `{snapshot['drift_tolerance']}`",
        "",
        f"Total routable skills: **{snapshot['total_routable_skills']}**",
        "",
        "| Collection | Routable skills |",
        "| --- | ---: |",
    ]
    for name, count in collections.items():
        lines.append(f"| {name} | {count} |")
    lines.extend(["", "| Domain | Routable skills | Availability |", "| --- | ---: | --- |"])
    for row in domains:
        if not isinstance(row, dict):
            continue
        lines.append(f"| {row['domain']} | {row['routable_skills']} | {row['availability']} |")
    lines.extend(
        [
            "",
            "Privacy: this snapshot contains counts and coarse domain buckets only; it does not contain skill bodies, local absolute paths, prompts, secrets, tokens, or customer data.",
            "",
        ]
    )
    return "\n".join(lines)


def render_agents_inventory(snapshot: dict[str, object]) -> str:
    collections = snapshot["collections"]
    domains = snapshot["domains"]
    if not isinstance(collections, dict) or not isinstance(domains, list):
        raise TypeError("invalid snapshot shape")
    lines = [
        "<!-- BEGIN ROUTER INVENTORY SNAPSHOT -->",
        f"- Generated routable skills: `{snapshot['total_routable_skills']}` (basis: repo SKILL.md inventory; examples excluded; deduped by skill name).",
        f"- Drift tolerance: `{snapshot['drift_tolerance']}`; regenerate with `python scripts/generate-router-inventory.py --write`.",
        "- Collections: " + ", ".join(f"`{name}` {count}" for name, count in collections.items()) + ".",
        "",
        "| Domain | Routable skills | Availability |",
        "| --- | ---: | --- |",
    ]
    for row in domains:
        if not isinstance(row, dict):
            continue
        lines.append(f"| {row['domain']} | {row['routable_skills']} | {row['availability']} |")
    lines.append("<!-- END ROUTER INVENTORY SNAPSHOT -->")
    return "\n".join(lines)


def check_agents_snapshot(snapshot: dict[str, object], agents_path: Path = AGENTS_MD) -> list[str]:
    text = agents_path.read_text(encoding="utf-8")
    expected = render_agents_inventory(snapshot)
    errors: list[str] = []
    if expected not in text:
        errors.append("AGENTS.md Router Inventory Snapshot does not match generated output")
    for forbidden in [str(REPO_ROOT), "SKILL body", "customer private data"]:
        if forbidden and forbidden in expected:
            errors.append(f"generated inventory leaked forbidden text: {forbidden}")
    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="Print JSON snapshot to stdout.")
    parser.add_argument("--markdown", action="store_true", help="Print Markdown snapshot to stdout.")
    parser.add_argument("--agents-block", action="store_true", help="Print the AGENTS.md inventory block.")
    parser.add_argument("--write", action="store_true", help="Write docs/router-inventory-snapshot.{json,md}.")
    parser.add_argument("--check", action="store_true", help="Check generated snapshots and AGENTS.md are current.")
    args = parser.parse_args(argv)

    snapshot = build_snapshot()
    json_text = json.dumps(snapshot, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    md_text = render_markdown(snapshot)

    if args.write:
        SNAPSHOT_JSON.write_text(json_text, encoding="utf-8")
        SNAPSHOT_MD.write_text(md_text, encoding="utf-8")

    if args.check:
        errors = []
        if SNAPSHOT_JSON.read_text(encoding="utf-8") != json_text:
            errors.append(f"{SNAPSHOT_JSON.relative_to(REPO_ROOT)} is stale")
        if SNAPSHOT_MD.read_text(encoding="utf-8") != md_text:
            errors.append(f"{SNAPSHOT_MD.relative_to(REPO_ROOT)} is stale")
        errors.extend(check_agents_snapshot(snapshot))
        if errors:
            raise SystemExit("\n".join(errors))

    if args.json:
        print(json_text, end="")
    elif args.markdown:
        print(md_text, end="")
    elif args.agents_block:
        print(render_agents_inventory(snapshot))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
