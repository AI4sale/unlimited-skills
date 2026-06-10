from __future__ import annotations

import json
import os
import platform
import re
import tempfile
import time
import zipfile
from pathlib import Path
from typing import Any

from . import __version__
from .doctor import build_doctor_report
from .hub import active_hub_token_count, cached_allowlist_summary, load_hub_config, load_remote_config
from .policy import load_policy, policy_summary
from .policy_sync import managed_policy_status
from .private_pack_diagnostics import assert_private_pack_diagnostics_safe, private_pack_local_summary, private_pack_setup_summary
from .registration import DEFAULT_SERVICE_URL, RegistrationError, RegistrationState, load_registration, redacted_status, redact_sensitive_text, unlimited_skills_home
from .service_diagnostics import load_service_config, service_health_snapshot


SUPPORT_SCHEMA_VERSION = 1
DEFAULT_BUNDLE_PREFIX = "unlimited-skills-support-bundle"
FORBIDDEN_KEY_PARTS = (
    "authorization",
    "body",
    "content",
    "device_private_key",
    "env",
    "license_token",
    "password",
    "private_key",
    "prompt",
    "proof",
    "query",
    "raw",
    "secret",
    "skill_body",
    "token",
)
PATH_PATTERN = re.compile(
    r"(?i)(?:[a-z]:\\[^\s\"']+|\\\\[^\s\"']+|/(?:Users|home|tmp|var|opt|srv|mnt)/[^\s\"']+)"
)


def now_stamp() -> str:
    return time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())


def default_bundle_path(cwd: Path | None = None) -> Path:
    return (cwd or Path.cwd()) / f"{DEFAULT_BUNDLE_PREFIX}-{now_stamp()}.zip"


def _collection_for(root: Path, skill_file: Path) -> str:
    try:
        rel = skill_file.relative_to(root)
    except ValueError:
        return "unknown"
    parts = rel.parts
    if len(parts) > 2 and parts[0] == "registry":
        return parts[1]
    if len(parts) > 2 and parts[0] == "local":
        return "local"
    return parts[0] if parts else "unknown"


def _skill_inventory(root: Path, *, include_paths: bool) -> dict[str, Any]:
    collections: dict[str, int] = {}
    physical_count = 0
    if root.is_dir():
        for skill_file in root.rglob("SKILL.md"):
            rel_parts = skill_file.relative_to(root).parts
            if ".rollbacks" in rel_parts or "duplicates" in rel_parts:
                continue
            physical_count += 1
            collection = _collection_for(root, skill_file)
            collections[collection] = collections.get(collection, 0) + 1
    index_path = root / ".unlimited-skills-index.json"
    index_record_count = 0
    index_readable = False
    if index_path.is_file():
        try:
            records = json.loads(index_path.read_text(encoding="utf-8-sig"))
            if isinstance(records, list):
                index_record_count = len(records)
                index_readable = True
        except (OSError, json.JSONDecodeError):
            index_readable = False
    payload: dict[str, Any] = {
        "root_present": root.is_dir(),
        "physical_skill_files": physical_count,
        "collection_count": len(collections),
        "collections": collections,
        "index_present": index_path.is_file(),
        "index_readable": index_readable,
        "index_record_count": index_record_count,
        "vector_sidecar_present": (root / ".unlimited-skills-vector.json").is_file(),
        "chroma_present": (root / ".chroma-skills").is_dir(),
        "skill_names_included": False,
        "skill_bodies_included": False,
    }
    if include_paths:
        payload["root"] = str(root)
        payload["index_path"] = str(index_path)
    return payload


def _registration_status(home: Path) -> dict[str, Any]:
    try:
        return redacted_status(load_registration(home))
    except RegistrationError:
        return {"registered": False, "plan": "community-core", "server_url": "", "telemetry": "off"}


def _service_status(home: Path) -> dict[str, Any]:
    try:
        status = service_health_snapshot(refresh=False, home=home)
    except Exception as exc:  # noqa: BLE001 - support diagnostics must stay non-fatal.
        return {"ok": False, "error": redact_sensitive_text(str(exc))}
    return status


def _hub_status(home: Path) -> dict[str, Any]:
    return {
        "config": load_hub_config(home),
        "remote": load_remote_config(home),
        "allowlist": cached_allowlist_summary(home),
        "active_token_count": active_hub_token_count(home),
    }


def _enterprise_status(home: Path) -> dict[str, Any]:
    return {
        "policy": policy_summary(load_policy(home)),
        "managed_policy": managed_policy_status(home=home),
    }


