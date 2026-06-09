from __future__ import annotations

import base64
import hashlib
import json
import re
import shutil
import sys
import tempfile
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any
from urllib.parse import quote

from . import __version__
from .registration import RegistrationError, RegistrationState, post_json, unlimited_skills_home, write_private_json
from .signatures import ManifestSignatureError, verify_manifest_signature
from .updates import (
    CollectionUpdate,
    RegistrationRequired,
    UpdateError,
    current_collection_state,
    download_archive,
    install_collection,
    resolve_collection_source,
    safe_extract_zip,
    sha256_file,
    validate_collection_name,
)

COMMUNITY_REQUIRED_MESSAGE = (
    "Registration is required for hosted community skills. The MIT local core still works offline. "
    "Run: unlimited-skills register"
)
COMMUNITY_INSTALLED_NAME = ".unlimited-skills-community.json"
SUBMISSIONS_DIR = "submissions"
ALLOWED_AGENTS = {"codex", "claude-code", "hermes", "openclaw", "vellum-ai"}
ALLOWED_VISIBILITIES = {"registered-community", "team-free", "pro", "enterprise"}
SKILL_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
SECRET_PATTERNS = [
    re.compile(r"BEGIN (?:RSA|DSA|EC|OPENSSH|PRIVATE) KEY", re.I),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b"),
    re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b"),
    re.compile(r"\b(?:api[_-]?key|secret|password|passwd|token)\s*[:=]\s*['\"]?[^'\"\s]{6,}", re.I),
    re.compile(r"^\s*[A-Z0-9_]*(?:SECRET|TOKEN|PASSWORD|API_KEY)[A-Z0-9_]*\s*=", re.I | re.M),
]
ABSOLUTE_PATH_PATTERNS = [
    re.compile(r"[A-Za-z]:\\[^\s'\"<>]+"),
    re.compile(r"/(?:Users|home|var|etc|srv)/[^\s'\"<>]+"),
]
BLOCKED_DIR_NAMES = {
    ".git",
    ".hg",
    ".svn",
    ".chroma-skills",
    ".learning",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    "__pycache__",
    "node_modules",
    "venv",
}
BLOCKED_FILE_NAMES = {
    ".env",
    ".env.local",
    ".env.production",
}
BLOCKED_SUFFIXES = {
    ".log",
    ".pyc",
    ".pyo",
}


class CommunityError(RuntimeError):
    """Raised when community catalog operations cannot proceed safely."""


class CommunityRegistrationRequired(RegistrationRequired):
    """Raised when hosted community features are requested without registration."""


@dataclass(frozen=True)
class CommunityCatalogItem:
    item_id: str
    kind: str
    name: str
    display_name: str = ""
    description: str = ""
    version: str = ""
    publisher: str = ""
    visibility: str = "registered-community"
    compatible_agents: tuple[str, ...] = ()
    tags: tuple[str, ...] = ()
    skill_count: int = 0
    updated_at: str = ""
    min_client_version: str = ""
    license_label: str = ""
    install_target: str = "community"
    trust: dict[str, Any] | None = None
    stats: dict[str, Any] | None = None


@dataclass(frozen=True)
class CommunitySkillPreview:
    item: CommunityCatalogItem
    manifest_summary: dict[str, Any]
    included_skill_names: tuple[str, ...]
    description: str = ""
    release_notes: str = ""
    required_capabilities: tuple[str, ...] = ()
    install_plan: dict[str, Any] | None = None
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True)
class CommunityInstallPlan:
    item_id: str
    collection: str
    version: str
    archive_url: str = ""
    sha256: str = ""
    skill_count: int = 0
    warnings: tuple[str, ...] = ()
    dry_run: bool = False


@dataclass(frozen=True)
class CommunityInstallResult:
    item_id: str
    collection: str
    version: str
    sha256: str = ""
    installed: bool = False
    dry_run: bool = False
    reindex_recommended: bool = False


@dataclass(frozen=True)
class CommunitySubmissionDraft:
    name: str
    description: str
    source_path: str
    skills: tuple[str, ...]
    files: tuple[dict[str, Any], ...]
    total_bytes: int
    warnings: tuple[str, ...]
    preview_path: str
    metadata: dict[str, Any]


