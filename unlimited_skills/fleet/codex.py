"""Codex Enterprise Fleet adapter.

The adapter uses an isolated ``CODEX_HOME`` for hooks and state plus a
dedicated runtime workspace whose ``.agents/skills`` directory is wholly
adapter-owned.  A real Codex ``SessionStart`` hook must observe the exact home,
workspace, activation, and skills tree before Fleet accepts runtime evidence.
"""

from __future__ import annotations

import hashlib
import json
import os
import shlex
import subprocess
import sys
from pathlib import Path
from typing import Any, Mapping

from ..frontmatter import load_frontmatter
from ..private_packs import PrivatePackClient
from ..registration import RegistrationState
from .adapter import ManagedFleetAdapterError
from .claude_code import _atomic_write_json
from .managed_runtime import (
    ManagedRuntimeFleetAdapter,
    ManagedRuntimeFleetAdapterError,
    record_managed_runtime_observation,
)


CODEX_ADAPTER_ID = "codex"
CODEX_ADAPTER_VERSION = "codex-fleet/1.0.0"
MAX_CODEX_HOOK_INPUT_BYTES = 64 * 1024
_ALLOWED_SESSION_SOURCES = {"startup", "resume"}
_CODEX_HOME_ENV = "CODEX_HOME"
_FLEET_MANAGED_ROOT_ENV = "UNLIMITED_SKILLS_FLEET_MANAGED_ROOT"


class CodexFleetAdapterError(ManagedRuntimeFleetAdapterError):
    """Raised when a Codex runtime cannot prove safe managed state."""


def _path_digest(path: Path) -> str:
    return "sha256:" + hashlib.sha256(
        str(path.resolve()).encode("utf-8")
    ).hexdigest()


def managed_codex_home(managed_root: Path) -> Path:
    return (
        Path(managed_root).expanduser().resolve()
        / "runtime"
        / "codex-home"
    )


def managed_codex_workspace(managed_root: Path) -> Path:
    return (
        Path(managed_root).expanduser().resolve()
        / "runtime"
        / "workspace"
    )


def _shell_join(arguments: list[str]) -> str:
    if os.name == "nt":
        return subprocess.list2cmdline(arguments)
    return shlex.join(arguments)


def _runtime_hook_command(root: Path) -> str:
    return _shell_join(
        [
            sys.executable,
            "-m",
            "unlimited_skills",
            "fleet",
            "codex-runtime-start",
            "--managed-root",
            str(root),
            "--json",
        ]
    )


def _is_fleet_hook_entry(entry: object) -> bool:
    if not isinstance(entry, dict):
        return False
    for hook in entry.get("hooks") or []:
        if not isinstance(hook, dict):
            continue
        command = str(hook.get("command") or "")
        if (
            "unlimited_skills" in command
            and "fleet" in command
            and "codex-runtime-start" in command
        ):
            return True
    return False


def _provision_codex_runtime_hook(root: Path) -> None:
    codex_home = managed_codex_home(root)
    codex_home.mkdir(parents=True, exist_ok=True)
    if codex_home.is_symlink():
        raise CodexFleetAdapterError(
            "runtime_codex_home_symlink_forbidden"
        )
    hooks_path = codex_home / "hooks.json"
    if hooks_path.is_file():
        try:
            hooks_document = json.loads(
                hooks_path.read_text(encoding="utf-8")
            )
        except (
            OSError,
            UnicodeDecodeError,
            json.JSONDecodeError,
        ) as exc:
            raise CodexFleetAdapterError(
                "runtime_hooks_invalid"
            ) from exc
    else:
        hooks_document = {}
    if not isinstance(hooks_document, dict):
        raise CodexFleetAdapterError("runtime_hooks_invalid")
    hooks = hooks_document.setdefault("hooks", {})
    if not isinstance(hooks, dict):
        raise CodexFleetAdapterError("runtime_hooks_invalid")
    entries = hooks.get("SessionStart")
    if not isinstance(entries, list):
        entries = []
    entries = [
        entry for entry in entries if not _is_fleet_hook_entry(entry)
    ]
    entries.append(
        {
            "matcher": "startup|resume",
            "hooks": [
                {
                    "type": "command",
                    "command": _runtime_hook_command(root),
                    "timeout": 15,
                    "statusMessage": (
                        "Verifying Unlimited Skills Fleet activation"
                    ),
                }
            ],
        }
    )
    hooks["SessionStart"] = entries
    _atomic_write_json(hooks_path, hooks_document)