def _private_pack_status(root: Path, home: Path, *, include_pack_ids: bool) -> dict[str, Any]:
    try:
        state = load_registration(home)
    except RegistrationError:
        state = RegistrationState(server_url=DEFAULT_SERVICE_URL)
    service_url = state.server_url if state else ""
    setup = private_pack_setup_summary(root, state=state, service_url=service_url)
    return {
        "local": private_pack_local_summary(root, include_pack_ids=include_pack_ids),
        "setup": {
            "status": setup["status"],
            "checks": setup["checks"],
            "recommendation_count": len(setup.get("recommendations") or []),
        },
        "pack_refs_included": include_pack_ids,
        "pack_names_included": False,
        "skill_names_included": False,
        "skill_bodies_included": False,
        "archive_urls_included": False,
        "local_paths_included": False,
    }


def _doctor_status(root: Path) -> dict[str, Any]:
    try:
        return build_doctor_report(root)
    except Exception as exc:  # noqa: BLE001 - support diagnostics must stay non-fatal.
        return {"ok": False, "error": redact_sensitive_text(str(exc))}


def _redact_path_markers(value: str, *, root: Path, home: Path) -> str:
    text = value
    replacements = {
        str(root): "[library-root]",
        str(home): "[unlimited-skills-home]",
        str(Path.home()): "[home]",
    }
    for raw, marker in sorted(replacements.items(), key=lambda item: len(item[0]), reverse=True):
        if raw:
            text = text.replace(raw, marker)
    return PATH_PATTERN.sub("[path]", text)


def sanitize_support_payload(value: Any, *, root: Path, home: Path, include_paths: bool = False) -> Any:
    if isinstance(value, dict):
        result: dict[str, Any] = {}
        for key, item in value.items():
            lowered = str(key).lower()
            if any(part in lowered for part in FORBIDDEN_KEY_PARTS):
                if lowered.endswith("_included") or lowered in {"proof_required", "tokens_redacted", "private_keys_redacted"}:
                    result[key] = bool(item)
                else:
                    result[key] = "present" if bool(item) else ""
                continue
            result[key] = sanitize_support_payload(item, root=root, home=home, include_paths=include_paths)
        return result
    if isinstance(value, list):
        return [sanitize_support_payload(item, root=root, home=home, include_paths=include_paths) for item in value]
    if isinstance(value, tuple):
        return [sanitize_support_payload(item, root=root, home=home, include_paths=include_paths) for item in value]
    if isinstance(value, str):
        text = redact_sensitive_text(value)
        if not include_paths:
            text = _redact_path_markers(text, root=root, home=home)
        return text
    return value


def assert_support_bundle_safe(payload: dict[str, Any]) -> None:
    private_pack_payload = payload.get("private_packs")
    diagnostics = payload.get("diagnostics")
    if private_pack_payload is None and isinstance(diagnostics, dict):
        private_pack_payload = diagnostics.get("private_packs")
    if isinstance(private_pack_payload, dict):
        assert_private_pack_diagnostics_safe(private_pack_payload)
    serialized = json.dumps(payload, ensure_ascii=False).lower()
    forbidden = (
        "authorization: bearer",
        "device_private_key",
        "secret_",
        "sk-",
        "skill.md",
        "x-uls-proof",
        "x-uls-hub-token",
    )
    for marker in forbidden:
        if marker in serialized:
            raise RuntimeError(f"Support bundle payload contains forbidden marker: {marker}")


def build_support_diagnostics(root: Path, *, include_paths: bool = False, include_private_pack_refs: bool = False) -> dict[str, Any]:
    root = root.expanduser()
    home = unlimited_skills_home()
    payload = {
        "schema_version": SUPPORT_SCHEMA_VERSION,
        "client": {"name": "unlimited-skills", "version": __version__},
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "privacy": {
            "redacted": True,
            "include_paths": include_paths,
            "skill_bodies_included": False,
            "skill_names_included": False,
            "prompts_included": False,
            "search_queries_included": False,
            "environment_values_included": False,
            "tokens_included": False,
            "private_keys_included": False,
        },
        "system": {
            "platform": platform.system(),
            "platform_release": platform.release(),
            "python_version": platform.python_version(),
            "cwd_included": include_paths,
            "environment_variable_names": sorted(
                name
                for name in os.environ
                if name.startswith(("UNLIMITED_SKILLS_", "CODEX_", "CLAUDE_", "HERMES_", "OPENCLAW_"))
            ),
        },
        "library": _skill_inventory(root, include_paths=include_paths),
        "registration": _registration_status(home),
        "service": _service_status(home),
        "hub": _hub_status(home),
        "enterprise": _enterprise_status(home),
        "private_packs": _private_pack_status(root, home, include_pack_ids=include_private_pack_refs),
        "doctor": _doctor_status(root),
    }
    sanitized = sanitize_support_payload(payload, root=root, home=home, include_paths=include_paths)
    assert_support_bundle_safe(sanitized)
    return sanitized