@dataclass(frozen=True)
class CommunitySubmissionResult:
    submission_id: str
    status: str
    preview_path: str
    uploaded: bool
    message: str = ""


@dataclass(frozen=True)
class CommunitySubmissionStatus:
    submission_id: str
    status: str
    reviewer_notes: str = ""
    updated_at: str = ""


@dataclass(frozen=True)
class InstalledCommunityItem:
    name: str
    collection: str
    version: str
    source: str
    installed_at: str = ""
    item_id: str = ""
    update_available: bool = False


def now_compact() -> str:
    return time.strftime("%Y%m%d-%H%M%S", time.gmtime())


def now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _tuple_of_strings(value: Any) -> tuple[str, ...]:
    if isinstance(value, (list, tuple)):
        return tuple(str(item) for item in value)
    if value:
        return (str(value),)
    return ()


def _item_from_json(data: dict[str, Any]) -> CommunityCatalogItem:
    trust = data.get("trust") if isinstance(data.get("trust"), dict) else {}
    stats = data.get("stats") if isinstance(data.get("stats"), dict) else {}
    item_id = str(data.get("item_id") or data.get("id") or "")
    name = str(data.get("name") or item_id)
    if not item_id or not name:
        raise CommunityError("Community catalog item is missing item_id or name.")
    return CommunityCatalogItem(
        item_id=item_id,
        kind=str(data.get("kind") or "skill"),
        name=name,
        display_name=str(data.get("display_name") or name),
        description=str(data.get("description") or ""),
        version=str(data.get("version") or ""),
        publisher=str(data.get("publisher") or ""),
        visibility=str(data.get("visibility") or "registered-community"),
        compatible_agents=_tuple_of_strings(data.get("compatible_agents")),
        tags=_tuple_of_strings(data.get("tags")),
        skill_count=int(data.get("skill_count") or 0),
        updated_at=str(data.get("updated_at") or ""),
        min_client_version=str(data.get("min_client_version") or ""),
        license_label=str(data.get("license_label") or ""),
        install_target=str(data.get("install_target") or "community"),
        trust=trust,
        stats=stats,
    )


def parse_catalog_items(data: dict[str, Any]) -> list[CommunityCatalogItem]:
    raw = data.get("items") or data.get("collections") or []
    if not isinstance(raw, list):
        raise CommunityError("Community service returned an invalid catalog item list.")
    return [_item_from_json(item) for item in raw if isinstance(item, dict)]


def _is_missing_endpoint_error(exc: Exception) -> bool:
    text = str(exc)
    return "HTTP 404" in text or "Not Found" in text


def _pack_archive_url(pack: dict[str, Any], server_url: str) -> str:
    archive = pack.get("archive") if isinstance(pack.get("archive"), dict) else {}
    existing = str(pack.get("archive_url") or pack.get("download_url") or archive.get("url") or archive.get("download_url") or "")
    if existing:
        return existing
    collection = str(pack.get("collection") or "")
    version = str(pack.get("version") or "")
    filename = str(archive.get("filename") or "")
    if not collection or not version or not filename:
        return ""
    return f"{server_url.rstrip('/')}/v1/catalog/packs/{quote(collection, safe='')}/{quote(version, safe='')}/{quote(filename, safe='')}"


def _pack_item(pack: dict[str, Any]) -> CommunityCatalogItem:
    collection = str(pack.get("collection") or "")
    pack_id = str(pack.get("pack_id") or collection)
    return _item_from_json(
        {
            "item_id": pack_id,
            "kind": "skill-pack",
            "name": collection or pack_id,
            "display_name": collection or pack_id,
            "description": str(pack.get("notes") or ""),
            "version": str(pack.get("version") or ""),
            "publisher": str(pack.get("source") or pack.get("source_repo") or "Unlimited Skills Registry"),
            "visibility": "registered-community",
            "compatible_agents": ["codex", "claude-code", "hermes", "openclaw", "vellum-ai"],
            "tags": ["registered-catalog", str(pack.get("channel") or "community")],
            "skill_count": int(pack.get("skill_count") or 0),
            "updated_at": str(pack.get("generated_at") or ""),
            "min_client_version": str(pack.get("min_core_version") or ""),
            "license_label": str(pack.get("license") or "registered-community-terms"),
            "install_target": collection or pack_id,
            "trust": {"requires_registration": bool(pack.get("requires_registration", True)), "signed_catalog": True},
            "stats": {},
        }
    )