def _assert_codex_runtime_hook(root: Path) -> None:
    hooks_path = managed_codex_home(root) / "hooks.json"
    try:
        document = json.loads(hooks_path.read_text(encoding="utf-8"))
    except (
        OSError,
        UnicodeDecodeError,
        json.JSONDecodeError,
    ) as exc:
        raise CodexFleetAdapterError(
            "runtime_hook_not_provisioned"
        ) from exc
    hooks = document.get("hooks") if isinstance(document, dict) else None
    entries = hooks.get("SessionStart") if isinstance(hooks, dict) else None
    expected = _runtime_hook_command(root)
    if not isinstance(entries, list) or not any(
        isinstance(entry, dict)
        and entry.get("matcher") == "startup|resume"
        and any(
            isinstance(hook, dict)
            and hook.get("type") == "command"
            and hook.get("command") == expected
            for hook in entry.get("hooks") or []
        )
        for entry in entries
    ):
        raise CodexFleetAdapterError(
            "runtime_hook_not_provisioned"
        )


def parse_codex_session_start_payload(raw: bytes) -> dict[str, Any]:
    if not raw or len(raw) > MAX_CODEX_HOOK_INPUT_BYTES:
        raise CodexFleetAdapterError("runtime_hook_input_invalid")
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CodexFleetAdapterError(
            "runtime_hook_input_invalid"
        ) from exc
    if not isinstance(value, dict):
        raise CodexFleetAdapterError("runtime_hook_input_invalid")
    return value


def record_codex_session_start(
    managed_root: Path,
    hook_payload: Mapping[str, Any],
    *,
    environment: Mapping[str, str] | None = None,
    process_id: int | None = None,
    parent_process_id: int | None = None,
    observed_at: str | None = None,
) -> dict[str, Any]:
    """Record privacy-safe evidence from a real Codex ``SessionStart``."""

    try:
        root = Path(managed_root).expanduser().resolve()
        marker_path = root / "managed-root.json"
        marker = json.loads(marker_path.read_text(encoding="utf-8"))
        if (
            not isinstance(marker, dict)
            or marker.get("adapter_id") != CODEX_ADAPTER_ID
            or marker.get("adapter_version") != CODEX_ADAPTER_VERSION
        ):
            raise CodexFleetAdapterError(
                "managed_root_marker_invalid"
            )
        binding = marker.get("runtime_binding")
        if not isinstance(binding, dict):
            raise CodexFleetAdapterError(
                "managed_root_marker_invalid"
            )
        runtime_environment = (
            environment if environment is not None else os.environ
        )
        configured_home = str(
            runtime_environment.get(_CODEX_HOME_ENV) or ""
        ).strip()
        if (
            not configured_home
            or _path_digest(
                Path(configured_home).expanduser().resolve()
            )
            != binding.get("codex_home_sha256")
        ):
            raise CodexFleetAdapterError(
                "runtime_codex_home_mismatch"
            )
        asserted_root = str(
            runtime_environment.get(_FLEET_MANAGED_ROOT_ENV) or ""
        ).strip()
        if asserted_root and (
            Path(asserted_root).expanduser().resolve() != root
        ):
            raise CodexFleetAdapterError(
                "runtime_managed_root_mismatch"
            )
        _assert_codex_runtime_hook(root)
        if hook_payload.get("hook_event_name") != "SessionStart":
            raise CodexFleetAdapterError(
                "runtime_hook_event_invalid"
            )
        source = str(hook_payload.get("source") or "")
        if source not in _ALLOWED_SESSION_SOURCES:
            return {
                "recorded": False,
                "reason": "runtime_source_not_new_generation",
                "source": source,
            }
        raw_cwd = str(hook_payload.get("cwd") or "").strip()
        if (
            not raw_cwd
            or "\x00" in raw_cwd
            or _path_digest(Path(raw_cwd).expanduser().resolve())
            != binding.get("workspace_sha256")
        ):
            raise CodexFleetAdapterError(
                "runtime_workspace_binding_mismatch"
            )
        session_id = str(hook_payload.get("session_id") or "")
        skills_root = (
            managed_codex_workspace(root) / ".agents" / "skills"
        )
        return record_managed_runtime_observation(
            managed_root=root,
            skills_root=skills_root,
            adapter_id=CODEX_ADAPTER_ID,
            adapter_version=CODEX_ADAPTER_VERSION,
            runtime_prefix="codex-session",
            runtime_token=session_id,
            expected_binding=binding,
            observed_at=observed_at,
            process_id=process_id,
            parent_process_id=parent_process_id,
            extra_marker={
                "codex_home_sha256": binding["codex_home_sha256"],
                "hook_event_name": "SessionStart",
                "source": source,
                "workspace_sha256": binding["workspace_sha256"],
            },
            error_type=CodexFleetAdapterError,
        )
    except ManagedFleetAdapterError as exc:
        if isinstance(exc, CodexFleetAdapterError):
            raise
        raise CodexFleetAdapterError(str(exc)) from exc
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CodexFleetAdapterError(
            "managed_root_marker_invalid"
        ) from exc


