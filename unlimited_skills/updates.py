from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import quote

from . import __version__
from .registration import RegistrationError, RegistrationState, is_secure_or_local_url, post_json, unlimited_skills_home
from .signatures import ManifestSignatureError, verify_manifest_signature

COLLECTIONS_MANIFEST = ".unlimited-skills-collections.json"
COLLECTION_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
REGISTRY_CACHE_DIR = "registry-cache"
RELEASE_STATE_NAME = "release-channel.json"
ROLLBACKS_DIR = ".rollbacks"


class RegistrationRequired(RuntimeError):
    """Raised when hosted catalog or collection updates are requested without registration."""


class UpdateError(RuntimeError):
    """Raised when a hosted collection update cannot be checked or applied."""


def preview_only_update_recommendation_flags() -> dict[str, bool]:
    return {
        "preview_only": True,
        "automatic_update": False,
        "automatic_install": False,
        "automatic_remove": False,
    }


@dataclass(frozen=True)
class CollectionUpdate:
    collection: str
    version: str
    archive_url: str
    sha256: str
    signature: str = ""
    pack_id: str = ""
    notes: str = ""
    format: str = "skill-collection-zip-v1"


@dataclass(frozen=True)
class EnhancementScript:
    script_id: str
    version: str
    download_url: str
    sha256: str
    signature: str
    notes: str = ""


@dataclass(frozen=True)
class ReleaseChannelState:
    channel: str = "stable"
    pinned: bool = False
    updated_at: str = ""

    def to_json(self) -> dict[str, Any]:
        return {"schema_version": 1, "channel": self.channel, "pinned": self.pinned, "updated_at": self.updated_at}


def now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def safe_timestamp() -> str:
    return time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())


def release_state_path(home: Path | None = None) -> Path:
    return (home or unlimited_skills_home()) / RELEASE_STATE_NAME


def load_release_channel(home: Path | None = None) -> ReleaseChannelState:
    path = release_state_path(home)
    if not path.is_file():
        return ReleaseChannelState()
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return ReleaseChannelState()
    channel = str(payload.get("channel") or "stable") if isinstance(payload, dict) else "stable"
    validate_collection_name(channel)
    return ReleaseChannelState(channel=channel, pinned=bool(payload.get("pinned", False)), updated_at=str(payload.get("updated_at") or ""))


def save_release_channel(channel: str, *, pinned: bool = True, home: Path | None = None) -> Path:
    validate_collection_name(channel)
    from .policy_enforcement import enforce_release_channel

    enforce_release_channel(channel, action="release channel pin", home=home)
    state = ReleaseChannelState(channel=channel, pinned=pinned, updated_at=now_iso())
    path = release_state_path(home)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state.to_json(), ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def read_collection_manifest(root: Path) -> dict[str, Any]:
    path = root / COLLECTIONS_MANIFEST
    if not path.exists():
        return {"schema_version": 1, "collections": {}}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise UpdateError(f"Cannot read collection manifest: {path}") from exc
    if not isinstance(data, dict):
        raise UpdateError(f"Collection manifest must be a JSON object: {path}")
    data.setdefault("schema_version", 1)
    data.setdefault("collections", {})
    return data


def write_collection_manifest(root: Path, data: dict[str, Any]) -> None:
    path = root / COLLECTIONS_MANIFEST
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def registry_response_cache_path(kind: str) -> Path:
    safe_kind = re.sub(r"[^A-Za-z0-9._-]+", "-", kind).strip("-") or "response"
    return unlimited_skills_home() / REGISTRY_CACHE_DIR / f"{safe_kind}.json"


def save_registry_response_cache(kind: str, response: dict[str, Any]) -> Path:
    path = registry_response_cache_path(kind)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"schema_version": 1, "cached_at": now_iso(), "kind": kind, "response": response}
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def load_registry_response_cache(kind: str) -> dict[str, Any] | None:
    path = registry_response_cache_path(kind)
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return None
    response = payload.get("response") if isinstance(payload, dict) else None
    return response if isinstance(response, dict) else None


def _count_bucket(count: int) -> str:
    if count <= 0:
        return "0"
    if count <= 10:
        return "1-10"
    if count <= 50:
        return "11-50"
    if count <= 250:
        return "51-250"
    if count <= 1000:
        return "251-1000"
    return "1000+"