def _catalog_packs(data: dict[str, Any]) -> list[dict[str, Any]]:
    packs = data.get("packs") or []
    return [item for item in packs if isinstance(item, dict)] if isinstance(packs, list) else []


def _catalog_items_from_packs(data: dict[str, Any], *, query: str = "", tags: tuple[str, ...] = (), limit: int = 50) -> list[CommunityCatalogItem]:
    query_lower = query.strip().lower()
    wanted_tags = {tag.lower() for tag in tags}
    items: list[CommunityCatalogItem] = []
    for pack in _catalog_packs(data):
        item = _pack_item(pack)
        haystack = " ".join([item.item_id, item.name, item.display_name, item.description, item.publisher]).lower()
        item_tags = {tag.lower() for tag in item.tags}
        if query_lower and query_lower not in haystack:
            continue
        if wanted_tags and not wanted_tags.issubset(item_tags):
            continue
        items.append(item)
        if len(items) >= max(1, min(limit, 500)):
            break
    return items


def _find_catalog_pack(data: dict[str, Any], item_id: str) -> dict[str, Any]:
    wanted = str(item_id or "")
    for pack in _catalog_packs(data):
        if wanted in {str(pack.get("pack_id") or ""), str(pack.get("collection") or ""), str(pack.get("name") or "")}:
            return pack
    raise CommunityError(f"Community pack not found in signed catalog: {item_id}")


def _install_plan_from_catalog_pack(item_id: str, pack: dict[str, Any], server_url: str, *, collection_override: str = "", dry_run: bool = False) -> CommunityInstallPlan:
    archive = pack.get("archive") if isinstance(pack.get("archive"), dict) else {}
    collection = collection_override or str(pack.get("collection") or pack.get("pack_id") or "community")
    validate_collection_name(collection)
    return CommunityInstallPlan(
        item_id=item_id,
        collection=collection,
        version=str(pack.get("version") or ""),
        archive_url=_pack_archive_url(pack, server_url),
        sha256=str(archive.get("sha256") or pack.get("sha256") or ""),
        skill_count=int(pack.get("skill_count") or 0),
        warnings=(),
        dry_run=dry_run,
    )


def parse_preview(data: dict[str, Any]) -> CommunitySkillPreview:
    raw_item = data.get("item")
    if not isinstance(raw_item, dict):
        raise CommunityError("Community preview response must include item metadata.")
    return CommunitySkillPreview(
        item=_item_from_json(raw_item),
        manifest_summary=data.get("manifest_summary") if isinstance(data.get("manifest_summary"), dict) else {},
        included_skill_names=_tuple_of_strings(data.get("included_skill_names")),
        description=str(data.get("description") or ""),
        release_notes=str(data.get("release_notes") or data.get("changelog") or ""),
        required_capabilities=_tuple_of_strings(data.get("required_capabilities")),
        install_plan=data.get("install_plan") if isinstance(data.get("install_plan"), dict) else {},
        warnings=_tuple_of_strings(data.get("warnings")),
    )


def _install_plan_from_response(item_id: str, data: dict[str, Any], collection_override: str = "") -> CommunityInstallPlan:
    plan = data.get("install_plan") if isinstance(data.get("install_plan"), dict) else data
    collection = collection_override or str(plan.get("collection") or plan.get("install_target") or "community")
    validate_collection_name(collection)
    return CommunityInstallPlan(
        item_id=item_id,
        collection=collection,
        version=str(plan.get("version") or data.get("version") or "community"),
        archive_url=str(plan.get("archive_url") or plan.get("download_url") or data.get("archive_url") or ""),
        sha256=str(plan.get("sha256") or data.get("sha256") or ""),
        skill_count=int(plan.get("skill_count") or data.get("skill_count") or 0),
        warnings=_tuple_of_strings(plan.get("warnings") or data.get("warnings")),
        dry_run=bool(plan.get("dry_run") or data.get("dry_run")),
    )