def build_bundle_report(
    root: Path,
    *,
    out: Path | None = None,
    dry_run: bool = False,
    include_paths: bool = False,
    include_private_pack_refs: bool = False,
    cwd: Path | None = None,
) -> dict[str, Any]:
    diagnostics = build_support_diagnostics(root, include_paths=include_paths, include_private_pack_refs=include_private_pack_refs)
    resolved_out = (out.expanduser() if out else default_bundle_path(cwd)).resolve()
    manifest = {
        "schema_version": SUPPORT_SCHEMA_VERSION,
        "client": diagnostics["client"],
        "bundle_type": "support-diagnostic-bundle",
        "created_at": diagnostics["created_at"],
        "dry_run": dry_run,
        "would_write": str(resolved_out),
        "wrote_bundle": False,
        "bundle_path": "",
        "files": ["manifest.json", "diagnostics.json", "README.txt"],
        "privacy": diagnostics["privacy"],
        "diagnostics_summary": {
            "registered": bool(diagnostics.get("registration", {}).get("registered")),
            "library_present": bool(diagnostics.get("library", {}).get("root_present")),
            "physical_skill_files": int(diagnostics.get("library", {}).get("physical_skill_files") or 0),
            "index_present": bool(diagnostics.get("library", {}).get("index_present")),
            "private_pack_installed_count": int(diagnostics.get("private_packs", {}).get("local", {}).get("installed_count") or 0),
            "private_pack_revoked_count": int(diagnostics.get("private_packs", {}).get("local", {}).get("revoked_count") or 0),
            "private_pack_stale_count": int(diagnostics.get("private_packs", {}).get("local", {}).get("stale_count") or 0),
        },
    }
    report = {"manifest": manifest, "diagnostics": diagnostics}
    assert_support_bundle_safe(report)
    if not dry_run:
        resolved_out.parent.mkdir(parents=True, exist_ok=True)
        _write_bundle(resolved_out, report)
        manifest["wrote_bundle"] = True
        manifest["bundle_path"] = str(resolved_out) if include_paths else "[bundle-path]"
        assert_support_bundle_safe(report)
    return report


def _write_bundle(path: Path, report: dict[str, Any]) -> None:
    readme = (
        "Unlimited Skills support diagnostic bundle\n\n"
        "This archive contains redacted metadata only. It must not contain skill bodies, prompts, "
        "search queries, environment values, tokens, device private keys, or raw proofs.\n"
    )
    with tempfile.TemporaryDirectory(prefix="uls-support-bundle-") as temp_dir:
        temp_path = Path(temp_dir) / path.name
        with zipfile.ZipFile(temp_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("manifest.json", json.dumps(report["manifest"], ensure_ascii=False, indent=2, sort_keys=True) + "\n")
            archive.writestr("diagnostics.json", json.dumps(report["diagnostics"], ensure_ascii=False, indent=2, sort_keys=True) + "\n")
            archive.writestr("README.txt", readme)
        temp_path.replace(path)


def format_bundle_text(report: dict[str, Any]) -> str:
    manifest = report["manifest"]
    summary = manifest["diagnostics_summary"]
    lines = [
        "Unlimited Skills support bundle",
        "Dry run: " + ("yes" if manifest["dry_run"] else "no"),
        "Wrote bundle: " + ("yes" if manifest["wrote_bundle"] else "no"),
        f"Output: {manifest['bundle_path'] or manifest['would_write']}",
        "Privacy: redacted metadata only",
        f"Registered: {'yes' if summary['registered'] else 'no'}",
        f"Library present: {'yes' if summary['library_present'] else 'no'}",
        f"Physical skill files counted: {summary['physical_skill_files']}",
        f"Index present: {'yes' if summary['index_present'] else 'no'}",
        f"Private packs installed: {summary['private_pack_installed_count']}",
    ]
    return "\n".join(lines)