def current_collection_state(root: Path) -> dict[str, dict[str, str]]:
    manifest = read_collection_manifest(root)
    known = manifest.get("collections") if isinstance(manifest.get("collections"), dict) else {}
    state: dict[str, dict[str, str]] = {}
    if not root.exists():
        return state
    registry_root = root / "registry"
    registry_children = sorted(item for item in registry_root.iterdir() if item.is_dir() and not item.name.startswith(".")) if registry_root.is_dir() else []
    for child in registry_children:
        count = sum(1 for _ in (child / "skills").rglob("SKILL.md"))
        metadata = known.get(child.name, {}) if isinstance(known, dict) else {}
        state[child.name] = {
            "version": str(metadata.get("version") or "local"),
            "source": str(metadata.get("source") or "local"),
            "skill_count_bucket": _count_bucket(count),
        }
    local_root = root / "local"
    if local_root.is_dir():
        count = sum(1 for path in local_root.rglob("SKILL.md") if "duplicates" not in path.relative_to(local_root).parts)
        metadata = known.get("local", {}) if isinstance(known, dict) else {}
        state["local"] = {
            "version": str(metadata.get("version") or "local"),
            "source": str(metadata.get("source") or "local"),
            "skill_count_bucket": _count_bucket(count),
        }
    # Backward compatibility for pre-registry-layout installs.
    for child in sorted(item for item in root.iterdir() if item.is_dir() and not item.name.startswith(".") and item.name not in {"registry", "local", "manifests"}):
        if child.name in state:
            continue
        count = sum(1 for _ in (child / "skills").rglob("SKILL.md"))
        metadata = known.get(child.name, {}) if isinstance(known, dict) else {}
        state[child.name] = {
            "version": str(metadata.get("version") or "local"),
            "source": str(metadata.get("source") or "local"),
            "skill_count_bucket": _count_bucket(count),
        }
    return state


def _archive_url_from_pack(pack: dict[str, Any], *, registry_url: str = "") -> str:
    archive = pack.get("archive", {}) if isinstance(pack.get("archive"), dict) else {}
    archive_url = str(pack.get("archive_url") or pack.get("download_url") or archive.get("archive_url") or archive.get("download_url") or archive.get("url") or "")
    if archive_url or not registry_url:
        return archive_url
    collection = str(pack.get("collection") or "")
    version = str(pack.get("version") or "")
    filename = str(archive.get("filename") or "")
    if not collection or not version or not filename:
        return ""
    return f"{registry_url.rstrip('/')}/v1/catalog/packs/{quote(collection, safe='')}/{quote(version, safe='')}/{quote(filename, safe='')}"


def parse_updates(data: dict[str, Any], *, registry_url: str = "") -> list[CollectionUpdate]:
    raw_updates = data.get("updates") or []
    if not raw_updates and isinstance(data.get("packs"), list):
        raw_updates = []
        for pack in data.get("packs", []):
            if not isinstance(pack, dict):
                continue
            archive = pack.get("archive", {}) if isinstance(pack.get("archive"), dict) else {}
            archive_url = _archive_url_from_pack(pack, registry_url=registry_url)
            if not archive_url:
                continue
            raw_updates.append(
                {
                    "collection": pack.get("collection"),
                    "version": pack.get("version"),
                    "archive_url": archive_url,
                    "sha256": archive.get("sha256") or pack.get("sha256"),
                    "signature": pack.get("signature") or "",
                    "pack_id": pack.get("pack_id") or "",
                    "notes": pack.get("notes") or "",
                    "format": pack.get("format") or "skill-collection-zip-v1",
                }
            )
    if not isinstance(raw_updates, list):
        raise UpdateError("Update service returned invalid updates payload.")
    updates: list[CollectionUpdate] = []
    for item in raw_updates:
        if not isinstance(item, dict):
            continue
        collection = str(item.get("collection") or "")
        version = str(item.get("version") or "")
        archive_url = str(item.get("archive_url") or item.get("download_url") or "")
        sha256 = str(item.get("sha256") or "")
        if not collection or not version or not archive_url or not sha256:
            raise UpdateError("Each collection update must include collection, version, archive_url, and sha256.")
        validate_collection_name(collection)
        updates.append(
            CollectionUpdate(
                collection=collection,
                version=version,
                archive_url=archive_url,
                sha256=sha256,
                signature=str(item.get("signature") or ""),
                pack_id=str(item.get("pack_id") or ""),
                notes=str(item.get("notes") or ""),
                format=str(item.get("format") or "skill-collection-zip-v1"),
            )
        )
    return updates


