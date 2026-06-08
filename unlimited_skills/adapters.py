from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
import tempfile
import time
from dataclasses import asdict, dataclass
from pathlib import Path


ADAPTER_VERSION = "odysseus-action-schema-v1"
AGENT_ADAPTER_VERSION = "action-schema-agent-v1"
SKILL_FILE = "SKILL.md"
SKILL_PACKS = {
    "ecc": {
        "repo": "https://github.com/affaan-m/ECC.git",
        "homepage": "https://github.com/affaan-m/ECC",
        "collection": "ecc",
        "description": "Everything Claude Code skill pack adapted for Unlimited Skills.",
    },
    "superpowers": {
        "repo": "https://github.com/obra/superpowers.git",
        "homepage": "https://github.com/obra/superpowers",
        "collection": "superpowers",
        "description": "Superpowers agentic skills framework adapted for Unlimited Skills.",
    },
}
IGNORED_PARTS = {".git", ".venv", ".chroma-skills", ".learning", "duplicates", "node_modules", "__pycache__"}
PACK_REF_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/@+-]{0,200}$")
DEFAULT_UNSPECIFIED = "Not specified by the source skill."
ACTION_SECTIONS = [
    "when_to_use",
    "when_not_to_use",
    "required_context",
    "procedure",
    "tools",
    "expected_output",
    "known_traps",
    "examples_of_successful_execution",
    "regression_tests",
]
SECTION_HEADINGS = {
    "when_to_use": "When to Use",
    "when_not_to_use": "When Not to Use",
    "required_context": "Required Context",
    "procedure": "Procedure",
    "tools": "Tools",
    "expected_output": "Expected Output",
    "known_traps": "Known Traps",
    "examples_of_successful_execution": "Examples of Successful Execution",
    "regression_tests": "Regression Tests",
}
HEADING_ALIASES = {
    "when to use": "when_to_use",
    "when to activate": "when_to_use",
    "activation": "when_to_use",
    "use when": "when_to_use",
    "triggers": "when_to_use",
    "when not to use": "when_not_to_use",
    "do not use": "when_not_to_use",
    "not appropriate": "when_not_to_use",
    "anti-patterns": "when_not_to_use",
    "required context": "required_context",
    "context": "required_context",
    "prerequisites": "required_context",
    "requirements": "required_context",
    "inputs": "required_context",
    "before you start": "required_context",
    "procedure": "procedure",
    "workflow": "procedure",
    "steps": "procedure",
    "process": "procedure",
    "instructions": "procedure",
    "implementation": "procedure",
    "tools": "tools",
    "tooling": "tools",
    "required tools": "tools",
    "expected output": "expected_output",
    "outputs": "expected_output",
    "deliverables": "expected_output",
    "success criteria": "expected_output",
    "known traps": "known_traps",
    "pitfalls": "known_traps",
    "warnings": "known_traps",
    "common mistakes": "known_traps",
    "failure modes": "known_traps",
    "examples": "examples_of_successful_execution",
    "example": "examples_of_successful_execution",
    "successful execution": "examples_of_successful_execution",
    "examples of successful execution": "examples_of_successful_execution",
    "regression tests": "regression_tests",
    "tests": "regression_tests",
    "verification": "regression_tests",
    "validation": "regression_tests",
    "checklist": "regression_tests",
}


@dataclass
class AdaptedSkill:
    name: str
    path: str
    changed: bool
    description: str
    original_sha256: str


@dataclass
class AgentAdaptedSkill:
    name: str
    path: str
    changed: bool
    source_sha256: str


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace").lstrip("\ufeff")


def library_collection_for(root: Path, skill_file: Path) -> str:
    rel = skill_file.relative_to(root)
    if len(rel.parts) > 3 and rel.parts[0] == "registry":
        return rel.parts[1]
    if len(rel.parts) > 2 and rel.parts[0] == "local":
        return "local"
    return rel.parts[0] if len(rel.parts) > 1 else "default"


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()


def slugify(text: str, fallback: str = "skill") -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", str(text or "").lower()).strip("-")
    return (slug or fallback)[:80]


