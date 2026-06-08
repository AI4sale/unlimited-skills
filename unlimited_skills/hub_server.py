from __future__ import annotations

import hashlib
import json
import os
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from .cli import DEFAULT_ROOT, read_text, split_frontmatter
from .hub import HUB_FEATURE_FLAGS, HUB_DEFAULT_PORT


DEFAULT_ALLOWLIST_PATH = Path(os.environ.get("UNLIMITED_SKILLS_HUB_ALLOWLIST", Path.home() / ".unlimited-skills" / "hub" / "hub-allowlist.v1.json"))
DEFAULT_HUB_ROOT = Path(os.environ.get("UNLIMITED_SKILLS_ROOT", str(DEFAULT_ROOT))).expanduser()
WORD_RE = re.compile(r"[a-zA-Z0-9][a-zA-Z0-9_.+#/-]*")
ACTIVE_CLIENT_WINDOW_SECONDS = 30 * 24 * 60 * 60


@dataclass(frozen=True)
class HubSkill:
    name: str
    collection: str
    sha256: str
    source: str
    skill_kind: str
    hub_behavior: str
    requires_local_install: bool
    risk_level: str
    body_allowed: bool
    path: str = ""
    description: str = ""


class ClientCapabilities(BaseModel):
    schema_version: int = 1
    client_id: str = ""
    agent: str = "unknown"
    os: str = ""
    arch: str = ""
    python: str = ""
    node: str = ""
    available_tools: list[str] = Field(default_factory=list)
    installed_packages: dict[str, list[str]] = Field(default_factory=dict)
    env_vars_present: list[str] = Field(default_factory=list)


class ClientRegisterRequest(BaseModel):
    schema_version: int = 1
    token: str = ""
    display_name: str = ""
    capabilities: ClientCapabilities | None = None


class SkillSearchRequest(BaseModel):
    schema_version: int = 1
    query: str
    limit: int = Field(default=8, ge=1, le=20)
    include_local_install_plan: bool = True


class ContextBudget(BaseModel):
    max_skills: int = Field(default=2, ge=1, le=10)
    max_chars: int = Field(default=12000, ge=1, le=100000)


class SkillResolveRequest(BaseModel):
    schema_version: int = 1
    query: str
    context_budget: ContextBudget = Field(default_factory=ContextBudget)
    client_capabilities: ClientCapabilities | None = None


class HubState:
    def __init__(self, root: Path, allowlist_path: Path) -> None:
        self.root = root.expanduser()
        self.allowlist_path = allowlist_path.expanduser()
        self.started_at = time.time()
        self.clients: dict[str, dict[str, Any]] = {}
        manifest = load_allowlist_manifest(self.allowlist_path)
        self.source_audit = manifest.get("source_audit", {})
        self.policy = manifest.get("policy", {})
        self.allowlisted = load_hub_skills(manifest)
        self.local_skills = load_local_skill_index(self.root)

    @property
    def active_client_count(self) -> int:
        cutoff = time.time() - ACTIVE_CLIENT_WINDOW_SECONDS
        return sum(1 for item in self.clients.values() if float(item.get("last_seen_at", 0)) >= cutoff)

    def register_client(self, request: ClientRegisterRequest) -> dict[str, Any]:
        if self.active_client_count >= HUB_FEATURE_FLAGS["max_hub_clients"]:
            raise HTTPException(status_code=403, detail={"code": "client_limit_reached", "message": "Registered Local Skill Hub supports up to 100 active client instances."})
        raw = json.dumps(model_payload(request), sort_keys=True)
        client_id = request.capabilities.client_id if request.capabilities and request.capabilities.client_id else "uls_client_" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]
        self.clients[client_id] = {
            "client_id": client_id,
            "display_name": request.display_name,
            "agent": request.capabilities.agent if request.capabilities else "unknown",
            "last_seen_at": time.time(),
        }
        return {"schema_version": 1, "client_id": client_id, "active_client_count": self.active_client_count, "active_client_limit": HUB_FEATURE_FLAGS["max_hub_clients"]}

    def status(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "hub_id": "uls_hub_local",
            "registered": True,
            "plan": "registered-community",
            "active_client_count": self.active_client_count,
            "active_client_limit": HUB_FEATURE_FLAGS["max_hub_clients"],
            "full_catalog_distribution_allowed": False,
            "distribution_mode": "allowlist_only",
            "catalog_audit_verdict": str(self.source_audit.get("verdict") or "YES_WITH_ALLOWLIST"),
            "skills_total": len(self.allowlisted),
            "allowlisted_skills": len([item for item in self.allowlisted.values() if item.body_allowed]),
            "vector_index_present": False,
            "hosted_query_forwarding": False,
            "allowlist_path": str(self.allowlist_path),
        }


