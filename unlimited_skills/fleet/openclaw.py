"""OpenClaw Enterprise Fleet adapter.

One adapter instance binds one registered Fleet identity to one configured
OpenClaw ``agentId`` and workspace.  Managed skills are materialized in a
dedicated workspace subtree, while a host-level ``agent:bootstrap`` hook
records evidence only when that exact agent and workspace start a real run.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import re
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Iterator, Mapping

from ..frontmatter import load_frontmatter
from ..private_packs import PrivatePackClient
from ..registration import RegistrationState
from .adapter import ManagedFleetAdapterError
from .managed_runtime import (
    MANAGED_RUNTIME_ROOT_SCHEMA_VERSION,
    ManagedRuntimeFleetAdapter,
    ManagedRuntimeFleetAdapterError,
    record_managed_runtime_observation,
)


OPENCLAW_ADAPTER_ID = "openclaw"
OPENCLAW_ADAPTER_VERSION = "openclaw-fleet/1.0.0"
OPENCLAW_MANAGED_SKILLS_DIR = ".unlimited-skills-fleet-active"
MAX_OPENCLAW_HOOK_INPUT_BYTES = 64 * 1024
_AGENT_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


class OpenClawFleetAdapterError(ManagedRuntimeFleetAdapterError):
    """Raised when an OpenClaw agent runtime cannot prove safe state."""


_HOOK_MD = """---
name: unlimited-skills-fleet
description: "Record Enterprise Fleet evidence for configured OpenClaw agents"
metadata:
  {
    "openclaw":
      {
        "emoji": "🚚",
        "events": ["agent:bootstrap"],
        "always": true,
      },
  }
---

# Unlimited Skills Fleet

Records privacy-safe activation evidence for explicitly provisioned agent
targets. It does not add prompt text, expose pack bodies, or run arbitrary
server commands.
"""


_HANDLER_JS_TEMPLATE = r"""import fs from "node:fs";
import path from "node:path";
import { spawnSync } from "node:child_process";

const TARGETS_PATH = __TARGETS_PATH_JSON__;