def split_frontmatter(text: str) -> tuple[dict[str, str], str]:
    text = text.lstrip("\ufeff")
    if not text.startswith("---"):
        return {}, text
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}, text
    end = None
    for idx in range(1, len(lines)):
        if lines[idx].strip() == "---":
            end = idx
            break
    if end is None:
        return {}, text
    meta = {}
    for line in lines[1:end]:
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key:
            meta[key] = value
    return meta, "\n".join(lines[end + 1 :]).lstrip("\n")


def extract_section(body: str, heading: str) -> str:
    pattern = re.compile(rf"^##\s+{re.escape(heading)}\s*$", re.IGNORECASE | re.MULTILINE)
    match = pattern.search(body)
    if not match:
        return ""
    start = match.end()
    next_match = re.search(r"^##\s+", body[start:], re.MULTILINE)
    end = start + next_match.start() if next_match else len(body)
    return body[start:end].strip()


def extract_terminal_section(body: str, heading: str) -> str:
    pattern = re.compile(rf"^##\s+{re.escape(heading)}\s*$", re.IGNORECASE | re.MULTILINE)
    matches = list(pattern.finditer(body))
    if not matches:
        return ""
    return body[matches[-1].end() :].strip()


def scalar(value: str) -> str:
    value = str(value or "").replace("\r", " ").replace("\n", " ").strip()
    if not value:
        return ""
    if any(ch in value for ch in [":", "|", '"', "'", "[", "]", ",", "#"]):
        return json.dumps(value, ensure_ascii=False)
    return value


def emit_frontmatter(meta: dict[str, str]) -> str:
    preferred = [
        "name",
        "description",
        "version",
        "category",
        "tags",
        "status",
        "confidence",
        "source",
        "source_pack",
        "source_repo",
        "source_path",
        "source_sha256",
        "unlimited_skills_adapter",
        "created",
    ]
    keys = [key for key in preferred if key in meta] + sorted(key for key in meta if key not in preferred)
    lines = ["---"]
    for key in keys:
        value = scalar(meta.get(key, ""))
        if value:
            lines.append(f"{key}: {value}")
    lines.append("---")
    return "\n".join(lines)


def normalize_heading(text: str) -> str:
    text = re.sub(r"\s+", " ", text.strip().lower())
    text = re.sub(r"^[0-9]+[.)]\s*", "", text)
    return text.rstrip(":")


def split_markdown_sections(body: str) -> tuple[dict[str, list[str]], str]:
    mapped = {key: [] for key in ACTION_SECTIONS}
    extra_blocks: list[str] = []
    current_key: str | None = None
    current_heading: str | None = None
    current_lines: list[str] = []

    def flush() -> None:
        nonlocal current_key, current_heading, current_lines
        text = "\n".join(current_lines).strip()
        if not text:
            current_key = None
            current_heading = None
            current_lines = []
            return
        if current_key:
            mapped[current_key].append(text)
        elif current_heading:
            extra_blocks.append(f"## {current_heading}\n\n{text}")
        else:
            extra_blocks.append(text)
        current_key = None
        current_heading = None
        current_lines = []

    for line in body.splitlines():
        match = re.match(r"^#{1,4}\s+(.*?)\s*$", line)
        if match:
            flush()
            heading = match.group(1).strip()
            current_heading = heading
            current_key = HEADING_ALIASES.get(normalize_heading(heading))
            continue
        current_lines.append(line)
    flush()
    return mapped, "\n\n".join(block for block in extra_blocks if block.strip()).strip()


def first_body_line(body: str) -> str:
    for line in body.splitlines():
        stripped = line.strip(" #\t-*0123456789.)")
        if stripped:
            return stripped[:220]
    return ""


def short_description(meta: dict[str, str], body: str, name: str) -> str:
    description = meta.get("description") or meta.get("title") or first_body_line(body)
    return (description or f"Operational skill for {name}.").strip()[:500]


def fallback_when_to_use(description: str) -> str:
    return description or DEFAULT_UNSPECIFIED


def fallback_procedure(body_extra: str) -> str:
    if body_extra:
        return "1. Read the preserved source skill body below.\n2. Apply only the parts relevant to the current task.\n3. Verify the result using the regression tests or project-specific checks."
    return DEFAULT_UNSPECIFIED


def section_text(mapped: dict[str, list[str]], key: str, fallback: str = DEFAULT_UNSPECIFIED) -> str:
    text = "\n\n".join(part for part in mapped.get(key, []) if part.strip()).strip()
    return text or fallback