class CodexFleetAdapter(ManagedRuntimeFleetAdapter):
    """Real Codex adapter for one isolated home and workspace."""

    adapter_id = CODEX_ADAPTER_ID
    adapter_version = CODEX_ADAPTER_VERSION
    runtime_vendor = "codex"
    runtime_generation_prefix = "codex"
    error_type = CodexFleetAdapterError

    def __init__(
        self,
        *,
        registration: RegistrationState,
        managed_root: Path,
        pack_client: PrivatePackClient | None = None,
        user_skills_root: Path | None = None,
        timeout: float = 30.0,
    ) -> None:
        if not registration.registered:
            raise self.error_type(
                "fleet_registered_installation_required"
            )
        expanded_root = Path(managed_root).expanduser()
        if expanded_root.exists() and expanded_root.is_symlink():
            raise self.error_type("managed_root_symlink_forbidden")
        expanded_root.resolve().mkdir(parents=True, exist_ok=True)
        self.codex_home = managed_codex_home(expanded_root)
        self.workspace = managed_codex_workspace(expanded_root)
        self.codex_home.mkdir(parents=True, exist_ok=True)
        self.workspace.mkdir(parents=True, exist_ok=True)
        if self.codex_home.is_symlink() or self.workspace.is_symlink():
            raise self.error_type("runtime_path_symlink_forbidden")
        self.user_skills_root = Path(
            user_skills_root
            if user_skills_root is not None
            else Path.home() / ".agents" / "skills"
        ).expanduser()
        binding = {
            "codex_home_sha256": _path_digest(self.codex_home),
            "workspace_sha256": _path_digest(self.workspace),
        }
        super().__init__(
            registration=registration,
            managed_root=expanded_root,
            skills_root=self.workspace / ".agents" / "skills",
            runtime_binding=binding,
            pack_client=pack_client,
            timeout=timeout,
        )
        _provision_codex_runtime_hook(self.managed_root)

    def _assert_runtime_parent(self, *, create: bool) -> None:
        agents_root = self.workspace / ".agents"
        if agents_root.exists() and (
            agents_root.is_symlink() or not agents_root.is_dir()
        ):
            raise self.error_type("runtime_workspace_invalid")
        if create:
            agents_root.mkdir(parents=True, exist_ok=True)
        if agents_root.resolve() != self.skills_root.parent:
            raise self.error_type("runtime_workspace_invalid")

    def _unmanaged_skill_names(self) -> set[str]:
        root = self.user_skills_root
        if not root.is_dir():
            return set()
        names: set[str] = set()
        for current, directories, files in os.walk(
            root,
            topdown=True,
            followlinks=False,
        ):
            current_path = Path(current)
            filtered: list[str] = []
            for directory in directories:
                child = current_path / directory
                if child.is_symlink():
                    raise self.error_type(
                        "unmanaged_skill_symlink_unsupported"
                    )
                filtered.append(directory)
            directories[:] = filtered
            if "SKILL.md" not in files:
                continue
            try:
                metadata, _ = load_frontmatter(
                    (current_path / "SKILL.md").read_text(
                        encoding="utf-8"
                    )
                )
            except (OSError, UnicodeDecodeError) as exc:
                raise self.error_type(
                    "unmanaged_skill_invalid"
                ) from exc
            name = str(
                metadata.get("name") or current_path.name
            ).strip()
            if name:
                names.add(name.casefold())
        return names