def read_installed_metadata(root: Path) -> dict[str, Any]:
    path = root / COMMUNITY_INSTALLED_NAME
    if not path.exists():
        return {"schema_version": 1, "items": {}}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CommunityError(f"Cannot read community install metadata: {path}") from exc
    if not isinstance(data, dict):
        raise CommunityError(f"Community install metadata must be a JSON object: {path}")
    data.setdefault("schema_version", 1)
    data.setdefault("items", {})
    return data


def write_installed_metadata(root: Path, data: dict[str, Any]) -> None:
    root.mkdir(parents=True, exist_ok=True)
    path = root / COMMUNITY_INSTALLED_NAME
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def list_installed_community_items(root: Path) -> list[InstalledCommunityItem]:
    metadata = read_installed_metadata(root)
    items = metadata.get("items") if isinstance(metadata.get("items"), dict) else {}
    installed: list[InstalledCommunityItem] = []
    for collection, row in sorted(items.items()):
        if not isinstance(row, dict):
            continue
        installed.append(
            InstalledCommunityItem(
                name=str(row.get("name") or collection),
                collection=str(collection),
                version=str(row.get("version") or "local"),
                source=str(row.get("source") or "community"),
                installed_at=str(row.get("installed_at") or ""),
                item_id=str(row.get("item_id") or ""),
                update_available=bool(row.get("update_available", False)),
            )
        )
    return installed


def _split_frontmatter(text: str) -> tuple[dict[str, str], str]:
    text = text.lstrip("\ufeff")
    if not text.startswith("---"):
        return {}, text
    lines = text.splitlines()
    end = None
    for idx in range(1, len(lines)):
        if lines[idx].strip() == "---":
            end = idx
            break
    if end is None:
        return {}, text
    meta: dict[str, str] = {}
    for line in lines[1:end]:
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        meta[key.strip().lower()] = value.strip().strip("'\"")
    return meta, "\n".join(lines[end + 1 :])


def _source_root_for_submission(path: Path) -> tuple[Path, list[Path]]:
    path = path.expanduser().resolve()
    if path.is_file():
        if path.name != "SKILL.md":
            raise CommunityError("Community submit accepts a SKILL.md file, a skill directory, or a collection directory.")
        return path.parent, [path]
    if not path.is_dir():
        raise CommunityError(f"Submission path does not exist: {path}")
    skill_files = sorted(path.rglob("SKILL.md"))
    if not skill_files:
        raise CommunityError("Submission path must contain at least one SKILL.md file.")
    return path, skill_files


def _relative_path(root: Path, path: Path) -> str:
    return path.relative_to(root).as_posix()


def _validate_submission_tree(root: Path) -> None:
    for item in root.rglob("*"):
        rel_parts = item.relative_to(root).parts
        if any(part in BLOCKED_DIR_NAMES for part in rel_parts):
            raise CommunityError(f"Refusing to submit blocked directory content: {item}")
        if item.is_file():
            if item.name.startswith(".") or item.name in BLOCKED_FILE_NAMES or item.suffix.lower() in BLOCKED_SUFFIXES:
                raise CommunityError(f"Refusing to submit blocked file: {item}")


def _collect_submission_files(root: Path) -> tuple[list[dict[str, Any]], int, list[str]]:
    files: list[dict[str, Any]] = []
    warnings: list[str] = []
    total = 0
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        rel = _relative_path(root, path)
        raw = path.read_bytes()
        total += len(raw)
        text = raw.decode("utf-8", errors="replace")
        for pattern in SECRET_PATTERNS:
            if pattern.search(text):
                warnings.append(f"possible secret pattern in {rel}")
                break
        for pattern in ABSOLUTE_PATH_PATTERNS:
            if pattern.search(text):
                warnings.append(f"possible local absolute path in {rel}")
                break
        files.append(
            {
                "path": rel,
                "bytes": len(raw),
                "sha256": hashlib.sha256(raw).hexdigest(),
                "content_base64": base64.b64encode(raw).decode("ascii"),
            }
        )
    return files, total, warnings


