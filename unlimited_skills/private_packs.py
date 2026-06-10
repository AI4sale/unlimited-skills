from __future__ import annotations

import json
import shutil
import tempfile
import time
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from . import __version__
from .registration import RegistrationError, RegistrationState, is_secure_or_local_url, post_json, proof_headers, redact_sensitive_text
from .signatures import ManifestSignatureError, verify_manifest_signature
from .updates import safe_extract_zip, sha256_file


PRIVATE_PACKS_REQUIRED_MESSAGE = (
    "Registration is required for private team packs. The MIT local core still works offline. "
    "Run: unlimited-skills register"
)
PRIVATE_PACKS_METADATA = ".unlimited-skills-private-packs.json"
PRIVATE_PACKS_SOURCE = "private-team-pack"
PRIVATE_PACK_DENIAL_CODES = {
    "no_entitlement",
    "not_team_member",
    "wrong_agent",
    "wrong_channel",
    "revoked",
    "policy_denied",
    "service_unavailable",
}
PRIVATE_PACK_DENIAL_ALIASES = {
    "missing_entitlement": "no_entitlement",
    "no_private_pack_entitlement": "no_entitlement",
    "registry_access_denied": "no_entitlement",
    "not_a_team_member": "not_team_member",
    "not_org_member": "not_team_member",
    "agent_not_allowed": "wrong_agent",
    "channel_not_allowed": "wrong_channel",
    "pack_revoked": "revoked",
    "denied_by_policy": "policy_denied",
    "unreachable": "service_unavailable",
    "service_unreachable": "service_unavailable",
}


class PrivatePackError(RuntimeError):
    """Raised when private team pack operations cannot proceed safely."""


@dataclass(frozen=True)
class PrivatePackPreview:
    pack_id: str
    team_id: str
    namespace: str
    name: str
    version: str
    visibility: str = "private-team"
    revoked: bool = False
    archive_sha256: str = ""
    archive_bytes: int = 0


@dataclass(frozen=True)
class InstalledPrivatePack:
    pack_id: str
    team_id: str
    name: str
    version: str
    sha256: str
    target: str
    installed_at: str = ""


@dataclass(frozen=True)
class PrivatePackInstallResult:
    pack_id: str
    version: str
    sha256: str
    target: str
    installed: bool
    dry_run: bool = False
    reindex_recommended: bool = False


def now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def read_private_pack_metadata(root: Path) -> dict[str, Any]:
    path = root / PRIVATE_PACKS_METADATA
    if not path.exists():
        return {"schema_version": 1, "items": {}}
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PrivatePackError(f"Cannot read private pack metadata: {path}") from exc
    if not isinstance(payload, dict):
        raise PrivatePackError(f"Private pack metadata must be a JSON object: {path}")
    payload.setdefault("schema_version", 1)
    payload.setdefault("items", {})
    return payload


def write_private_pack_metadata(root: Path, payload: dict[str, Any]) -> None:
    path = root / PRIVATE_PACKS_METADATA
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def list_installed_private_packs(root: Path) -> list[InstalledPrivatePack]:
    metadata = read_private_pack_metadata(root)
    rows = metadata.get("items") if isinstance(metadata.get("items"), dict) else {}
    installed: list[InstalledPrivatePack] = []
    for pack_id, row in sorted(rows.items()):
        if not isinstance(row, dict):
            continue
        installed.append(
            InstalledPrivatePack(
                pack_id=str(pack_id),
                team_id=str(row.get("team_id") or ""),
                name=str(row.get("name") or pack_id),
                version=str(row.get("version") or ""),
                sha256=str(row.get("sha256") or ""),
                target=str(row.get("target") or ""),
                installed_at=str(row.get("installed_at") or ""),
            )
        )
    return installed


def private_pack_ref(pack_id: str) -> str:
    import hashlib

    return "pack:" + hashlib.sha256(pack_id.encode("utf-8")).hexdigest()[:12]


def _preview_from_json(data: dict[str, Any]) -> PrivatePackPreview:
    archive = data.get("archive") if isinstance(data.get("archive"), dict) else {}
    pack_id = str(data.get("pack_id") or "")
    if not pack_id:
        raise PrivatePackError("Private pack metadata is missing pack_id.")
    return PrivatePackPreview(
        pack_id=pack_id,
        team_id=str(data.get("team_id") or ""),
        namespace=str(data.get("namespace") or ""),
        name=str(data.get("name") or pack_id),
        version=str(data.get("version") or ""),
        visibility=str(data.get("visibility") or "private-team"),
        revoked=bool(data.get("revoked")),
        archive_sha256=str(data.get("archive_sha256") or archive.get("sha256") or ""),
        archive_bytes=int(archive.get("bytes") or data.get("bytes") or 0),
    )


