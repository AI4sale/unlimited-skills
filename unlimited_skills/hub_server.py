from __future__ import annotations

import hashlib
import json
import os
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from . import __version__
from .cli import DEFAULT_ROOT, read_text, split_frontmatter
from .hub import HUB_FEATURE_FLAGS, HUB_DEFAULT_PORT, verify_hub_token
from .hub_allowlist import cached_allowlist_path, hub_clients_path, hub_logs_dir, validate_allowlist
from .registration import redact_sensitive_text, unlimited_skills_home, write_private_json


DEFAULT_ALLOWLIST_PATH = Path(os.environ.get("UNLIMITED_SKILLS_HUB_ALLOWLIST", cached_allowlist_path()))
DEFAULT_HUB_ROOT = Path(os.environ.get("UNLIMITED_SKILLS_ROOT", str(DEFAULT_ROOT))).expanduser()
WORD_RE = re.compile(r"[a-zA-Z0-9][a-zA-Z0-9_.+#/-]*")
ACTIVE_CLIENT_WINDOW_SECONDS = 30 * 24 * 60 * 60


def now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


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
    runtime_manifest: dict[str, Any]
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


class SkillEventRequest(BaseModel):
    schema_version: int = 1
    skill_name: str = ""
    query: str = ""
    task: str = ""
    verdict: str = ""
    notes: str = ""