export default async function unlimitedSkillsFleetHook(event) {
  if (!event || event.type !== "agent" || event.action !== "bootstrap") return;
  const context = event.context || {};
  const agentId = String(context.agentId || "").trim();
  const workspaceDir = String(context.workspaceDir || "").trim();
  const runtimeToken = String(
    event.sessionKey || context.sessionKey || context.runId || ""
  ).trim();
  if (!agentId || !workspaceDir || !runtimeToken) return;

  let targets;
  try {
    targets = JSON.parse(
      fs.readFileSync(TARGETS_PATH, "utf8")
    );
  } catch (error) {
    console.warn("[unlimited-skills-fleet] targets unavailable");
    return;
  }
  if (
    !targets ||
    !targets.targets ||
    !Object.prototype.hasOwnProperty.call(targets.targets, agentId)
  ) return;
  const target = targets.targets[agentId];
  if (!target || typeof target !== "object") return;
  if (
    typeof target.workspace !== "string" ||
    typeof target.managed_root !== "string" ||
    typeof target.python_executable !== "string" ||
    !path.isAbsolute(target.workspace) ||
    !path.isAbsolute(target.managed_root) ||
    !path.isAbsolute(target.python_executable)
  ) return;
  if (path.resolve(workspaceDir) !== path.resolve(target.workspace)) return;

  const payload = JSON.stringify({
    hook_event_name: "agent:bootstrap",
    agent_id: agentId,
    workspace_dir: workspaceDir,
    session_key: runtimeToken,
  });
  const result = spawnSync(
    target.python_executable,
    [
      "-m",
      "unlimited_skills",
      "fleet",
      "openclaw-runtime-start",
      "--managed-root",
      target.managed_root,
      "--json",
    ],
    {
      input: payload,
      encoding: "utf8",
      shell: false,
      timeout: 15000,
      env: {
        PATH: String(process.env.PATH || ""),
        HOME: String(process.env.HOME || ""),
        USERPROFILE: String(process.env.USERPROFILE || ""),
        SYSTEMROOT: String(process.env.SYSTEMROOT || ""),
        WINDIR: String(process.env.WINDIR || ""),
        TEMP: String(process.env.TEMP || ""),
        TMP: String(process.env.TMP || ""),
        UNLIMITED_SKILLS_FLEET_MANAGED_ROOT: target.managed_root,
      },
    }
  );
  if (result.error || result.status !== 0) {
    console.warn(
      `[unlimited-skills-fleet] runtime evidence failed for ${agentId}`
    );
  }
}
"""


def _path_digest(path: Path) -> str:
    return "sha256:" + hashlib.sha256(
        str(path.resolve()).encode("utf-8")
    ).hexdigest()


def _upgrade_legacy_default_profile_marker(
    *,
    managed_root: Path,
    registration: RegistrationState,
    agent_id: str,
    workspace: Path,
    openclaw_profile: str,
) -> None:
    """Add the empty profile binding to an exact pre-profile marker."""

    if openclaw_profile:
        return
    marker_path = (
        Path(managed_root).expanduser().resolve()
        / "managed-root.json"
    )
    if not marker_path.is_file() or marker_path.is_symlink():
        return
    try:
        existing = json.loads(marker_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return
    legacy_binding = {
        "agent_id": agent_id,
        "workspace_sha256": _path_digest(workspace),
    }
    legacy_marker = {
        "schema_version": MANAGED_RUNTIME_ROOT_SCHEMA_VERSION,
        "adapter_id": OPENCLAW_ADAPTER_ID,
        "adapter_version": OPENCLAW_ADAPTER_VERSION,
        "installation_id": registration.install_id,
        "runtime_vendor": "openclaw",
        "runtime_binding": legacy_binding,
    }
    if existing != legacy_marker:
        return
    upgraded = dict(legacy_marker)
    upgraded["runtime_binding"] = {
        **legacy_binding,
        "openclaw_profile": "",
    }
    _atomic_write_text(
        marker_path,
        json.dumps(
            upgraded,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ),
    )


def _atomic_write_text(
    path: Path,
    text: str,
    *,
    mode: int = 0o600,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=path.parent,
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
            if not text.endswith("\n"):
                handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.chmod(temporary, mode)
        except OSError:
            pass
        if path.is_symlink():
            raise OpenClawFleetAdapterError(
                "openclaw_hook_path_symlink_forbidden"
            )
        os.replace(temporary, path)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


@contextlib.contextmanager
def _provision_lock(path: Path) -> Iterator[None]:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+b") as handle:
        handle.seek(0, os.SEEK_END)
        if handle.tell() == 0:
            handle.write(b"0")
            handle.flush()
        deadline = time.monotonic() + 10.0
        while True:
            try:
                if os.name == "nt":
                    import msvcrt

                    handle.seek(0)
                    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl

                    fcntl.flock(
                        handle.fileno(),
                        fcntl.LOCK_EX | fcntl.LOCK_NB,
                    )
                break
            except (OSError, BlockingIOError):
                if time.monotonic() >= deadline:
                    raise OpenClawFleetAdapterError(
                        "openclaw_provision_lock_timeout"
                    )
                time.sleep(0.05)
        try:
            yield
        finally:
            if os.name == "nt":
                import msvcrt

                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def provision_openclaw_runtime_hook(
    *,
    openclaw_home: Path,
    agent_id: str,
    openclaw_profile: str = "",
    workspace: Path,
    managed_root: Path,
    python_executable: Path,
) -> Path:
    """Install/update the shared hook and one exact agent target binding."""

    if not _AGENT_ID.fullmatch(agent_id):
        raise OpenClawFleetAdapterError("openclaw_agent_id_invalid")
    if openclaw_profile and not _AGENT_ID.fullmatch(
        openclaw_profile
    ):
        raise OpenClawFleetAdapterError(
            "openclaw_profile_invalid"
        )
    expanded_home = Path(openclaw_home).expanduser()
    if expanded_home.exists() and expanded_home.is_symlink():
        raise OpenClawFleetAdapterError(
            "openclaw_home_symlink_forbidden"
        )
    home = expanded_home.resolve()
    home.mkdir(parents=True, exist_ok=True)
    hooks_root = home / "hooks"
    fleet_root = home / "fleet"
    for directory in (hooks_root, fleet_root):
        if directory.exists() and (
            directory.is_symlink() or not directory.is_dir()
        ):
            raise OpenClawFleetAdapterError(
                "openclaw_state_subdirectory_invalid"
            )
        directory.mkdir(parents=True, exist_ok=True)
        try:
            os.chmod(directory, 0o700)
        except OSError:
            pass
    hook_root = hooks_root / "unlimited-skills-fleet"
    targets_path = fleet_root / "targets.json"
    lock_path = fleet_root / ".targets.lock"
    with _provision_lock(lock_path):
        hook_root.mkdir(parents=True, exist_ok=True)
        if hook_root.is_symlink():
            raise OpenClawFleetAdapterError(
                "openclaw_hook_path_symlink_forbidden"
            )
        try:
            os.chmod(hook_root, 0o700)
        except OSError:
            pass
        _atomic_write_text(hook_root / "HOOK.md", _HOOK_MD)
        handler = _HANDLER_JS_TEMPLATE.replace(
            "__TARGETS_PATH_JSON__",
            json.dumps(str(targets_path.resolve())),
        )
        _atomic_write_text(hook_root / "handler.js", handler)
        if targets_path.exists():
            try:
                targets = json.loads(
                    targets_path.read_text(encoding="utf-8")
                )
            except (
                OSError,
                UnicodeDecodeError,
                json.JSONDecodeError,
            ) as exc:
                raise OpenClawFleetAdapterError(
                    "openclaw_targets_invalid"
                ) from exc
        else:
            targets = {
                "schema_version": 1,
                "targets": {},
            }
        if (
            not isinstance(targets, dict)
            or targets.get("schema_version") != 1
            or not isinstance(targets.get("targets"), dict)
        ):
            raise OpenClawFleetAdapterError(
                "openclaw_targets_invalid"
            )
        targets["targets"][agent_id] = {
            "managed_root": str(managed_root.resolve()),
            "openclaw_profile": openclaw_profile,
            "python_executable": str(python_executable),
            "workspace": str(workspace.resolve()),
        }
        _atomic_write_text(
            targets_path,
            json.dumps(
                targets,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ),
        )
    return hook_root


def parse_openclaw_bootstrap_payload(raw: bytes) -> dict[str, Any]:
    if not raw or len(raw) > MAX_OPENCLAW_HOOK_INPUT_BYTES:
        raise OpenClawFleetAdapterError(
            "runtime_hook_input_invalid"
        )
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise OpenClawFleetAdapterError(
            "runtime_hook_input_invalid"
        ) from exc
    if not isinstance(value, dict):
        raise OpenClawFleetAdapterError(
            "runtime_hook_input_invalid"
        )
    return value


def record_openclaw_agent_bootstrap(
    managed_root: Path,
    hook_payload: Mapping[str, Any],
    *,
    process_id: int | None = None,
    parent_process_id: int | None = None,
    observed_at: str | None = None,
) -> dict[str, Any]:
    """Record evidence from a real OpenClaw ``agent:bootstrap`` event."""

    try:
        root = Path(managed_root).expanduser().resolve()
        marker_path = root / "managed-root.json"
        if marker_path.is_symlink() or not marker_path.is_file():
            raise OpenClawFleetAdapterError(
                "managed_root_marker_invalid"
            )
        marker = json.loads(marker_path.read_text(encoding="utf-8"))
        if (
            not isinstance(marker, dict)
            or marker.get("adapter_id") != OPENCLAW_ADAPTER_ID
            or marker.get("adapter_version")
            != OPENCLAW_ADAPTER_VERSION
        ):
            raise OpenClawFleetAdapterError(
                "managed_root_marker_invalid"
            )
        binding = marker.get("runtime_binding")
        if not isinstance(binding, dict):
            raise OpenClawFleetAdapterError(
                "managed_root_marker_invalid"
            )
        if hook_payload.get("hook_event_name") != "agent:bootstrap":
            raise OpenClawFleetAdapterError(
                "runtime_hook_event_invalid"
            )
        agent_id = str(hook_payload.get("agent_id") or "")
        if agent_id != str(binding.get("agent_id") or ""):
            raise OpenClawFleetAdapterError(
                "runtime_agent_binding_mismatch"
            )
        raw_workspace = str(
            hook_payload.get("workspace_dir") or ""
        ).strip()
        if not raw_workspace or "\x00" in raw_workspace:
            raise OpenClawFleetAdapterError(
                "runtime_workspace_binding_mismatch"
            )
        workspace = Path(raw_workspace).expanduser().resolve()
        if _path_digest(workspace) != binding.get(
            "workspace_sha256"
        ):
            raise OpenClawFleetAdapterError(
                "runtime_workspace_binding_mismatch"
            )
        runtime_token = str(
            hook_payload.get("session_key")
            or hook_payload.get("run_id")
            or ""
        )
        skills_root = (
            workspace
            / "skills"
            / OPENCLAW_MANAGED_SKILLS_DIR
        )
        return record_managed_runtime_observation(
            managed_root=root,
            skills_root=skills_root,
            adapter_id=OPENCLAW_ADAPTER_ID,
            adapter_version=OPENCLAW_ADAPTER_VERSION,
            runtime_prefix="openclaw-bootstrap",
            runtime_token=runtime_token,
            expected_binding=binding,
            observed_at=observed_at,
            process_id=process_id,
            parent_process_id=parent_process_id,
            extra_marker={
                "agent_id": agent_id,
                "hook_event_name": "agent:bootstrap",
                "workspace_sha256": binding["workspace_sha256"],
            },
            error_type=OpenClawFleetAdapterError,
        )
    except ManagedFleetAdapterError as exc:
        if isinstance(exc, OpenClawFleetAdapterError):
            raise
        raise OpenClawFleetAdapterError(str(exc)) from exc
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise OpenClawFleetAdapterError(
            "managed_root_marker_invalid"
        ) from exc


class OpenClawFleetAdapter(ManagedRuntimeFleetAdapter):
    """Real OpenClaw adapter for one configured agent ID and workspace."""

    adapter_id = OPENCLAW_ADAPTER_ID
    adapter_version = OPENCLAW_ADAPTER_VERSION
    runtime_vendor = "openclaw"
    runtime_generation_prefix = "openclaw"
    error_type = OpenClawFleetAdapterError

    def __init__(
        self,
        *,
        registration: RegistrationState,
        managed_root: Path,
        workspace: Path,
        agent_id: str,
        openclaw_home: Path,
        openclaw_profile: str = "",
        pack_client: PrivatePackClient | None = None,
        python_executable: Path | None = None,
        timeout: float = 30.0,
    ) -> None:
        if not _AGENT_ID.fullmatch(str(agent_id)):
            raise self.error_type("openclaw_agent_id_invalid")
        profile = str(openclaw_profile or "").strip()
        if profile and not _AGENT_ID.fullmatch(profile):
            raise self.error_type("openclaw_profile_invalid")
        expanded_workspace = Path(workspace).expanduser()
        if (
            not expanded_workspace.exists()
            or expanded_workspace.is_symlink()
            or not expanded_workspace.is_dir()
        ):
            raise self.error_type("openclaw_workspace_invalid")
        self.workspace = expanded_workspace.resolve()
        self.agent_id = str(agent_id)
        self.openclaw_profile = profile
        self.openclaw_home = Path(openclaw_home).expanduser().resolve()
        self.python_executable = Path(
            python_executable or sys.executable
        )
        skills_root = (
            self.workspace
            / "skills"
            / OPENCLAW_MANAGED_SKILLS_DIR
        )
        binding = {
            "agent_id": self.agent_id,
            "openclaw_profile": self.openclaw_profile,
            "workspace_sha256": _path_digest(self.workspace),
        }
        _upgrade_legacy_default_profile_marker(
            managed_root=managed_root,
            registration=registration,
            agent_id=self.agent_id,
            workspace=self.workspace,
            openclaw_profile=self.openclaw_profile,
        )
        super().__init__(
            registration=registration,
            managed_root=managed_root,
            skills_root=skills_root,
            runtime_binding=binding,
            pack_client=pack_client,
            timeout=timeout,
        )
        provision_openclaw_runtime_hook(
            openclaw_home=self.openclaw_home,
            agent_id=self.agent_id,
            openclaw_profile=self.openclaw_profile,
            workspace=self.workspace,
            managed_root=self.managed_root,
            python_executable=self.python_executable,
        )

    def _assert_runtime_parent(self, *, create: bool) -> None:
        skills_parent = self.workspace / "skills"
        if skills_parent.exists() and (
            skills_parent.is_symlink() or not skills_parent.is_dir()
        ):
            raise self.error_type(
                "openclaw_workspace_skills_invalid"
            )
        if create:
            skills_parent.mkdir(parents=True, exist_ok=True)
        if skills_parent.resolve() != self.skills_root.parent:
            raise self.error_type(
                "openclaw_workspace_skills_invalid"
            )

    def _unmanaged_skill_names(self) -> set[str]:
        root = self.workspace / "skills"
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
                if child == self.skills_root or directory.startswith(
                    (".skills-staging-", ".skills-backup-")
                ):
                    continue
                if child.is_symlink():
                    raise self.error_type(
                        "unmanaged_skill_symlink_unsupported"
                    )
                filtered.append(directory)
            directories[:] = filtered
            if "SKILL.md" not in files:
                continue
            skill_file = current_path / "SKILL.md"
            try:
                metadata, _ = load_frontmatter(
                    skill_file.read_text(encoding="utf-8")
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
