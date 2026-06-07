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

from . import __version__
from .registration import RegistrationState, is_secure_or_local_url, post_json, unlimited_skills_home

COLLECTIONS_MANIFEST = ".unlimited-skills-collections.json"
COLLECTION_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


class RegistrationRequired(RuntimeError):
    """Raised when hosted catalog or collection updates are requested without registration."""


class UpdateError(RuntimeError):
    """Raised when a hosted collection update cannot be checked or applied."""


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


def now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


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
    for child in sorted(item for item in root.iterdir() if item.is_dir() and not item.name.startswith(".")):
        count = sum(1 for _ in child.rglob("SKILL.md"))
        metadata = known.get(child.name, {}) if isinstance(known, dict) else {}
        state[child.name] = {
            "version": str(metadata.get("version") or "local"),
            "source": str(metadata.get("source") or "local"),
            "skill_count_bucket": _count_bucket(count),
        }
    return state


def parse_updates(data: dict[str, Any]) -> list[CollectionUpdate]:
    raw_updates = data.get("updates") or []
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
    script_id = str(data.get("script_id") or "")
    version = str(data.get("version") or "")
    download_url = str(data.get("download_url") or "")
    sha256 = str(data.get("sha256") or "")
    signature = str(data.get("signature") or "")
    if not script_id or not version or not download_url or not sha256:
        raise UpdateError("Enhancement service must return script_id, version, download_url, and sha256.")
    validate_collection_name(script_id)
    return EnhancementScript(
        script_id=script_id,
        version=version,
        download_url=download_url,
        sha256=sha256,
        signature=signature,
        notes=str(data.get("notes") or ""),
    )


def validate_collection_name(collection: str) -> None:
    if not COLLECTION_NAME_RE.match(collection):
        raise UpdateError(f"Unsafe collection name: {collection}")


class UpdateClient:
    def __init__(self, state: RegistrationState, *, timeout: float = 30.0) -> None:
        if not state.registered:
            raise RegistrationRequired(
                "Official registry features require registration. The MIT core remains fully usable offline: local search, "
                "local skill library, local imports, router skill, daemon, reindex, list, and view."
            )
        self.state = state
        self.timeout = timeout

    def check(self, root: Path) -> list[CollectionUpdate]:
        payload = {
            "schema_version": 1,
            "install_id": self.state.install_id,
            "client": {"name": "unlimited-skills", "version": __version__},
            "collections": current_collection_state(root),
        }
        response = post_json(
            f"{self.state.server_url.rstrip('/')}/v1/collections/updates",
            payload,
            token=self.state.license_token,
            proof_state=self.state,
            timeout=self.timeout,
        )
        return parse_updates(response)

    def catalog(self, root: Path) -> dict[str, Any]:
        payload = {
            "schema_version": 1,
            "install_id": self.state.install_id,
            "client": {"name": "unlimited-skills", "version": __version__},
            "collections": current_collection_state(root),
        }
        response = post_json(
            f"{self.state.server_url.rstrip('/')}/v1/catalog",
            payload,
            token=self.state.license_token,
            proof_state=self.state,
            timeout=self.timeout,
        )
        return response

    def enhancement_script(self, root: Path) -> EnhancementScript:
        payload = {
            "schema_version": 1,
            "install_id": self.state.install_id,
            "client": {"name": "unlimited-skills", "version": __version__},
            "collections": current_collection_state(root),
        }
        response = post_json(
            f"{self.state.server_url.rstrip('/')}/v1/enhancement/script",
            payload,
            token=self.state.license_token,
            proof_state=self.state,
            timeout=self.timeout,
        )
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


def install_collection(root: Path, update: CollectionUpdate, source: Path) -> None:
    target = root / update.collection
    backup = root / f".{update.collection}.update-backup"
    if backup.exists():
        shutil.rmtree(backup)
    try:
        if target.exists():
            shutil.move(str(target), str(backup))
        shutil.copytree(source, target)
        if backup.exists():
            shutil.rmtree(backup)
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
        "source": "hosted",
        "sha256": update.sha256,
        "updated_at": now_iso(),
    }
    write_collection_manifest(root, manifest)