def build_submission_draft(
    path: Path,
    *,
    name: str = "",
    description: str = "",
    tags: tuple[str, ...] = (),
    compatible_agents: tuple[str, ...] = (),
    visibility: str = "registered-community",
    home: Path | None = None,
) -> CommunitySubmissionDraft:
    if visibility not in ALLOWED_VISIBILITIES:
        raise CommunityError(f"Unsupported community visibility: {visibility}")
    unsupported_agents = [agent for agent in compatible_agents if agent not in ALLOWED_AGENTS]
    if unsupported_agents:
        raise CommunityError(f"Unsupported compatible agent: {unsupported_agents[0]}")

    root, skill_files = _source_root_for_submission(path)
    _validate_submission_tree(root)
    skills: list[str] = []
    first_description = ""
    for skill_file in skill_files:
        meta, _ = _split_frontmatter(skill_file.read_text(encoding="utf-8", errors="replace"))
        skill_name = meta.get("name", "").strip()
        skill_description = meta.get("description", "").strip()
        if not skill_name or not skill_description:
            raise CommunityError(f"SKILL.md must include name and description frontmatter: {skill_file}")
        if not SKILL_NAME_RE.match(skill_name):
            raise CommunityError(f"Unsafe skill name in submission: {skill_name}")
        skills.append(skill_name)
        first_description = first_description or skill_description

    files, total_bytes, warnings = _collect_submission_files(root)
    resolved_name = name or (skills[0] if len(skills) == 1 else root.name)
    resolved_description = description or first_description
    metadata = {
        "name": resolved_name,
        "description": resolved_description,
        "tags": list(tags),
        "compatible_agents": list(compatible_agents),
        "visibility": visibility,
        "skill_count": len(skills),
    }
    preview = {
        "schema_version": 1,
        "source_path": str(root),
        "metadata": metadata,
        "skills": skills,
        "files": [{key: value for key, value in row.items() if key != "content_base64"} for row in files],
        "total_bytes": total_bytes,
        "warnings": sorted(set(warnings)),
        "note": "Community submission uploads the selected skill/pack content for maintainer review.",
    }
    preview_dir = (home or unlimited_skills_home()) / SUBMISSIONS_DIR
    preview_path = preview_dir / f"{now_compact()}-preview.json"
    write_private_json(preview_path, preview)
    return CommunitySubmissionDraft(
        name=resolved_name,
        description=resolved_description,
        source_path=str(root),
        skills=tuple(skills),
        files=tuple(files),
        total_bytes=total_bytes,
        warnings=tuple(sorted(set(warnings))),
        preview_path=str(preview_path),
        metadata=metadata,
    )