def emit_action_body(mapped: dict[str, list[str]], body_extra: str, description: str) -> str:
    values = {
        "when_to_use": section_text(mapped, "when_to_use", fallback_when_to_use(description)),
        "when_not_to_use": section_text(mapped, "when_not_to_use"),
        "required_context": section_text(mapped, "required_context"),
        "procedure": section_text(mapped, "procedure", fallback_procedure(body_extra)),
        "tools": section_text(mapped, "tools"),
        "expected_output": section_text(mapped, "expected_output"),
        "known_traps": section_text(mapped, "known_traps"),
        "examples_of_successful_execution": section_text(mapped, "examples_of_successful_execution"),
        "regression_tests": section_text(mapped, "regression_tests"),
    }
    parts = [f"## {SECTION_HEADINGS[key]}\n\n{values[key]}" for key in ACTION_SECTIONS]
    if body_extra:
        parts.append(f"## Original Skill Body\n\n{body_extra}")
    return "\n\n".join(parts).strip() + "\n"


def emit_agent_action_body(data: dict, original_body: str) -> str:
    values = {}
    for key in ACTION_SECTIONS:
        value = data.get(key)
        if isinstance(value, list):
            value = "\n".join(f"{idx + 1}. {item}" for idx, item in enumerate(value))
        value = str(value or "").strip() or DEFAULT_UNSPECIFIED
        values[key] = value
    parts = [f"## {SECTION_HEADINGS[key]}\n\n{values[key]}" for key in ACTION_SECTIONS]
    if original_body.strip():
        parts.append(f"## Original Skill Body\n\n{original_body.strip()}")
    return "\n\n".join(parts).strip() + "\n"


def extract_tags(name: str, description: str, source_pack: str = "") -> str:
    words = []
    for token in re.findall(r"[a-zA-Z0-9][a-zA-Z0-9_+.#-]*", f"{name} {description} {source_pack}"):
        token = token.lower().strip("-")
        if len(token) >= 3 and token not in {"the", "and", "for", "with", "when", "use", "skill"}:
            words.append(token)
    unique = []
    for word in words:
        if word not in unique:
            unique.append(word)
    return "[" + ", ".join(unique[:8]) + "]" if unique else ""