def parse_enhancement_script(data: dict[str, Any]) -> EnhancementScript:
    source = data
    if not data.get("script_id") and isinstance(data.get("scripts"), list) and data["scripts"]:
        first = data["scripts"][0]
        if isinstance(first, dict):
            source = first
    script_id = str(source.get("script_id") or "")
    version = str(source.get("version") or "")
    download_url = str(source.get("download_url") or "")
    sha256 = str(source.get("sha256") or "")
    signature = str(source.get("signature") or "")
    if not script_id or not version or not download_url or not sha256:
        raise UpdateError("Enhancement service must return script_id, version, download_url, and sha256.")
    validate_collection_name(script_id)
    return EnhancementScript(
        script_id=script_id,
        version=version,
        download_url=download_url,
        sha256=sha256,
        signature=signature,
        notes=str(source.get("notes") or data.get("notes") or ""),
    )


def validate_collection_name(collection: str) -> None:
    if not COLLECTION_NAME_RE.match(collection):
        raise UpdateError(f"Unsafe collection name: {collection}")


class UpdateClient:
    def __init__(self, state: RegistrationState, *, timeout: float = 30.0, channel: str = "") -> None:
        if not state.registered:
            raise RegistrationRequired(
                "Official registry features require registration. The MIT core remains fully usable offline: local search, "
                "local skill library, local imports, router skill, daemon, reindex, list, and view."
            )
        self.state = state
        self.timeout = timeout
        pinned = load_release_channel()
        resolved_channel = channel or pinned.channel or "stable"
        validate_collection_name(resolved_channel)
        from .policy_enforcement import enforce_release_channel

        enforce_release_channel(resolved_channel, action="registered update channel")
        self.channel = resolved_channel

    def check(self, root: Path) -> list[CollectionUpdate]:
        payload = {
            "schema_version": 1,
            "install_id": self.state.install_id,
            "client": {"name": "unlimited-skills", "version": __version__},
            "channel": self.channel,
            "collections": current_collection_state(root),
        }
        try:
            response = post_json(
                f"{self.state.server_url.rstrip('/')}/v1/collections/updates",
                payload,
                token=self.state.license_token,
                proof_state=self.state,
                timeout=self.timeout,
                retry_safe=True,
            )
        except RegistrationError:
            cached = load_registry_response_cache("collection-updates")
            if cached is None:
                raise
            response = cached
        try:
            verify_manifest_signature(
                response,
                purpose="Hosted collection updates",
                required=True,
                scope="catalog-updates",
                registry_url=self.state.server_url,
            )
        except ManifestSignatureError as exc:
            raise UpdateError(str(exc)) from exc
        save_registry_response_cache("collection-updates", response)
        return parse_updates(response, registry_url=self.state.server_url)

    def catalog(self, root: Path) -> dict[str, Any]:
        payload = {
            "schema_version": 1,
            "install_id": self.state.install_id,
            "client": {"name": "unlimited-skills", "version": __version__},
            "channel": self.channel,
            "collections": current_collection_state(root),
        }
        try:
            response = post_json(
                f"{self.state.server_url.rstrip('/')}/v1/catalog",
                payload,
                token=self.state.license_token,
                proof_state=self.state,
                timeout=self.timeout,
                retry_safe=True,
            )
        except Exception as exc:
            cached = load_registry_response_cache("catalog")
            if cached is None:
                raise
            cached = dict(cached)
            cached["offline_cache"] = True
            cached["offline_cache_reason"] = str(exc)
            return cached
        save_registry_response_cache("catalog", response)
        return response

    def enhancement_script(self, root: Path) -> EnhancementScript:
        payload = {
            "schema_version": 1,
            "install_id": self.state.install_id,
            "client": {"name": "unlimited-skills", "version": __version__},
            "channel": self.channel,
            "collections": current_collection_state(root),
        }
        response = post_json(
            f"{self.state.server_url.rstrip('/')}/v1/enhancement/script",
            payload,
            token=self.state.license_token,
            proof_state=self.state,
            timeout=self.timeout,
            retry_safe=True,
        )
        try:
            verify_manifest_signature(
                response,
                purpose="Enhancement script manifest",
                required=True,
                scope="enhancement-manifest",
                registry_url=self.state.server_url,
            )
        except ManifestSignatureError as exc:
            raise UpdateError(str(exc)) from exc
        return parse_enhancement_script(response)

    def download_enhancement_script(self, root: Path, target_dir: Path | None = None) -> Path:
        script = self.enhancement_script(root)
        target_root = target_dir or (unlimited_skills_home() / "registry-cache" / "enhancers")
        target_root.mkdir(parents=True, exist_ok=True)
        target = target_root / f"{script.script_id}-{script.version}.py"
        download_file(script.download_url, target, timeout=self.timeout)
        actual_sha = sha256_file(target)
        if actual_sha.lower() != script.sha256.lower():
            target.unlink(missing_ok=True)
            raise UpdateError(f"SHA256 mismatch for {script.script_id}: expected {script.sha256}, got {actual_sha}")
        return target

    def run_enhancement_script(self, root: Path, *, apply: bool = False, limit: int = 0, target_dir: Path | None = None) -> int:
        script_path = self.download_enhancement_script(root, target_dir=target_dir)
        command = [sys.executable, str(script_path), "--root", str(root)]
        if apply:
            command.append("--apply")
        if limit:
            command.extend(["--limit", str(limit)])
        completed = subprocess.run(command, check=False)
        return int(completed.returncode)

    def release_channels(self) -> dict[str, Any]:
        response = post_json(
            f"{self.state.server_url.rstrip('/')}/v1/channels/status",
            {
                "schema_version": 1,
                "install_id": self.state.install_id,
                "client": {"name": "unlimited-skills", "version": __version__},
                "channel": self.channel,
            },
            token=self.state.license_token,
            proof_state=self.state,
            timeout=self.timeout,
            retry_safe=True,
        )
        try:
            response["signature_verification"] = verify_manifest_signature(
                response,
                purpose="Release channels manifest",
                required=True,
                scope="release-channels",
                registry_url=self.state.server_url,
            )
        except ManifestSignatureError as exc:
            raise UpdateError(str(exc)) from exc
        return response

    def apply(self, root: Path, update: CollectionUpdate) -> dict[str, str]:
        validate_collection_name(update.collection)
        if update.format != "skill-collection-zip-v1":
            raise UpdateError(f"Unsupported update format: {update.format}")
        root.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="unlimited-skills-update-") as tmp:
            tmp_path = Path(tmp)
            archive = tmp_path / "collection.zip"
            download_archive(update.archive_url, archive, timeout=self.timeout)
            actual_sha = sha256_file(archive)
            if actual_sha.lower() != update.sha256.lower():
                raise UpdateError(f"SHA256 mismatch for {update.collection}: expected {update.sha256}, got {actual_sha}")
            extracted = tmp_path / "extracted"
            safe_extract_zip(archive, extracted)
            source = resolve_collection_source(extracted, update.collection)
            install_collection(root, update, source)
            return {"collection": update.collection, "version": update.version, "sha256": actual_sha}