class CommunityClient:
    def __init__(self, state: RegistrationState, *, timeout: float = 30.0) -> None:
        if not state.registered:
            raise CommunityRegistrationRequired(COMMUNITY_REQUIRED_MESSAGE)
        self.state = state
        self.timeout = timeout

    def _client_payload(self) -> dict[str, str]:
        return {"name": "unlimited-skills", "version": __version__}

    def _post(self, endpoint: str, payload: dict[str, Any]) -> dict[str, Any]:
        return post_json(
            f"{self.state.server_url.rstrip('/')}{endpoint}",
            payload,
            token=self.state.license_token,
            proof_state=self.state,
            timeout=self.timeout,
        )

    def _signed_catalog(self, root: Path | None = None) -> dict[str, Any]:
        response = self._post(
            "/v1/catalog",
            {
                "schema_version": 1,
                "install_id": self.state.install_id,
                "client": self._client_payload(),
                "collections": current_collection_state(root) if root is not None else {},
            },
        )
        try:
            verify_manifest_signature(
                response,
                purpose="Community catalog fallback",
                required=True,
                scope="catalog-updates",
                registry_url=self.state.server_url,
            )
        except ManifestSignatureError as exc:
            raise CommunityError(str(exc)) from exc
        return response

    def list_community_items(self, root: Path, *, limit: int = 50, compatible_agent: str = "", tags: tuple[str, ...] = ()) -> list[CommunityCatalogItem]:
        payload = {
            "schema_version": 1,
            "install_id": self.state.install_id,
            "client": self._client_payload(),
            "compatible_agent": compatible_agent,
            "tags": list(tags),
            "limit": limit,
            "collections": current_collection_state(root),
        }
        try:
            response = self._post("/v1/community/list", payload)
            return parse_catalog_items(response)
        except RegistrationError as exc:
            if not _is_missing_endpoint_error(exc):
                raise
            catalog = self._signed_catalog(root)
            return _catalog_items_from_packs(catalog, tags=tags, limit=limit)

    def search_community_items(
        self,
        root: Path,
        *,
        query: str,
        tags: tuple[str, ...] = (),
        compatible_agent: str = "",
        limit: int = 20,
    ) -> list[CommunityCatalogItem]:
        payload = {
            "schema_version": 1,
            "install_id": self.state.install_id,
            "client": self._client_payload(),
            "query": query,
            "tags": list(tags),
            "compatible_agent": compatible_agent,
            "limit": limit,
            "collections": current_collection_state(root),
        }
        try:
            response = self._post("/v1/community/search", payload)
            return parse_catalog_items(response)
        except RegistrationError as exc:
            if not _is_missing_endpoint_error(exc):
                raise
            catalog = self._signed_catalog(root)
            return _catalog_items_from_packs(catalog, query=query, tags=tags, limit=limit)

    def preview_community_item(self, item_id: str) -> CommunitySkillPreview:
        payload = {"schema_version": 1, "install_id": self.state.install_id, "client": self._client_payload(), "item_id": item_id}
        try:
            response = self._post("/v1/community/preview", payload)
            return parse_preview(response)
        except RegistrationError as exc:
            if not _is_missing_endpoint_error(exc):
                raise
            catalog = self._signed_catalog()
            pack = _find_catalog_pack(catalog, item_id)
            plan = _install_plan_from_catalog_pack(item_id, pack, self.state.server_url, dry_run=True)
            archive = pack.get("archive") if isinstance(pack.get("archive"), dict) else {}
            return CommunitySkillPreview(
                item=_pack_item(pack),
                manifest_summary={
                    "pack_id": pack.get("pack_id"),
                    "collection": pack.get("collection"),
                    "version": pack.get("version"),
                    "format": pack.get("format"),
                    "archive_filename": archive.get("filename"),
                    "archive_bytes": archive.get("bytes"),
                    "signed_catalog": True,
                },
                included_skill_names=(),
                description=str(pack.get("notes") or ""),
                release_notes=str(pack.get("notes") or ""),
                required_capabilities=(),
                install_plan=asdict(plan),
                warnings=(),
            )

    def install_community_item(
        self,
        root: Path,
        *,
        item_id: str,
        target_collection: str = "",
        dry_run: bool = False,
        force: bool = False,
    ) -> CommunityInstallPlan | CommunityInstallResult:
        from .policy_enforcement import enforce_community_install

        enforce_community_install()
        payload = {
            "schema_version": 1,
            "install_id": self.state.install_id,
            "client": self._client_payload(),
            "item_id": item_id,
            "target_collection": target_collection,
            "dry_run": dry_run,
            "force": force,
            "collections": current_collection_state(root),
        }
        try:
            response = self._post("/v1/community/install", payload)
            plan = _install_plan_from_response(item_id, response, target_collection)
        except RegistrationError as exc:
            if not _is_missing_endpoint_error(exc):
                raise
            catalog = self._signed_catalog(root)
            pack = _find_catalog_pack(catalog, item_id)
            plan = _install_plan_from_catalog_pack(item_id, pack, self.state.server_url, collection_override=target_collection, dry_run=dry_run)
            response = {"name": str(pack.get("collection") or pack.get("pack_id") or item_id)}
        if dry_run:
            return CommunityInstallPlan(**{**asdict(plan), "dry_run": True})
        if not plan.archive_url or not plan.sha256:
            raise CommunityError("Community install response must include archive_url and sha256.")
        root.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="unlimited-skills-community-") as tmp:
            tmp_path = Path(tmp)
            archive = tmp_path / "community.zip"
            download_archive(plan.archive_url, archive, timeout=self.timeout)
            actual_sha = sha256_file(archive)
            if actual_sha.lower() != plan.sha256.lower():
                raise CommunityError(f"SHA256 mismatch for {item_id}: expected {plan.sha256}, got {actual_sha}")
            extracted = tmp_path / "extracted"
            safe_extract_zip(archive, extracted)
            source = resolve_collection_source(extracted, plan.collection)
            update = CollectionUpdate(collection=plan.collection, version=plan.version, archive_url=plan.archive_url, sha256=plan.sha256, pack_id=item_id, notes="community")
            install_collection(root, update, source, source_label="community")

        metadata = read_installed_metadata(root)
        items = metadata.setdefault("items", {})
        if not isinstance(items, dict):
            items = {}
            metadata["items"] = items
        items[plan.collection] = {
            "item_id": item_id,
            "name": str(response.get("name") or item_id),
            "version": plan.version,
            "source": "community",
            "installed_at": now_iso(),
            "sha256": plan.sha256,
        }
        write_installed_metadata(root, metadata)
        return CommunityInstallResult(item_id=item_id, collection=plan.collection, version=plan.version, sha256=plan.sha256, installed=True, reindex_recommended=True)

    def submit_community_skill(self, draft: CommunitySubmissionDraft, *, dry_run: bool = False, confirm: bool = False) -> CommunitySubmissionResult:
        from .policy_enforcement import enforce_community_submit

        enforce_community_submit()
        if dry_run:
            return CommunitySubmissionResult(submission_id="", status="draft", preview_path=draft.preview_path, uploaded=False, message="Dry run: no content uploaded.")
        if not confirm:
            raise CommunityError("Community submission requires explicit confirmation before upload.")
        response = self._post(
            "/v1/community/submit",
            {
                "schema_version": 1,
                "install_id": self.state.install_id,
                "client": self._client_payload(),
                "metadata": draft.metadata,
                "skills": list(draft.skills),
                "files": list(draft.files),
                "total_bytes": draft.total_bytes,
                "warnings": list(draft.warnings),
                "preview_sha256": sha256_file(Path(draft.preview_path)),
            },
        )
        return CommunitySubmissionResult(
            submission_id=str(response.get("submission_id") or ""),
            status=str(response.get("status") or "uploaded"),
            preview_path=draft.preview_path,
            uploaded=True,
            message=str(response.get("message") or ""),
        )

    def get_submission_status(self, submission_id: str = "") -> dict[str, Any]:
        return self._post(
            "/v1/community/submission-status",
            {"schema_version": 1, "install_id": self.state.install_id, "client": self._client_payload(), "submission_id": submission_id},
        )


