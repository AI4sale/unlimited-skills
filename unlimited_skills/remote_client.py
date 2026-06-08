from __future__ import annotations

import json
import os
import platform
import shutil
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
import importlib.metadata
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from . import __version__
from .hub import load_remote_runtime_config
from .registration import redact_sensitive_text


DEFAULT_CONTEXT_BUDGET = {"max_skills": 2, "max_chars": 12000}
TOOL_NAMES = ("git", "python", "python3", "node", "docker", "sh", "bash", "powershell", "pwsh")


class RemoteHubError(RuntimeError):
    """Raised when the remote hub returns a clear application or HTTP error."""


class RemoteHubUnavailable(RemoteHubError):
    """Raised when the remote hub cannot be reached."""


@dataclass(frozen=True)
class RemoteHubConfig:
    url: str
    token: str
    fallback_mode: str = "local_allowed"
    timeout_seconds: float = 10.0
    token_storage: str = "file"
    token_env: str = ""

    @property
    def configured(self) -> bool:
        return bool(self.url)


def redact_url(value: str) -> str:
    parsed = urllib.parse.urlsplit(str(value))
    query: list[tuple[str, str]] = []
    for key, item_value in urllib.parse.parse_qsl(parsed.query, keep_blank_values=True):
        if any(token in key.lower() for token in ("token", "secret", "key", "password")):
            query.append((key, "[redacted]"))
        else:
            query.append((key, item_value))
    netloc = parsed.hostname or ""
    if parsed.port:
        netloc = f"{netloc}:{parsed.port}"
    redacted = urllib.parse.urlunsplit((parsed.scheme, netloc, parsed.path, urllib.parse.urlencode(query), ""))
    return redact_sensitive_text(redacted)


def config_from_file(home: Path | None = None) -> RemoteHubConfig:
    raw = load_remote_runtime_config(home)
    token_storage = str(raw.get("token_storage") or "file")
    token_env = str(raw.get("token_env") or "")
    token = ""
    if token_storage == "env":
        token = os.environ.get(token_env, "") if token_env else ""
    else:
        token = str(raw.get("token") or "")
    return RemoteHubConfig(
        url=str(raw.get("url") or "").rstrip("/"),
        token=token,
        fallback_mode=str(raw.get("fallback_mode") or "local_allowed"),
        timeout_seconds=float(raw.get("timeout_seconds") or 10),
        token_storage=token_storage,
        token_env=token_env,
    )


def parse_json_response(raw: bytes) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        data = json.loads(raw.decode("utf-8"))
    except json.JSONDecodeError as exc:
        raise RemoteHubError("Remote hub returned invalid JSON.") from exc
    if not isinstance(data, dict):
        raise RemoteHubError("Remote hub returned a non-object JSON response.")
    return data


def error_message_from_payload(payload: dict[str, Any], fallback: str) -> str:
    error = payload.get("error")
    if isinstance(error, dict):
        code = str(error.get("code") or "remote_hub_error")
        message = str(error.get("message") or fallback)
        return redact_sensitive_text(f"Remote hub error {code}: {message}")
    detail = payload.get("detail")
    if isinstance(detail, dict):
        nested = detail.get("error")
        if isinstance(nested, dict):
            code = str(nested.get("code") or "remote_hub_error")
            message = str(nested.get("message") or fallback)
            return redact_sensitive_text(f"Remote hub error {code}: {message}")
        if detail.get("code") or detail.get("message"):
            return redact_sensitive_text(f"Remote hub error {detail.get('code') or 'remote_hub_error'}: {detail.get('message') or fallback}")
    return redact_sensitive_text(fallback)