def adapt_skill_file(
    path: Path,
    source_pack: str = "",
    source_repo: str = "",
    source_path: str = "",
    force: bool = False,
    dry_run: bool = False,
) -> AdaptedSkill:
    original = read_text(path)
    original_sha = sha256_text(original)
    meta, body = split_frontmatter(original)
    name = slugify(meta.get("name") or path.parent.name)
    description = short_description(meta, body, name)
    current_source_sha = meta.get("source_sha256", "")
    already_adapted = meta.get("unlimited_skills_adapter") == ADAPTER_VERSION and current_source_sha == original_sha
    mapped, body_extra = split_markdown_sections(body)

    new_meta = {
        "name": name,
        "description": description,
        "version": meta.get("version", "1.0.0"),
        "category": meta.get("category") or source_pack or "general",
        "tags": meta.get("tags") or extract_tags(name, description, source_pack),
        "status": meta.get("status", "published"),
        "confidence": meta.get("confidence", "0.8"),
        "source": meta.get("source", "imported" if source_pack else "local"),
        "source_sha256": original_sha,
        "unlimited_skills_adapter": ADAPTER_VERSION,
        "created": meta.get("created") or time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    if source_pack:
        new_meta["source_pack"] = source_pack
    if source_repo:
        new_meta["source_repo"] = source_repo
    if source_path:
        new_meta["source_path"] = source_path

    new_text = emit_frontmatter(new_meta) + "\n\n" + emit_action_body(mapped, body_extra, description)
    changed = force or not already_adapted or original != new_text
    if changed and not dry_run:
        path.write_text(new_text, encoding="utf-8")
    return AdaptedSkill(name=name, path=str(path), changed=changed, description=description, original_sha256=original_sha)


def agent_source_text(text: str, body: str) -> str:
    original = extract_terminal_section(body, "Original Skill Body")
    return original or text


def adaptation_task(path: Path, root: Path, source_pack: str = "", source_repo: str = "") -> dict:
    text = read_text(path)
    meta, body = split_frontmatter(text)
    source_text = agent_source_text(text, body)
    source_sha = meta.get("source_sha256") or sha256_text(source_text)
    name = slugify(meta.get("name") or path.parent.name)
    description = short_description(meta, source_text, name)
    schema = {
        "name": "kebab-case skill name",
        "description": "short index summary, not keyword stuffing",
        "category": "short category",
        "tags": ["3-8 retrieval tags"],
        "when_to_use": "activation conditions",
        "when_not_to_use": "negative activation conditions",
        "required_context": "inputs/context the agent must inspect before acting",
        "procedure": ["ordered operational steps"],
        "tools": ["tools or capabilities required; say not specified if absent"],
        "expected_output": "what the agent should produce",
        "known_traps": ["failure modes, ambiguity, safety issues"],
        "examples_of_successful_execution": ["source-grounded examples or not specified"],
        "regression_tests": ["checks that prove the skill worked"],
    }
    return {
        "task": "Adapt exactly one source skill into an action-memory skill. Skill memory is not RAG; it must teach an agent how to act.",
        "rules": [
            "Return or write JSON matching required_json_schema.",
            "Do not invent unsupported facts. Use 'Not specified by the source skill.' when the source lacks a field.",
            "Keep description short; put operational routing in when_to_use and when_not_to_use.",
            "Procedure must be concrete, ordered, and executable by an agent.",
            "Regression tests must be checks the agent can run or inspect.",
            "Preserve provenance. Do not remove source_repo, source_pack, source_path, or source_sha256.",
        ],
        "source_path": str(path),
        "library_root": str(root),
        "source_sha256": source_sha,
        "source_pack": source_pack,
        "source_repo": source_repo,
        "current_name": name,
        "current_description": description,
        "required_json_schema": schema,
        "source_skill": source_text[:30000],
    }


def normalize_agent_json(data: dict, fallback_name: str, fallback_description: str) -> dict:
    out = dict(data)
    out["name"] = slugify(out.get("name") or fallback_name)
    out["description"] = str(out.get("description") or fallback_description).strip()[:500]
    out["category"] = slugify(out.get("category") or "general")
    tags = out.get("tags") if isinstance(out.get("tags"), list) else []
    out["tags"] = [slugify(tag) for tag in tags if str(tag).strip()][:8]
    for key in ACTION_SECTIONS:
        value = out.get(key)
        if isinstance(value, list):
            cleaned = [str(item).strip() for item in value if str(item).strip()]
            out[key] = cleaned or [DEFAULT_UNSPECIFIED]
        else:
            out[key] = str(value or DEFAULT_UNSPECIFIED).strip()
    return out


def apply_agent_adaptation(
    path: Path,
    root: Path,
    data: dict,
    source_pack: str = "",
    source_repo: str = "",
    dry_run: bool = False,
) -> AgentAdaptedSkill:
    text = read_text(path)
    meta, body = split_frontmatter(text)
    source_text = agent_source_text(text, body)
    source_sha = meta.get("source_sha256") or sha256_text(source_text)
    name = slugify(meta.get("name") or path.parent.name)
    description = short_description(meta, source_text, name)
    normalized = normalize_agent_json(data, name, description)
    new_meta = {
        "name": normalized["name"],
        "description": normalized["description"],
        "version": meta.get("version", "1.0.0"),
        "category": normalized["category"],
        "tags": "[" + ", ".join(normalized["tags"]) + "]" if normalized["tags"] else "",
        "status": meta.get("status", "published"),
        "confidence": meta.get("confidence", "0.85"),
        "source": meta.get("source", "imported" if source_pack else "local"),
        "source_pack": source_pack or meta.get("source_pack", ""),
        "source_repo": source_repo or meta.get("source_repo", ""),
        "source_path": meta.get("source_path", str(path)),
        "source_sha256": source_sha,
        "unlimited_skills_adapter": ADAPTER_VERSION,
        "unlimited_skills_agent_adapter": AGENT_ADAPTER_VERSION,
        "created": meta.get("created") or time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    new_text = emit_frontmatter(new_meta) + "\n\n" + emit_agent_action_body(normalized, source_text)
    changed = text != new_text
    if changed and not dry_run:
        path.write_text(new_text, encoding="utf-8")
    return AgentAdaptedSkill(name=normalized["name"], path=str(path), changed=changed, source_sha256=source_sha)


def next_skill_for_agent(root: Path, collection: str | None = None) -> Path | None:
    for skill_file in sorted(root.rglob(SKILL_FILE), key=lambda item: str(item).lower()):
        rel_parts = skill_file.relative_to(root).parts
        if any(part in IGNORED_PARTS for part in rel_parts):
            continue
        if collection and library_collection_for(root, skill_file) != collection:
            continue
        meta, _body = split_frontmatter(read_text(skill_file))
        if meta.get("unlimited_skills_agent_adapter") != AGENT_ADAPTER_VERSION:
            return skill_file
    return None


def adapt_library(root: Path, collection: str | None = None, source_pack: str = "", source_repo: str = "", force: bool = False, dry_run: bool = False) -> list[AdaptedSkill]:
    results = []
    for skill_file in root.rglob(SKILL_FILE):
        rel_parts = skill_file.relative_to(root).parts
        if any(part in IGNORED_PARTS for part in rel_parts):
            continue
        if collection and library_collection_for(root, skill_file) != collection:
            continue
        results.append(
            adapt_skill_file(
                skill_file,
                source_pack=source_pack or collection or "",
                source_repo=source_repo,
                source_path=str(skill_file.relative_to(root)),
                force=force,
                dry_run=dry_run,
            )
        )
    return results


def copy_skill_dirs(source_root: Path, target_root: Path, collection: str, source_pack: str, source_repo: str) -> list[AdaptedSkill]:
    target_skills = target_root / "registry" / collection / "skills"
    target_skills.mkdir(parents=True, exist_ok=True)
    copied = []
    candidates = sorted(source_root.rglob(SKILL_FILE), key=lambda item: (len(item.parts), str(item).lower()))
    seen_names = set()
    for skill_file in candidates:
        if any(part in IGNORED_PARTS for part in skill_file.parts):
            continue
        skill_dir = skill_file.parent
        name = slugify(skill_dir.name)
        if name in seen_names:
            continue
        seen_names.add(name)
        destination = target_skills / name
        if destination.exists():
            shutil.rmtree(destination)
        shutil.copytree(skill_dir, destination, ignore=shutil.ignore_patterns(*IGNORED_PARTS))
        copied.append(
            adapt_skill_file(
                destination / SKILL_FILE,
                source_pack=source_pack,
                source_repo=source_repo,
                source_path=str(skill_file.relative_to(source_root)),
            )
        )
    manifest_dir = target_root / "manifests"
    manifest_dir.mkdir(parents=True, exist_ok=True)
    manifest = {
        "collection": collection,
        "source_pack": source_pack,
        "source_repo": source_repo,
        "imported_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "adapter": ADAPTER_VERSION,
        "count": len(copied),
        "items": [asdict(item) for item in copied],
    }
    (manifest_dir / f"{collection}-pack-import-{int(time.time())}.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return copied


def install_pack(root: Path, pack: str, ref: str = "", keep_clone: Path | None = None) -> list[AdaptedSkill]:
    if pack not in SKILL_PACKS:
        known = ", ".join(sorted(SKILL_PACKS))
        raise RuntimeError(f"Unknown skill pack: {pack}. Known packs: {known}")
    spec = SKILL_PACKS[pack]
    safe_ref = validate_pack_ref(ref) if ref else ""
    with tempfile.TemporaryDirectory(prefix=f"unlimited-skills-{pack}-") as tmp:
        clone_dir = Path(tmp) / pack
        subprocess.run(["git", "clone", "--depth", "1", spec["repo"], str(clone_dir)], check=True)
        if safe_ref:
            subprocess.run(["git", "-C", str(clone_dir), "fetch", "--depth", "1", "origin", safe_ref], check=True)
            subprocess.run(["git", "-C", str(clone_dir), "checkout", "FETCH_HEAD"], check=True)
        results = copy_skill_dirs(clone_dir, root, spec["collection"], pack, spec["homepage"])
        if keep_clone:
            if keep_clone.exists():
                shutil.rmtree(keep_clone)
            shutil.copytree(clone_dir, keep_clone)
        return results


def validate_pack_ref(ref: str) -> str:
    value = ref.strip()
    if not value or not PACK_REF_RE.match(value):
        raise RuntimeError(f"Unsafe git ref: {ref}")
    if ".." in value or value.endswith(".lock"):
        raise RuntimeError(f"Unsafe git ref: {ref}")
    return value