def _ensure_registered(state: RegistrationState) -> None:
    if not state.registered:
        raise PrivatePackError(PRIVATE_PACKS_REQUIRED_MESSAGE)


def _private_target(root: Path, pack_id: str) -> Path:
    root = root.expanduser().resolve()
    safe = "".join(ch if ch.isalnum() or ch in "._-" else "-" for ch in pack_id).strip(".-")
    if not safe:
        raise PrivatePackError("Private pack id cannot be converted to a safe local path.")
    target = (root / "registry" / "private" / safe).resolve()
    allowed_root = (root / "registry" / "private").resolve()
    if allowed_root != target and allowed_root not in target.parents:
        raise PrivatePackError("Private pack target escaped registry/private.")
    return target


def _post_private_pack_bytes(state: RegistrationState, endpoint: str, payload: dict[str, Any], *, timeout: float) -> bytes:
    url = f"{state.server_url.rstrip('/')}{endpoint}"
    if not is_secure_or_local_url(url):
        raise PrivatePackError("Private pack download URL must use HTTPS. Plain HTTP is allowed only for localhost development.")
    from .policy_enforcement import enforce_registry_url

    enforce_registry_url(url, action="private pack download")
    body = json.dumps(payload).encode("utf-8")
    headers = {
        "Content-Type": "application/json",
        "User-Agent": f"unlimited-skills/{__version__}",
        "Authorization": f"Bearer {state.license_token}",
    }
    headers.update(proof_headers(state, "POST", url, body))
    request = urllib.request.Request(url, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.read()
    except urllib.error.HTTPError as exc:
        message = redact_sensitive_text(exc.read().decode("utf-8", errors="replace") if exc.fp else str(exc))
        raise PrivatePackError(f"Private pack service returned HTTP {exc.code}: {message}") from exc
    except urllib.error.URLError as exc:
        raise PrivatePackError(f"Private pack service is unreachable: {redact_sensitive_text(exc.reason)}") from exc


def _resolve_archive_source(extracted: Path, pack_id: str) -> Path:
    named = extracted / pack_id
    if (named / "skills").is_dir():
        return named
    if (extracted / "skills").is_dir():
        return extracted
    candidates = [path.parent.parent for path in extracted.rglob("SKILL.md") if path.parent.parent.name == "skills"]
    unique = []
    for candidate in candidates:
        if candidate not in unique:
            unique.append(candidate)
    if len(unique) == 1:
        return unique[0]
    raise PrivatePackError("Private pack archive must contain exactly one skills/ directory.")


def _replace_owned_target(target: Path, source: Path) -> None:
    backup = target.parent / f".{target.name}.private-pack-backup"
    rollback = target.parent / ".rollbacks" / target.name / time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    target.parent.mkdir(parents=True, exist_ok=True)
    if backup.exists():
        stale = target.parent / ".rollbacks" / target.name / f"{time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())}-stale"
        stale.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(backup), str(stale))
    try:
        if target.exists():
            shutil.move(str(target), str(backup))
        shutil.copytree(source, target)
        if backup.exists():
            rollback.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(backup), str(rollback))
    except Exception:
        if target.exists():
            shutil.rmtree(target)
        if backup.exists():
            shutil.move(str(backup), str(target))
        raise