class RemoteHubClient:
    def __init__(self, config: RemoteHubConfig | None = None) -> None:
        self.config = config or config_from_file()
        if not self.config.configured:
            raise RemoteHubUnavailable("Remote hub is not configured.")
        if not self.config.token:
            source = f"env var {self.config.token_env}" if self.config.token_storage == "env" else "remote config"
            raise RemoteHubError(f"Remote hub token is missing from {source}.")

    def get_status(self) -> dict[str, Any]:
        return self._request("GET", "/v1/hub/status")

    def search(self, query: str, limit: int = 8, mode: str = "hybrid", collection: str = "") -> dict[str, Any]:
        payload: dict[str, Any] = {
            "schema_version": 1,
            "query": query,
            "limit": limit,
            "include_local_install_plan": True,
        }
        if mode:
            payload["mode"] = mode
        if collection:
            payload["collection"] = collection
        return self._request("POST", "/v1/skills/search", payload)

    def resolve(
        self,
        query: str,
        context_budget: dict[str, int] | None = None,
        client_capabilities: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        payload = {
            "schema_version": 1,
            "query": query,
            "context_budget": context_budget or dict(DEFAULT_CONTEXT_BUDGET),
            "client_capabilities": client_capabilities or collect_client_capabilities(),
        }
        return self._request("POST", "/v1/skills/resolve", payload)

    def view(self, name: str) -> dict[str, Any]:
        encoded = urllib.parse.quote(name, safe="")
        return self._request("GET", f"/v1/skills/{encoded}")

    def manifest(self, name: str) -> dict[str, Any]:
        encoded = urllib.parse.quote(name, safe="")
        return self._request("GET", f"/v1/skills/{encoded}/manifest")

    def record_use(self, skill_name: str, *, query: str = "", task: str = "") -> dict[str, Any]:
        return self._request("POST", "/v1/skills/use", {"schema_version": 1, "skill_name": skill_name, "query": query, "task": task})

    def record_feedback(self, skill_name: str, *, query: str = "", verdict: str = "", notes: str = "") -> dict[str, Any]:
        return self._request(
            "POST",
            "/v1/skills/feedback",
            {"schema_version": 1, "skill_name": skill_name, "query": query, "verdict": verdict, "notes": notes},
        )

    def _request(self, method: str, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        url = self.config.url.rstrip("/") + path
        body = json.dumps(payload or {}, ensure_ascii=False).encode("utf-8") if payload is not None else None
        headers = {
            "Accept": "application/json",
            "User-Agent": f"unlimited-skills/{__version__}",
            "Authorization": f"Bearer {self.config.token}",
            "X-ULS-Hub-Token": self.config.token,
        }
        if body is not None:
            headers["Content-Type"] = "application/json"
        request = urllib.request.Request(url, data=body, headers=headers, method=method)
        try:
            with urllib.request.urlopen(request, timeout=self.config.timeout_seconds) as response:
                return parse_json_response(response.read())
        except urllib.error.HTTPError as exc:
            raw = exc.read() if exc.fp else b""
            try:
                parsed = parse_json_response(raw)
            except RemoteHubError:
                parsed = {}
            fallback = f"Remote hub returned HTTP {exc.code} for {method} {redact_url(url)}."
            raise RemoteHubError(error_message_from_payload(parsed, fallback)) from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            reason = getattr(exc, "reason", exc)
            raise RemoteHubUnavailable(f"Remote hub unavailable at {redact_url(url)}: {redact_sensitive_text(reason)}") from exc


def read_capabilities_json(path: str | Path) -> dict[str, Any]:
    data = json.loads(Path(path).expanduser().read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise RemoteHubError("Capabilities JSON must contain an object.")
    return data


def collect_client_capabilities(agent: str = "unknown", extra_path: str | Path | None = None) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "schema_version": 1,
        "client_id": "",
        "agent": agent or "unknown",
        "os": platform.system().lower(),
        "arch": platform.machine(),
        "python": platform.python_version(),
        "node": node_version(),
        "available_tools": available_tools(),
        "installed_packages": {"python": installed_python_packages(), "npm": []},
        "env_vars_present": sorted(name for name in os.environ if name.startswith(("CODEX", "CLAUDE", "HERMES", "OPENCLAW", "ULS_", "UNLIMITED_SKILLS"))),
    }
    if extra_path:
        extra = read_capabilities_json(extra_path)
        payload.update(extra)
        payload["env_vars_present"] = sorted(str(name) for name in payload.get("env_vars_present", []) if isinstance(name, str))
    return payload


def available_tools() -> list[str]:
    found: list[str] = []
    for name in TOOL_NAMES:
        if shutil.which(name):
            found.append(name)
    return sorted(set(found))


def node_version() -> str:
    node = shutil.which("node")
    if not node:
        return ""
    try:
        result = subprocess.run([node, "--version"], capture_output=True, text=True, timeout=2, check=False)
    except (OSError, subprocess.SubprocessError):
        return ""
    return result.stdout.strip()[:80]


def installed_python_packages() -> list[str]:
    try:
        names = [dist.metadata.get("Name", "") for dist in importlib.metadata.distributions()]
    except Exception:
        return []
    return sorted({name for name in names if name})[:400]