class HubState:
    def __init__(self, root: Path, allowlist_path: Path, home: Path | None = None) -> None:
        self.root = root.expanduser()
        self.allowlist_path = allowlist_path.expanduser()
        self.home = home or unlimited_skills_home()
        self.started_at = time.time()
        self.clients_path = hub_clients_path(self.home)
        self.audit_path = hub_logs_dir(self.home) / "audit.jsonl"
        self.clients: dict[str, dict[str, Any]] = self.load_clients()
        self.request_count = 0
        self.events_by_type: dict[str, int] = {}
        manifest = load_allowlist_manifest(self.allowlist_path)
        self.source_audit = manifest.get("source_audit", {})
        self.policy = manifest.get("policy", {})
        self.allowlisted = load_hub_skills(manifest)
        self.local_skills = load_local_skill_index(self.root)

    @property
    def active_client_count(self) -> int:
        cutoff = time.time() - ACTIVE_CLIENT_WINDOW_SECONDS
        return sum(1 for item in self.clients.values() if not bool(item.get("deactivated")) and float(item.get("last_seen_at", 0)) >= cutoff)

    def load_clients(self) -> dict[str, dict[str, Any]]:
        if not self.clients_path.is_file():
            write_private_json(self.clients_path, {"schema_version": 1, "clients": []})
            return {}
        try:
            payload = json.loads(self.clients_path.read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError):
            payload = {}
        clients = payload.get("clients", []) if isinstance(payload, dict) else []
        records: dict[str, dict[str, Any]] = {}
        if isinstance(clients, list):
            for item in clients:
                if not isinstance(item, dict):
                    continue
                client_id = str(item.get("client_id") or "")
                if client_id:
                    records[client_id] = item
        return records

    def save_clients(self) -> None:
        write_private_json(
            self.clients_path,
            {
                "schema_version": 1,
                "updated_at": now_iso(),
                "active_client_window_seconds": ACTIVE_CLIENT_WINDOW_SECONDS,
                "active_client_limit": HUB_FEATURE_FLAGS["max_hub_clients"],
                "clients": sorted(self.clients.values(), key=lambda item: str(item.get("client_id") or "")),
            },
        )

    def audit(self, event: str, **fields: Any) -> None:
        self.request_count += 1
        self.events_by_type[event] = self.events_by_type.get(event, 0) + 1
        payload = {
            "schema_version": 1,
            "ts": now_iso(),
            "event": event,
            **{key: redact_sensitive_text(value) for key, value in fields.items() if value not in (None, "")},
        }
        self.audit_path.parent.mkdir(parents=True, exist_ok=True)
        with self.audit_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n")

    def _client_from_request(self, request: ClientRegisterRequest) -> tuple[str, dict[str, Any]]:
        raw = json.dumps(model_payload(request), sort_keys=True)
        client_id = request.capabilities.client_id if request.capabilities and request.capabilities.client_id else "uls_client_" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]
        now = time.time()
        previous = self.clients.get(client_id, {})
        record = {
            "client_id": client_id,
            "display_name": request.display_name,
            "agent": request.capabilities.agent if request.capabilities else "unknown",
            "os": request.capabilities.os if request.capabilities else "",
            "arch": request.capabilities.arch if request.capabilities else "",
            "first_seen_at": previous.get("first_seen_at") or now,
            "last_seen_at": now,
            "request_count": int(previous.get("request_count") or 0) + 1,
            "deactivated": False,
            "capabilities": model_payload(request.capabilities) if request.capabilities else {},
        }
        return client_id, record

    def register_client(self, request: ClientRegisterRequest) -> dict[str, Any]:
        client_id, record = self._client_from_request(request)
        already_active = client_id in self.clients and not bool(self.clients[client_id].get("deactivated"))
        if not already_active and self.active_client_count >= HUB_FEATURE_FLAGS["max_hub_clients"]:
            raise HTTPException(status_code=403, detail={"code": "client_limit_reached", "message": "Registered Local Skill Hub supports up to 100 active client instances."})
        self.clients[client_id] = record
        self.save_clients()
        self.audit("client_registered", client_id=client_id, agent=record["agent"], display_name=record["display_name"])
        return {"schema_version": 1, "client_id": client_id, "active_client_count": self.active_client_count, "active_client_limit": HUB_FEATURE_FLAGS["max_hub_clients"]}

    def heartbeat(self, request: ClientRegisterRequest) -> dict[str, Any]:
        client_id = request.capabilities.client_id if request.capabilities and request.capabilities.client_id else ""
        if client_id and client_id in self.clients:
            self.clients[client_id]["last_seen_at"] = time.time()
            self.clients[client_id]["deactivated"] = False
            self.clients[client_id]["request_count"] = int(self.clients[client_id].get("request_count") or 0) + 1
            self.save_clients()
            self.audit("client_heartbeat", client_id=client_id, agent=self.clients[client_id].get("agent"))
            return {"schema_version": 1, "client_id": client_id, "active_client_count": self.active_client_count}
        return self.register_client(request)

    def deactivate_client(self, client_id: str) -> dict[str, Any]:
        if client_id not in self.clients:
            raise HTTPException(status_code=404, detail={"code": "client_not_found", "message": "Client is not registered with this hub."})
        self.clients[client_id]["deactivated"] = True
        self.clients[client_id]["deactivated_at"] = time.time()
        self.save_clients()
        self.audit("client_deactivated", client_id=client_id)
        return {"schema_version": 1, "client_id": client_id, "status": "deactivated", "active_client_count": self.active_client_count}

    def list_clients(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "active_client_count": self.active_client_count,
            "active_client_limit": HUB_FEATURE_FLAGS["max_hub_clients"],
            "clients": [
                {
                    "client_id": str(item.get("client_id") or ""),
                    "display_name": str(item.get("display_name") or ""),
                    "agent": str(item.get("agent") or "unknown"),
                    "os": str(item.get("os") or ""),
                    "arch": str(item.get("arch") or ""),
                    "first_seen_at": item.get("first_seen_at"),
                    "last_seen_at": item.get("last_seen_at"),
                    "request_count": int(item.get("request_count") or 0),
                    "deactivated": bool(item.get("deactivated")),
                }
                for item in sorted(self.clients.values(), key=lambda value: str(value.get("client_id") or ""))
            ],
        }

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
            "local_install_plan_skills": len([item for item in self.allowlisted.values() if item.requires_local_install]),
            "vector_index_present": False,
            "hosted_query_forwarding": False,
            "allowlist_path": str(self.allowlist_path),
            "clients_path": str(self.clients_path),
            "audit_log_path": str(self.audit_path),
        }

    def metrics(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "uptime_seconds": round(time.time() - self.started_at, 3),
            "requests_total": self.request_count,
            "events_by_type": dict(sorted(self.events_by_type.items())),
            "clients": {
                "registered_total": len(self.clients),
                "active": self.active_client_count,
                "deactivated": sum(1 for item in self.clients.values() if bool(item.get("deactivated"))),
                "limit": HUB_FEATURE_FLAGS["max_hub_clients"],
                "active_window_seconds": ACTIVE_CLIENT_WINDOW_SECONDS,
            },
            "skills": {
                "total": len(self.allowlisted),
                "allowlisted_body": len([item for item in self.allowlisted.values() if item.body_allowed]),
                "local_install_plan": len([item for item in self.allowlisted.values() if item.requires_local_install]),
            },
            "distribution_mode": "allowlist_only",
            "hub_executes_skills": False,
            "hosted_query_forwarding": False,
            "audit_log_path": str(self.audit_path),
        }