class PrivatePackClient:
    def __init__(self, state: RegistrationState, *, timeout: float = 30.0) -> None:
        _ensure_registered(state)
        self.state = state
        self.timeout = timeout

    def _client_payload(self) -> dict[str, str]:
        return {"name": "unlimited-skills", "version": __version__}

    def _payload(self, extra: dict[str, Any] | None = None) -> dict[str, Any]:
        payload = {"schema_version": 1, "install_id": self.state.install_id, "client": self._client_payload()}
        if extra:
            payload.update(extra)
        return payload

    def _post(self, endpoint: str, payload: dict[str, Any]) -> dict[str, Any]:
        try:
            return post_json(
                f"{self.state.server_url.rstrip('/')}{endpoint}",
                payload,
                token=self.state.license_token,
                proof_state=self.state,
                timeout=self.timeout,
                retry_safe=True,
            )
        except RegistrationError as exc:
            raise PrivatePackError(str(exc)) from exc

    def list(self) -> list[PrivatePackPreview]:
        response = self._post("/v1/private-packs/list", self._payload())
        raw = response.get("packs") or []
        if not isinstance(raw, list):
            raise PrivatePackError("Private pack list response must include packs.")
        return [_preview_from_json(item) for item in raw if isinstance(item, dict)]

    def preview(self, pack_id: str) -> dict[str, Any]:
        response = self._post("/v1/private-packs/preview", self._payload({"pack_id": pack_id}))
        pack = response.get("pack")
        if not isinstance(pack, dict):
            raise PrivatePackError("Private pack preview response must include pack metadata.")
        return {"schema_version": 1, "pack": asdict(_preview_from_json(pack)), "raw": pack}

    def signed_manifest(self, pack_id: str) -> dict[str, Any]:
        response = self._post("/v1/private-packs/manifest", self._payload({"pack_id": pack_id}))
        manifest = response.get("manifest")
        if not isinstance(manifest, dict):
            raise PrivatePackError("Private pack manifest response must include manifest.")
        try:
            verification = verify_manifest_signature(
                manifest,
                purpose="Private team pack manifest",
                required=True,
                scope="private-team-pack",
                registry_url=self.state.server_url,
            )
        except ManifestSignatureError as exc:
            raise PrivatePackError(str(exc)) from exc
        return {"manifest": manifest, "verification": verification}

    def access_check(self, pack_id: str) -> dict[str, Any]:
        return self._post("/v1/private-packs/access-check", self._payload({"pack_id": pack_id}))

    def access_check_diagnostic(self, pack_id: str) -> dict[str, Any]:
        try:
            response = self.access_check(pack_id)
        except PrivatePackError as exc:
            return normalize_private_pack_access_check(
                {"authorized": False, "denial_reasons": ["service_unavailable"], "message": str(exc)},
                pack_id=pack_id,
            )
        return normalize_private_pack_access_check(response, pack_id=pack_id)

    def install(self, root: Path, pack_id: str, *, dry_run: bool = False) -> PrivatePackInstallResult:
        root = root.expanduser().resolve()
        manifest_payload = self.signed_manifest(pack_id)
        manifest = manifest_payload["manifest"]
        target = _private_target(root, pack_id)
        expected_sha = str(manifest.get("sha256") or "")
        version = str(manifest.get("version") or "")
        if dry_run:
            return PrivatePackInstallResult(pack_id=pack_id, version=version, sha256=expected_sha, target=str(target), installed=False, dry_run=True)
        archive_bytes = _post_private_pack_bytes(self.state, "/v1/private-packs/download", self._payload({"pack_id": pack_id}), timeout=self.timeout)
        root.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="unlimited-skills-private-pack-") as tmp:
            tmp_path = Path(tmp)
            archive = tmp_path / "private-pack.zip"
            archive.write_bytes(archive_bytes)
            actual_sha = sha256_file(archive)
            if actual_sha.lower() != expected_sha.lower():
                raise PrivatePackError(f"SHA256 mismatch for {pack_id}: expected {expected_sha}, got {actual_sha}")
            extracted = tmp_path / "extracted"
            safe_extract_zip(archive, extracted)
            source = _resolve_archive_source(extracted, pack_id)
            _replace_owned_target(target, source)

        metadata = read_private_pack_metadata(root)
        items = metadata.setdefault("items", {})
        if not isinstance(items, dict):
            items = {}
            metadata["items"] = items
        items[pack_id] = {
            "team_id": str(manifest.get("team_id") or ""),
            "name": str(manifest.get("name") or pack_id),
            "version": version,
            "sha256": expected_sha,
            "target": str(target.relative_to(root)),
            "source": PRIVATE_PACKS_SOURCE,
            "installed_at": now_iso(),
        }
        write_private_pack_metadata(root, metadata)
        return PrivatePackInstallResult(pack_id=pack_id, version=version, sha256=expected_sha, target=str(target), installed=True, reindex_recommended=True)

    def sync(self, root: Path, *, dry_run: bool = True) -> dict[str, Any]:
        available = self.list()
        installed = {item.pack_id: item for item in list_installed_private_packs(root)}
        planned = []
        applied = []
        for item in available:
            current = installed.get(item.pack_id)
            needs_install = current is None or current.version != item.version or current.sha256.lower() != item.archive_sha256.lower()
            row = {
                "pack_id": item.pack_id,
                "name": item.name,
                "version": item.version,
                "installed_version": current.version if current else "",
                "target": str(_private_target(root, item.pack_id)),
                "action": "install_or_update" if needs_install else "noop",
            }
            planned.append(row)
            if needs_install and not dry_run:
                applied.append(asdict(self.install(root, item.pack_id)))
        return {"schema_version": 1, "dry_run": dry_run, "planned": planned, "applied": applied}


