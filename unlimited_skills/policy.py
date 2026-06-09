from __future__ import annotations

import hashlib
import json
import time
import urllib.parse
from pathlib import Path
from typing import Any

from .registration import redact_sensitive_text, unlimited_skills_home, write_private_json
from .signatures import ManifestSignatureError, canonical_manifest_bytes, signature_envelope, verify_manifest_signature

POLICY_FILE = "enterprise-skill-lock-policy.json"
AUDIT_LOG = "refusals.jsonl"
VALID_MODES = {"audit", "enforce"}


class PolicyError(RuntimeError):
    """Raised when Enterprise Skill Lock policy is invalid or blocks an action."""


def now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def policy_dir(home: Path | None = None) -> Path:
    return (home or unlimited_skills_home()) / "policy"


def policy_path(home: Path | None = None) -> Path:
    return policy_dir(home) / POLICY_FILE


def audit_log_path(home: Path | None = None) -> Path:
    return policy_dir(home) / AUDIT_LOG


def normalize_origin(value: str) -> str:
    parsed = urllib.parse.urlsplit(str(value or "").strip())
    if not parsed.scheme or not parsed.netloc:
        return str(value or "").rstrip("/")
    return f"{parsed.scheme.lower()}://{parsed.netloc.lower()}"


def canonical_policy_sha256(policy: dict[str, Any]) -> str:
    unsigned = {key: value for key, value in policy.items() if key not in {"policy_sha256", "manifest_signature", "signature_envelope"}}
    return hashlib.sha256(json.dumps(unsigned, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def default_policy() -> dict[str, Any]:
    return {
        "schema_version": 1,
        "installed": False,
        "mode": "disabled",
        "locked": False,
    }


def load_policy(home: Path | None = None) -> dict[str, Any]:
    path = policy_path(home)
    if not path.is_file():
        return default_policy()
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PolicyError("Cannot read installed Enterprise Skill Lock policy.") from exc
    if not isinstance(data, dict):
        raise PolicyError("Installed Enterprise Skill Lock policy must be a JSON object.")
    return normalize_policy(data, installed=True)


def normalize_policy(data: dict[str, Any], *, installed: bool = False) -> dict[str, Any]:
    mode = str(data.get("mode") or "audit").lower()
    if mode not in VALID_MODES:
        raise PolicyError("Enterprise Skill Lock policy mode must be audit or enforce.")
    policy = dict(data)
    policy["schema_version"] = int(policy.get("schema_version") or 1)
    if policy["schema_version"] != 1:
        raise PolicyError("Unsupported Enterprise Skill Lock policy schema_version.")
    policy["policy_id"] = str(policy.get("policy_id") or "")
    if not policy["policy_id"]:
        raise PolicyError("Enterprise Skill Lock policy must include policy_id.")
    policy["mode"] = mode
    policy["allowed_registries"] = [normalize_origin(item) for item in policy.get("allowed_registries", []) if str(item)]
    policy["allowed_release_channels"] = [str(item) for item in policy.get("allowed_release_channels", []) if str(item)]
    policy["required_manifest_signatures"] = bool(policy.get("required_manifest_signatures", True))
    policy["allowed_key_ids"] = [str(item) for item in policy.get("allowed_key_ids", []) if str(item)]
    policy["allowed_key_scopes"] = [str(item) for item in policy.get("allowed_key_scopes", []) if str(item)]
    policy["allowed_local_roots"] = [str(Path(str(item)).expanduser().resolve()) for item in policy.get("allowed_local_roots", []) if str(item)]
    community = policy.get("community") if isinstance(policy.get("community"), dict) else {}
    policy["community"] = {
        "install_allowed": bool(community.get("install_allowed", True)),
        "submit_allowed": bool(community.get("submit_allowed", True)),
    }
    hub = policy.get("hub") if isinstance(policy.get("hub"), dict) else {}
    policy["hub"] = {
        "remote_required": bool(hub.get("remote_required", False)),
        "local_fallback_allowed": bool(hub.get("local_fallback_allowed", True)),
        "unsigned_local_allowlist_allowed": bool(hub.get("unsigned_local_allowlist_allowed", True)),
        "max_client_instances_override_allowed": bool(hub.get("max_client_instances_override_allowed", False)),
    }
    audit = policy.get("audit") if isinstance(policy.get("audit"), dict) else {}
    policy["audit"] = {"log_refusals": bool(audit.get("log_refusals", True))}
    policy["installed"] = installed
    policy["locked"] = True
    policy["policy_sha256_actual"] = canonical_policy_sha256(policy)
    return policy


def verify_policy_payload(data: dict[str, Any]) -> dict[str, Any]:
    policy = normalize_policy(data)
    signed = bool(signature_envelope(data))
    expected_hash = str(data.get("policy_sha256") or "")
    hash_verified = bool(expected_hash and expected_hash.lower() == canonical_policy_sha256(data).lower())
    signature_verification: dict[str, Any] = {"verified": False, "reason": "signature_missing"}
    if signed:
        try:
            signature_verification = verify_manifest_signature(
                data,
                purpose="Enterprise Skill Lock policy",
                required=True,
                scope="enterprise-policy",
            )
        except ManifestSignatureError as exc:
            raise PolicyError(str(exc)) from exc
    if not signed and not hash_verified:
        raise PolicyError("Enterprise Skill Lock policy must be signed or include a valid policy_sha256 hash pin.")
    return {
        "schema_version": 1,
        "policy_id": policy["policy_id"],
        "mode": policy["mode"],
        "valid": True,
        "signed": signed,
        "hash_pinned": hash_verified,
        "policy_sha256": canonical_policy_sha256(data),
        "signature_verification": signature_verification,
        "summary": policy_summary(policy),
    }


def read_policy_file(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PolicyError(f"Cannot read Enterprise Skill Lock policy: {path}") from exc
    if not isinstance(data, dict):
        raise PolicyError("Enterprise Skill Lock policy file must contain a JSON object.")
    return data


def install_policy(source: Path, *, home: Path | None = None) -> dict[str, Any]:
    data = read_policy_file(source)
    return install_policy_payload(data, home=home, source=str(source))


def install_policy_payload(data: dict[str, Any], *, home: Path | None = None, source: str = "payload") -> dict[str, Any]:
    verification = verify_policy_payload(data)
    policy = normalize_policy(data, installed=True)
    policy["installed_at"] = now_iso()
    policy["source"] = source
    path = write_private_json(policy_path(home), policy)
    return {**verification, "installed": True, "path": str(path)}


def remove_policy(*, yes: bool = False, home: Path | None = None) -> dict[str, Any]:
    if not yes:
        raise PolicyError("Removing Enterprise Skill Lock policy requires --yes.")
    path = policy_path(home)
    existed = path.exists()
    path.unlink(missing_ok=True)
    return {"schema_version": 1, "removed": existed, "path": str(path)}


def policy_summary(policy: dict[str, Any] | None = None) -> dict[str, Any]:
    policy = policy or load_policy()
    if not policy.get("installed") and not policy.get("locked"):
        return default_policy()
    return {
        "schema_version": 1,
        "installed": bool(policy.get("installed")),
        "locked": bool(policy.get("locked")),
        "policy_id": str(policy.get("policy_id") or ""),
        "mode": str(policy.get("mode") or "disabled"),
        "allowed_registries": list(policy.get("allowed_registries", [])),
        "allowed_release_channels": list(policy.get("allowed_release_channels", [])),
        "required_manifest_signatures": bool(policy.get("required_manifest_signatures", False)),
        "allowed_key_ids": list(policy.get("allowed_key_ids", [])),
        "allowed_key_scopes": list(policy.get("allowed_key_scopes", [])),
        "allowed_local_roots": list(policy.get("allowed_local_roots", [])),
        "community": dict(policy.get("community", {})),
        "hub": dict(policy.get("hub", {})),
        "audit": dict(policy.get("audit", {})),
        "policy_sha256": str(policy.get("policy_sha256_actual") or canonical_policy_sha256(policy)),
    }


def explain_policy(policy: dict[str, Any] | None = None) -> str:
    summary = policy_summary(policy)
    if not summary.get("locked"):
        return "Enterprise Skill Lock is not installed. Community Core behavior is unchanged."
    mode = summary["mode"]
    lines = [
        f"Enterprise Skill Lock is installed in {mode} mode.",
        "Allowed registries: " + (", ".join(summary["allowed_registries"]) if summary["allowed_registries"] else "(any)"),
        "Allowed release channels: " + (", ".join(summary["allowed_release_channels"]) if summary["allowed_release_channels"] else "(any)"),
        "Allowed key ids: " + (", ".join(summary["allowed_key_ids"]) if summary["allowed_key_ids"] else "(any trusted key)"),
        "Community install: " + ("allowed" if summary["community"].get("install_allowed") else "denied"),
        "Community submit: " + ("allowed" if summary["community"].get("submit_allowed") else "denied"),
        "Remote local fallback: " + ("allowed" if summary["hub"].get("local_fallback_allowed") else "denied"),
        "Unsigned local allowlists: " + ("allowed" if summary["hub"].get("unsigned_local_allowlist_allowed") else "denied"),
    ]
    return "\n".join(lines)


def write_policy_audit(event: dict[str, Any], *, home: Path | None = None) -> Path:
    path = audit_log_path(home)
    path.parent.mkdir(parents=True, exist_ok=True)
    safe_event = json.loads(redact_sensitive_text(json.dumps(event, ensure_ascii=False, sort_keys=True)))
    safe_event["ts"] = now_iso()
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(safe_event, ensure_ascii=False, sort_keys=True) + "\n")
    return path