def load_allowlist_manifest(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise RuntimeError(f"Local Skill Hub allowlist is required: {path}")
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(data, dict):
        raise RuntimeError("Hub allowlist must be a JSON object.")
    policy = data.get("policy", {})
    if not isinstance(policy, dict) or policy.get("full_catalog_distribution_allowed") is not False:
        raise RuntimeError("Local Skill Hub MVP requires full_catalog_distribution_allowed=false.")
    if policy.get("hub_executes_skills") is not False:
        raise RuntimeError("Local Skill Hub MVP requires hub_executes_skills=false.")
    if policy.get("requires_registration") is not True:
        raise RuntimeError("Local Skill Hub MVP requires registered hub policy.")
    return data


def model_payload(model: BaseModel) -> dict[str, Any]:
    if hasattr(model, "model_dump"):
        return model.model_dump()
    return model.dict()


def skill_kind_for(item: dict[str, Any]) -> str:
    if item.get("requires_local_install_plan"):
        return "tool"
    if (item.get("asset_policy") or {}).get("distribute_assets"):
        return "asset"
    return "pure_text"


def item_key(collection: str, name: str) -> str:
    return f"{collection.lower()}/{name.lower()}"


def load_hub_skills(manifest: dict[str, Any]) -> dict[str, HubSkill]:
    results: dict[str, HubSkill] = {}
    for raw in manifest.get("allowlist", []):
        if not isinstance(raw, dict):
            continue
        category = str(raw.get("primary_category") or "")
        if category not in {"HUB_READY_PURE_TEXT", "HUB_READY_WITH_ASSETS"}:
            continue
        item = HubSkill(
            name=str(raw.get("name") or raw.get("skill_id") or ""),
            collection=str(raw.get("collection") or ""),
            sha256=str(raw.get("sha256") or ""),
            source=str(raw.get("source") or "unknown"),
            skill_kind=skill_kind_for(raw),
            hub_behavior=str(raw.get("hub_behavior") or "distribute_body"),
            requires_local_install=False,
            risk_level=str(raw.get("risk_level") or "none"),
            body_allowed=True,
        )
        if item.name and item.collection and item.sha256:
            results[item_key(item.collection, item.name)] = item
    for raw in manifest.get("local_install_plan_candidates", []):
        if not isinstance(raw, dict):
            continue
        item = HubSkill(
            name=str(raw.get("name") or raw.get("skill_id") or ""),
            collection=str(raw.get("collection") or ""),
            sha256=str(raw.get("sha256") or ""),
            source="registered",
            skill_kind="tool",
            hub_behavior="distribute_body_with_local_install_plan",
            requires_local_install=True,
            risk_level="medium",
            body_allowed=False,
        )
        key = item_key(item.collection, item.name)
        if item.name and item.collection and item.sha256 and key not in results:
            results[key] = item
    return results


def load_local_skill_index(root: Path) -> dict[str, dict[str, str]]:
    records: dict[str, dict[str, str]] = {}
    if not root.exists():
        return records
    for skill_md in root.rglob("SKILL.md"):
        rel_parts = skill_md.relative_to(root).parts
        if "duplicates" in rel_parts:
            continue
        try:
            text = read_text(skill_md)
        except OSError:
            continue
        meta, body = split_frontmatter(text)
        name = meta.get("name") or skill_md.parent.name
        collection = collection_for(root, skill_md)
        records[item_key(collection, name)] = {"path": str(skill_md), "body": text, "description": meta.get("description") or first_body_line(body)}
    return records


def collection_for(root: Path, skill_md: Path) -> str:
    rel = skill_md.relative_to(root)
    if len(rel.parts) > 3 and rel.parts[0] == "registry":
        return rel.parts[1]
    if len(rel.parts) > 2 and rel.parts[0] == "local":
        return "local"
    return rel.parts[0] if rel.parts else "default"


def first_body_line(body: str) -> str:
    for line in body.splitlines():
        clean = line.strip(" #\t")
        if clean:
            return clean[:240]
    return ""


def tokens(value: str) -> set[str]:
    return {item.group(0).lower().strip("-_/") for item in WORD_RE.finditer(value or "") if len(item.group(0)) > 1}


def skill_score(query: str, skill: HubSkill, local: dict[str, str] | None) -> float:
    q = tokens(query)
    if not q:
        return 0.0
    haystack = f"{skill.name} {skill.collection} {local.get('description', '') if local else ''} {local.get('body', '')[:4000] if local else ''}"
    overlap = len(q & tokens(haystack))
    score = float(overlap)
    lowered = query.lower()
    if lowered in skill.name.lower():
        score += 6.0
    if skill.name.lower() in lowered:
        score += 8.0
    return score


def search_skills(state: HubState, query: str, limit: int, *, include_local_install_plan: bool) -> list[dict[str, Any]]:
    rows: list[tuple[float, HubSkill, dict[str, str] | None]] = []
    for skill in state.allowlisted.values():
        if skill.requires_local_install and not include_local_install_plan:
            continue
        local = state.local_skills.get(item_key(skill.collection, skill.name))
        score = skill_score(query, skill, local)
        if score > 0:
            rows.append((score, skill, local))
    rows.sort(key=lambda item: (-item[0], item[1].collection, item[1].name))
    return [skill_metadata(skill, confidence=min(score / 10.0, 1.0), local=local) for score, skill, local in rows[:limit]]


def skill_metadata(skill: HubSkill, *, confidence: float = 0.0, local: dict[str, str] | None = None) -> dict[str, Any]:
    return {
        "name": skill.name,
        "collection": skill.collection,
        "confidence": round(confidence, 4),
        "sha256": skill.sha256,
        "skill_kind": skill.skill_kind,
        "hub_behavior": skill.hub_behavior,
        "requires_local_install": skill.requires_local_install,
        "available_locally": bool(local),
    }


def resolve_skills(state: HubState, request: SkillResolveRequest) -> dict[str, Any]:
    hits = search_skills(state, request.query, request.context_budget.max_skills, include_local_install_plan=True)
    selected: list[dict[str, Any]] = []
    used_chars = 0
    for hit in hits:
        skill = state.allowlisted[item_key(hit["collection"], hit["name"])]
        local = state.local_skills.get(item_key(skill.collection, skill.name))
        body = ""
        warnings: list[str] = []
        missing: list[str] = []
        if skill.requires_local_install:
            warnings.append("Local install plan skills are metadata/resolution only until client capability checks are implemented.")
            missing.append("client_capability_checks")
        elif skill.body_allowed and local:
            body = local["body"][: max(request.context_budget.max_chars - used_chars, 0)]
            used_chars += len(body)
        elif skill.body_allowed:
            warnings.append("Skill is allowlisted but not present in the local hub library.")
        selected.append({**hit, "body": body, "missing_capabilities": missing, "warnings": warnings})
    return {"schema_version": 1, "query": request.query, "selected": selected, "context_budget": {"max_skills": request.context_budget.max_skills, "max_chars": request.context_budget.max_chars, "used_chars": used_chars}}


def get_skill_by_name(state: HubState, name: str) -> dict[str, Any]:
    matches = [skill for skill in state.allowlisted.values() if skill.name.lower() == name.lower()]
    if not matches:
        raise HTTPException(status_code=404, detail={"code": "skill_not_found", "message": "Skill is not allowlisted for Local Skill Hub distribution."})
    skill = sorted(matches, key=lambda item: item.collection)[0]
    local = state.local_skills.get(item_key(skill.collection, skill.name))
    payload = skill_metadata(skill, local=local)
    payload["body"] = local["body"] if local and skill.body_allowed and not skill.requires_local_install else ""
    if skill.requires_local_install:
        payload["warnings"] = ["Local install plan skills are metadata-only until client capability checks are implemented."]
    else:
        payload["warnings"] = [] if local else ["Skill is allowlisted but not present in the local hub library."]
    return {"schema_version": 1, "skill": payload}


def create_app(root: Path | None = None, allowlist_path: Path | None = None) -> FastAPI:
    state = HubState(root or DEFAULT_HUB_ROOT, allowlist_path or DEFAULT_ALLOWLIST_PATH)
    app = FastAPI(title="Unlimited Skills Local Skill Hub", version="0.2.0")
    app.state.hub_state = state

    @app.get("/health")
    def health() -> dict[str, Any]:
        return {"ok": True, "distribution_mode": "allowlist_only", "hosted_query_forwarding": False, "hub_executes_skills": False}

    @app.get("/v1/hub/status")
    def status() -> dict[str, Any]:
        return state.status()

    @app.post("/v1/clients/register")
    def register_client(request: ClientRegisterRequest) -> dict[str, Any]:
        return state.register_client(request)

    @app.post("/v1/skills/search")
    def search(request: SkillSearchRequest) -> dict[str, Any]:
        return {"schema_version": 1, "query": request.query, "results": search_skills(state, request.query, request.limit, include_local_install_plan=request.include_local_install_plan)}

    @app.post("/v1/skills/resolve")
    def resolve(request: SkillResolveRequest) -> dict[str, Any]:
        return resolve_skills(state, request)

    @app.get("/v1/skills/{name}")
    def skill(name: str) -> dict[str, Any]:
        return get_skill_by_name(state, name)

    return app


app: FastAPI | None = None