def remove_private_pack(root: Path, pack_id: str, *, dry_run: bool = True) -> dict[str, Any]:
    root = root.expanduser().resolve()
    metadata = read_private_pack_metadata(root)
    items = metadata.get("items") if isinstance(metadata.get("items"), dict) else {}
    row = items.get(pack_id) if isinstance(items, dict) else None
    if not isinstance(row, dict) or row.get("source") != PRIVATE_PACKS_SOURCE:
        raise PrivatePackError("Refusing to remove a private pack that is not marked as registry-owned.")
    target = (root / str(row.get("target") or "")).resolve()
    allowed_root = (root / "registry" / "private").resolve()
    if allowed_root != target and allowed_root not in target.parents:
        raise PrivatePackError("Refusing to remove a target outside registry/private.")
    if dry_run:
        return {"pack_id": pack_id, "target": str(target), "removed": False, "dry_run": True}
    if target.exists():
        shutil.rmtree(target)
    items.pop(pack_id, None)
    write_private_pack_metadata(root, metadata)
    return {"pack_id": pack_id, "target": str(target), "removed": True, "dry_run": False}


def normalize_private_pack_access_check(payload: dict[str, Any], *, pack_id: str = "") -> dict[str, Any]:
    policy = payload.get("access_policy") if isinstance(payload.get("access_policy"), dict) else {}
    raw_reasons = (
        payload.get("denial_reasons")
        or payload.get("reasons")
        or payload.get("reason_code")
        or policy.get("denial_reasons")
        or policy.get("reasons")
        or policy.get("reason_code")
        or []
    )
    if isinstance(raw_reasons, str):
        raw_reasons = [raw_reasons]
    if not isinstance(raw_reasons, list):
        raw_reasons = []
    denied_by_policy = payload.get("policy_denied") is True or policy.get("denied") is True
    revoked = payload.get("revoked") is True or policy.get("revoked") is True
    authorized = bool(payload.get("authorized") or policy.get("current_install_authorized") is True)
    if denied_by_policy:
        raw_reasons.append("policy_denied")
    if revoked:
        raw_reasons.append("revoked")
    reasons = sorted({_normalize_denial_code(str(reason)) for reason in raw_reasons if str(reason).strip()})
    if not authorized and not reasons:
        reasons = ["policy_denied"]
    status = "authorized" if authorized else ("unavailable" if "service_unavailable" in reasons else "denied")
    result = {
        "schema_version": 1,
        "pack_ref": private_pack_ref(pack_id or str(payload.get("pack_id") or "")),
        "authorized": authorized,
        "status": status,
        "denial_reasons": reasons,
        "plan": _safe_string(payload.get("plan") or policy.get("plan") or ""),
        "scope": _safe_string(payload.get("scope") or policy.get("scope") or ""),
        "organization": _safe_dict(payload.get("organization")),
        "team": _safe_dict(payload.get("team")),
        "request_id": _safe_string(payload.get("request_id") or ""),
        "privacy": {
            "pack_id_included": False,
            "pack_name_included": False,
            "skill_names_included": False,
            "skill_bodies_included": False,
            "archive_urls_included": False,
            "tokens_included": False,
            "proofs_included": False,
            "private_keys_included": False,
            "local_paths_included": False,
        },
    }
    _assert_access_check_safe(result)
    return result


def _normalize_denial_code(value: str) -> str:
    normalized = value.strip().lower().replace("-", "_").replace(" ", "_")
    normalized = PRIVATE_PACK_DENIAL_ALIASES.get(normalized, normalized)
    if normalized in PRIVATE_PACK_DENIAL_CODES:
        return normalized
    return "policy_denied"


def _safe_string(value: object) -> str:
    return redact_sensitive_text(value).strip()


def _safe_dict(value: object) -> dict[str, str]:
    if not isinstance(value, dict):
        return {}
    allowed = {}
    for key in ("org_id", "team_id", "role", "status", "namespace", "scope"):
        if key in value:
            allowed[key] = _safe_string(value.get(key))
    return allowed


def _assert_access_check_safe(payload: dict[str, Any]) -> None:
    serialized = json.dumps(payload, ensure_ascii=False).lower()
    forbidden = ["authorization", "bearer ", "license_token", "device_private_key", "x-uls-proof", '"archive_url":', '"download_url":', "skill.md"]
    for marker in forbidden:
        if marker in serialized:
            raise PrivatePackError(f"Private pack access diagnostic contains forbidden marker: {marker}")