def load_allowlist_manifest(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise RuntimeError(f"Local Skill Hub allowlist is required: {path}")
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(data, dict):
        raise RuntimeError("Hub allowlist must be a JSON object.")
    return validate_allowlist(data)


def hub_error(code: str, message: str, status_code: int = 401) -> HTTPException:
    return HTTPException(
        status_code=status_code,
        detail={"schema_version": 1, "error": {"code": code, "message": redact_sensitive_text(message)}},
    )


def token_from_headers(authorization: str = "", x_uls_hub_token: str = "") -> str:
    auth = authorization.strip()
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    return x_uls_hub_token.strip()


def require_hub_token(
    authorization: str = Header(default="", alias="Authorization"),
    x_uls_hub_token: str = Header(default="", alias="X-ULS-Hub-Token"),
) -> dict[str, Any]:
    raw_token = token_from_headers(authorization, x_uls_hub_token)
    ok, code, record = verify_hub_token(raw_token)
    if ok and record is not None:
        return record
    messages = {
        "hub_token_required": "Local Skill Hub client token is required.",
        "invalid_hub_token": "Local Skill Hub client token is invalid.",
        "hub_token_revoked": "Local Skill Hub client token is revoked.",
    }
    raise hub_error(code, messages.get(code, "Local Skill Hub client token was rejected."))


def model_payload(model: BaseModel) -> dict[str, Any]:
    if hasattr(model, "model_dump"):
        return model.model_dump()
    return model.dict()


def skill_kind_for(item: dict[str, Any]) -> str:
    explicit = str(item.get("skill_kind") or "").strip()
    if explicit in {"pure_text", "asset", "tool", "platform", "secret_dependent"}:
        return explicit
    reqs = item.get("local_requirements") if isinstance(item.get("local_requirements"), dict) else {}
    secrets_policy = item.get("secrets_policy") if isinstance(item.get("secrets_policy"), dict) else {}
    if secrets_policy.get("requires_secrets") or reqs.get("env_vars"):
        return "secret_dependent"
    if reqs.get("platforms") or item.get("platforms"):
        return "platform"
    if reqs.get("python_packages") or reqs.get("npm_packages") or reqs.get("binaries"):
        return "tool"
    if item.get("requires_local_install_plan"):
        return "tool"
    if (item.get("asset_policy") or {}).get("distribute_assets"):
        return "asset"
    return "pure_text"


def runtime_manifest_from_item(item: dict[str, Any], *, name: str, kind: str, hub_behavior: str) -> dict[str, Any]:
    distribution = item.get("distribution") if isinstance(item.get("distribution"), dict) else {}
    requirements = item.get("local_requirements") if isinstance(item.get("local_requirements"), dict) else {}
    assets = item.get("assets") if isinstance(item.get("assets"), dict) else {}
    execution = item.get("execution") if isinstance(item.get("execution"), dict) else {}
    secrets_policy = item.get("secrets_policy") if isinstance(item.get("secrets_policy"), dict) else {}
    secret_names = list(dict.fromkeys([*(str(value) for value in secrets_policy.get("secret_names", []) if isinstance(value, str)), *(str(value) for value in requirements.get("env_vars", []) if isinstance(value, str))]))
    return {
        "schema_version": 1,
        "name": name,
        "skill_kind": kind,
        "distribution": {
            "central_retrieval": bool(distribution.get("central_retrieval", True)),
            "central_body_distribution": bool(distribution.get("central_body_distribution", hub_behavior in {"distribute_body", "distribute_body_and_assets"})),
            "central_asset_distribution": bool(distribution.get("central_asset_distribution", False)),
            "default_hub_behavior": str(distribution.get("default_hub_behavior") or hub_behavior or "metadata_only"),
        },
        "compatible_agents": [str(value) for value in item.get("compatible_agents", []) if isinstance(value, str)],
        "platforms": [str(value).lower() for value in (item.get("platforms") or requirements.get("platforms") or []) if isinstance(value, str)],
        "local_requirements": {
            "python_packages": [str(value) for value in requirements.get("python_packages", []) if isinstance(value, str)],
            "npm_packages": [str(value) for value in requirements.get("npm_packages", []) if isinstance(value, str)],
            "binaries": [str(value) for value in requirements.get("binaries", []) if isinstance(value, str)],
            "env_vars": secret_names,
            "platforms": [str(value).lower() for value in requirements.get("platforms", []) if isinstance(value, str)],
        },
        "assets": {
            "required": bool(assets.get("required", False)),
            "distributable": bool(assets.get("distributable", False)),
            "files": [str(value) for value in assets.get("files", []) if isinstance(value, str)],
        },
        "execution": {
            "hub_executes": False,
            "client_executes": bool(execution.get("client_executes", False)),
        },
        "secrets_policy": {
            "requires_secrets": bool(secrets_policy.get("requires_secrets", bool(secret_names))),
            "secret_names": secret_names,
        },
    }


def load_runtime_manifest(skill_md: Path, meta: dict[str, str]) -> dict[str, Any]:
    explicit = skill_md.with_name("skill-runtime-manifest.json")
    if explicit.is_file():
        try:
            data = json.loads(explicit.read_text(encoding="utf-8-sig"))
            if isinstance(data, dict):
                return data
        except (OSError, json.JSONDecodeError):
            return {}
    kind = meta.get("skill_kind") or ""
    if kind:
        reqs = {
            "python_packages": split_csv(meta.get("python_packages", "")),
            "npm_packages": split_csv(meta.get("npm_packages", "")),
            "binaries": split_csv(meta.get("binaries", "")),
            "env_vars": split_csv(meta.get("env_vars", "")),
            "platforms": split_csv(meta.get("platforms", "")),
        }
        return runtime_manifest_from_item({"skill_kind": kind, "local_requirements": reqs}, name=meta.get("name") or skill_md.parent.name, kind=kind, hub_behavior=meta.get("hub_behavior") or "metadata_only")
    return {}


def split_csv(value: str) -> list[str]:
    return [item.strip() for item in str(value or "").split(",") if item.strip()]


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
            runtime_manifest=runtime_manifest_from_item(raw, name=str(raw.get("name") or raw.get("skill_id") or ""), kind=skill_kind_for(raw), hub_behavior=str(raw.get("hub_behavior") or "distribute_body")),
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
            runtime_manifest=runtime_manifest_from_item(raw, name=str(raw.get("name") or raw.get("skill_id") or ""), kind=skill_kind_for(raw), hub_behavior=str(raw.get("hub_behavior") or "distribute_body_with_local_install_plan")),
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
        records[item_key(collection, name)] = {"path": str(skill_md), "body": text, "description": meta.get("description") or first_body_line(body), "manifest": load_runtime_manifest(skill_md, meta)}
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
    manifest = runtime_manifest_for(skill, local)
    requirements = manifest.get("local_requirements", {})
    return {
        "name": skill.name,
        "collection": skill.collection,
        "confidence": round(confidence, 4),
        "sha256": skill.sha256,
        "skill_kind": skill.skill_kind,
        "hub_behavior": skill.hub_behavior,
        "requires_local_install": skill.requires_local_install,
        "install_plan_available": has_local_requirements(requirements),
        "runtime_manifest": manifest,
        "available_locally": bool(local),
    }


def runtime_manifest_for(skill: HubSkill, local: dict[str, Any] | None) -> dict[str, Any]:
    local_manifest = local.get("manifest") if isinstance(local, dict) and isinstance(local.get("manifest"), dict) else {}
    if local_manifest:
        merged = dict(skill.runtime_manifest)
        merged.update(local_manifest)
        merged.setdefault("name", skill.name)
        return merged
    return dict(skill.runtime_manifest)


def has_local_requirements(requirements: dict[str, Any]) -> bool:
    return any(requirements.get(key) for key in ("python_packages", "npm_packages", "binaries", "env_vars", "platforms"))


def compare_capabilities(manifest: dict[str, Any], capabilities: ClientCapabilities | None) -> tuple[list[str], list[str]]:
    requirements = manifest.get("local_requirements", {}) if isinstance(manifest.get("local_requirements"), dict) else {}
    caps = model_payload(capabilities) if capabilities else {}
    available_tools = {str(value).lower() for value in caps.get("available_tools", []) if isinstance(value, str)}
    env_names = {str(value) for value in caps.get("env_vars_present", []) if isinstance(value, str)}
    installed = caps.get("installed_packages", {}) if isinstance(caps.get("installed_packages"), dict) else {}
    python_packages = {str(value).lower() for value in installed.get("python", []) if isinstance(value, str)}
    npm_packages = {str(value).lower() for value in installed.get("npm", []) if isinstance(value, str)}
    client_os = str(caps.get("os") or "").lower()
    missing: list[str] = []
    matched: list[str] = []
    for value in requirements.get("python_packages", []):
        marker = f"python_package:{value}"
        (matched if str(value).lower() in python_packages else missing).append(marker)
    for value in requirements.get("npm_packages", []):
        marker = f"npm_package:{value}"
        (matched if str(value).lower() in npm_packages else missing).append(marker)
    for value in requirements.get("binaries", []):
        marker = f"binary:{value}"
        (matched if str(value).lower() in available_tools else missing).append(marker)
    for value in requirements.get("env_vars", []):
        marker = f"env_var:{value}"
        (matched if str(value) in env_names else missing).append(marker)
    platforms = [str(value).lower() for value in requirements.get("platforms", []) or manifest.get("platforms", []) if isinstance(value, str)]
    if platforms:
        marker = "platform:" + "|".join(platforms)
        (matched if client_os in platforms else missing).append(marker)
    return missing, matched


def resolve_skills(state: HubState, request: SkillResolveRequest) -> dict[str, Any]:
    hits = search_skills(state, request.query, request.context_budget.max_skills, include_local_install_plan=True)
    selected: list[dict[str, Any]] = []
    used_chars = 0
    for hit in hits:
        skill = state.allowlisted[item_key(hit["collection"], hit["name"])]
        local = state.local_skills.get(item_key(skill.collection, skill.name))
        body = ""
        warnings: list[str] = []
        manifest = runtime_manifest_for(skill, local)
        missing, matched = compare_capabilities(manifest, request.client_capabilities)
        if skill.requires_local_install or missing:
            warnings.append("Local install plan is metadata/dry-run only. Install dependencies locally before using this skill.")
        elif skill.body_allowed and local:
            body = local["body"][: max(request.context_budget.max_chars - used_chars, 0)]
            used_chars += len(body)
        elif skill.body_allowed:
            warnings.append("Skill is allowlisted but not present in the local hub library.")
        selected.append({**hit, "body": body, "missing_capabilities": missing, "matched_capabilities": matched, "install_plan_available": has_local_requirements(manifest.get("local_requirements", {})), "warnings": warnings})
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
        payload["warnings"] = ["Local install plan is metadata/dry-run only. Install dependencies locally before using this skill."]
    else:
        payload["warnings"] = [] if local else ["Skill is allowlisted but not present in the local hub library."]
    return {"schema_version": 1, "skill": payload}


def create_app(root: Path | None = None, allowlist_path: Path | None = None) -> FastAPI:
    state = HubState(root or DEFAULT_HUB_ROOT, allowlist_path or DEFAULT_ALLOWLIST_PATH)
    app = FastAPI(title="Unlimited Skills Local Skill Hub", version=__version__)
    app.state.hub_state = state

    @app.exception_handler(HTTPException)
    def http_exception_handler(_request, exc: HTTPException):
        if isinstance(exc.detail, dict) and "schema_version" in exc.detail and "error" in exc.detail:
            return JSONResponse(status_code=exc.status_code, content=exc.detail)
        if isinstance(exc.detail, dict) and "code" in exc.detail:
            return JSONResponse(status_code=exc.status_code, content={"schema_version": 1, "error": {"code": exc.detail.get("code"), "message": redact_sensitive_text(exc.detail.get("message", ""))}})
        return JSONResponse(status_code=exc.status_code, content={"schema_version": 1, "error": {"code": "http_error", "message": redact_sensitive_text(exc.detail)}})

    @app.get("/health")
    def health() -> dict[str, Any]:
        return {"ok": True, "distribution_mode": "allowlist_only", "hosted_query_forwarding": False, "hub_executes_skills": False}

    @app.get("/v1/hub/status")
    def status(_token: dict[str, Any] = Depends(require_hub_token)) -> dict[str, Any]:
        state.audit("hub_status", token_id=_token.get("token_id"), token_label=_token.get("label"))
        return state.status()

    @app.get("/v1/hub/metrics")
    def metrics(_token: dict[str, Any] = Depends(require_hub_token)) -> dict[str, Any]:
        state.audit("hub_metrics", token_id=_token.get("token_id"), token_label=_token.get("label"))
        return state.metrics()

    @app.post("/v1/clients/register")
    def register_client(request: ClientRegisterRequest, _token: dict[str, Any] = Depends(require_hub_token)) -> dict[str, Any]:
        return state.register_client(request)

    @app.post("/v1/clients/heartbeat")
    def heartbeat(request: ClientRegisterRequest, _token: dict[str, Any] = Depends(require_hub_token)) -> dict[str, Any]:
        return state.heartbeat(request)

    @app.get("/v1/clients")
    def clients(_token: dict[str, Any] = Depends(require_hub_token)) -> dict[str, Any]:
        state.audit("clients_listed", token_id=_token.get("token_id"), token_label=_token.get("label"))
        return state.list_clients()

    @app.post("/v1/clients/{client_id}/deactivate")
    def deactivate_client(client_id: str, _token: dict[str, Any] = Depends(require_hub_token)) -> dict[str, Any]:
        return state.deactivate_client(client_id)

    @app.post("/v1/skills/search")
    def search(request: SkillSearchRequest, _token: dict[str, Any] = Depends(require_hub_token)) -> dict[str, Any]:
        state.audit("skills_search", token_id=_token.get("token_id"), query_sha256=hashlib.sha256(request.query.encode("utf-8")).hexdigest(), limit=request.limit)
        return {"schema_version": 1, "query": request.query, "results": search_skills(state, request.query, request.limit, include_local_install_plan=request.include_local_install_plan)}

    @app.post("/v1/skills/resolve")
    def resolve(request: SkillResolveRequest, _token: dict[str, Any] = Depends(require_hub_token)) -> dict[str, Any]:
        state.audit("skills_resolve", token_id=_token.get("token_id"), query_sha256=hashlib.sha256(request.query.encode("utf-8")).hexdigest(), max_skills=request.context_budget.max_skills)
        return resolve_skills(state, request)

    @app.get("/v1/skills/{name}")
    def skill(name: str, _token: dict[str, Any] = Depends(require_hub_token)) -> dict[str, Any]:
        state.audit("skill_viewed", token_id=_token.get("token_id"), skill_name=name)
        return get_skill_by_name(state, name)

    @app.get("/v1/skills/{name}/manifest")
    def skill_manifest(name: str, _token: dict[str, Any] = Depends(require_hub_token)) -> dict[str, Any]:
        state.audit("skill_manifest_viewed", token_id=_token.get("token_id"), skill_name=name)
        payload = get_skill_by_name(state, name)["skill"]
        return {"schema_version": 1, "manifest": payload.get("runtime_manifest", {}), "install_plan": {key: value for key, value in payload.items() if key not in {"body", "runtime_manifest"}}}

    @app.post("/v1/skills/use")
    def skill_use(request: SkillEventRequest, _token: dict[str, Any] = Depends(require_hub_token)) -> dict[str, Any]:
        state.audit("skill_used", token_id=_token.get("token_id"), skill_name=request.skill_name, verdict=request.verdict)
        return {"schema_version": 1, "accepted": True, "event": "use", "skill_name": request.skill_name}

    @app.post("/v1/skills/feedback")
    def skill_feedback(request: SkillEventRequest, _token: dict[str, Any] = Depends(require_hub_token)) -> dict[str, Any]:
        state.audit("skill_feedback", token_id=_token.get("token_id"), skill_name=request.skill_name, verdict=request.verdict)
        return {"schema_version": 1, "accepted": True, "event": "feedback", "skill_name": request.skill_name, "verdict": request.verdict}

    return app


app: FastAPI | None = None