def remove_community_item(root: Path, name_or_collection: str, *, dry_run: bool = True, force: bool = False) -> dict[str, Any]:
    validate_collection_name(name_or_collection)
    metadata = read_installed_metadata(root)
    items = metadata.get("items") if isinstance(metadata.get("items"), dict) else {}
    collection = name_or_collection
    if collection not in items:
        for candidate, row in items.items():
            if isinstance(row, dict) and (row.get("item_id") == name_or_collection or row.get("name") == name_or_collection):
                collection = str(candidate)
                break
    row = items.get(collection) if isinstance(items, dict) else None
    target = root / "registry" / collection
    if not isinstance(row, dict) and not force:
        raise CommunityError("Refusing to remove a non-community item without --force.")
    if not target.exists():
        if isinstance(items, dict):
            items.pop(collection, None)
            write_installed_metadata(root, metadata)
        return {"collection": collection, "removed": False, "reason": "not installed", "dry_run": dry_run}
    if dry_run:
        return {"collection": collection, "target": str(target), "removed": False, "dry_run": True}
    shutil.rmtree(target)
    if isinstance(items, dict):
        items.pop(collection, None)
    write_installed_metadata(root, metadata)
    return {"collection": collection, "target": str(target), "removed": True, "dry_run": False}


def confirm_upload_or_fail(yes: bool) -> bool:
    if yes:
        return True
    if not sys.stdin.isatty():
        raise CommunityError("Community submission requires --yes in non-interactive mode.")
    typed = input("Type UPLOAD to submit selected skill content for maintainer review: ")
    if typed.strip() != "UPLOAD":
        raise CommunityError("Community submission cancelled.")
    return True