def download_archive(url: str, target: Path, *, timeout: float = 30.0) -> None:
    download_file(url, target, timeout=timeout)


def download_file(url: str, target: Path, *, timeout: float = 30.0) -> None:
    if not is_secure_or_local_url(url):
        raise UpdateError("Registry download URL must use HTTPS. Plain HTTP is allowed only for localhost development.")
    request = urllib.request.Request(url, headers={"User-Agent": f"unlimited-skills/{__version__}"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            with target.open("wb") as handle:
                shutil.copyfileobj(response, handle)
    except urllib.error.URLError as exc:
        raise UpdateError(f"Cannot download registry file: {exc.reason}") from exc


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def safe_extract_zip(archive: Path, target: Path) -> None:
    target.mkdir(parents=True, exist_ok=True)
    target_root = target.resolve()
    try:
        with zipfile.ZipFile(archive) as zf:
            for member in zf.infolist():
                destination = (target / member.filename).resolve()
                if target_root != destination and target_root not in destination.parents:
                    raise UpdateError(f"Unsafe archive path: {member.filename}")
            zf.extractall(target)
    except zipfile.BadZipFile as exc:
        raise UpdateError("Collection archive is not a valid zip file.") from exc


def resolve_collection_source(extracted: Path, collection: str) -> Path:
    named = extracted / collection
    if (named / "skills").is_dir():
        return named
    if (extracted / "skills").is_dir():
        return extracted
    candidates = [path.parent.parent for path in extracted.rglob("SKILL.md") if path.parent.parent.name == "skills"]
    if len(candidates) == 1:
        return candidates[0]
    raise UpdateError("Collection archive must contain a skills/ directory.")


def install_collection(root: Path, update: CollectionUpdate, source: Path, *, source_label: str = "hosted") -> None:
    target = root / "registry" / update.collection
    backup = root / "registry" / f".{update.collection}.update-backup"
    target.parent.mkdir(parents=True, exist_ok=True)
    if backup.exists():
        stale = root / "registry" / ROLLBACKS_DIR / update.collection / f"{safe_timestamp()}-stale-update-backup"
        stale.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(backup), str(stale))
    previous_manifest = read_collection_manifest(root).get("collections", {}).get(update.collection, {})
    try:
        if target.exists():
            shutil.move(str(target), str(backup))
        shutil.copytree(source, target)
        if backup.exists():
            rollback_target = root / "registry" / ROLLBACKS_DIR / update.collection / f"{safe_timestamp()}-{previous_manifest.get('version', 'previous')}"
            rollback_target.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(backup), str(rollback_target))
            (rollback_target / ".unlimited-skills-rollback.json").write_text(
                json.dumps({"schema_version": 1, "collection": update.collection, "previous_manifest": previous_manifest, "saved_at": now_iso()}, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
    except Exception:
        if target.exists():
            shutil.rmtree(target)
        if backup.exists():
            shutil.move(str(backup), str(target))
        raise

    manifest = read_collection_manifest(root)
    collections = manifest.setdefault("collections", {})
    if not isinstance(collections, dict):
        collections = {}
        manifest["collections"] = collections
    collections[update.collection] = {
        "version": update.version,
        "source": source_label,
        "sha256": update.sha256,
        "updated_at": now_iso(),
    }
    write_collection_manifest(root, manifest)


def rollback_collection(root: Path, collection: str) -> dict[str, Any]:
    validate_collection_name(collection)
    target = root / "registry" / collection
    rollback_root = root / "registry" / ROLLBACKS_DIR / collection
    if not rollback_root.is_dir():
        raise UpdateError(f"No rollback snapshot found for {collection}.")
    candidates = sorted((item for item in rollback_root.iterdir() if item.is_dir()), key=lambda item: item.name, reverse=True)
    if not candidates:
        raise UpdateError(f"No rollback snapshot found for {collection}.")
    snapshot = candidates[0]
    metadata_path = snapshot / ".unlimited-skills-rollback.json"
    previous_manifest: dict[str, Any] = {}
    if metadata_path.is_file():
        try:
            metadata = json.loads(metadata_path.read_text(encoding="utf-8-sig"))
            previous_manifest = metadata.get("previous_manifest", {}) if isinstance(metadata, dict) and isinstance(metadata.get("previous_manifest"), dict) else {}
        except json.JSONDecodeError:
            previous_manifest = {}
    current_snapshot = rollback_root / f"{safe_timestamp()}-rolled-forward"
    if target.exists():
        shutil.move(str(target), str(current_snapshot))
    shutil.move(str(snapshot), str(target))
    manifest = read_collection_manifest(root)
    collections = manifest.setdefault("collections", {})
    if isinstance(collections, dict):
        collections[collection] = previous_manifest or {
            "version": "rolled-back",
            "source": "rollback",
            "sha256": "",
            "updated_at": now_iso(),
        }
    write_collection_manifest(root, manifest)
    return {"collection": collection, "restored_from": str(snapshot), "current_saved_to": str(current_snapshot) if current_snapshot.exists() else ""}
