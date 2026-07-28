"""Hermes Enterprise Fleet adapter.

The adapter owns one nested managed skills tree inside an existing Hermes
home and installs a narrowly scoped user plugin that records a real
``on_session_start`` lifecycle event. Personal Hermes skills and runtime
credentials remain outside the Fleet-owned tree.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any, Mapping

from ..frontmatter import load_frontmatter
from ..private_packs import PrivatePackClient
from ..registration import RegistrationState
from .adapter import ManagedFleetAdapterError
from .managed_runtime import (
    ManagedRuntimeFleetAdapter,
    ManagedRuntimeFleetAdapterError,
    record_managed_runtime_observation,
)


HERMES_ADAPTER_ID = "hermes"
HERMES_ADAPTER_VERSION = "hermes-fleet/1.0.0"
HERMES_MANAGED_SKILLS_DIR = "unlimited-skills-fleet-managed"
HERMES_PLUGIN_NAME = "unlimited-skills-fleet"
MAX_HERMES_HOOK_INPUT_BYTES = 64 * 1024


class HermesFleetAdapterError(ManagedRuntimeFleetAdapterError):
    """Raised when Hermes cannot prove safe managed Fleet state."""


def _path_digest(path: Path) -> str:
    return "sha256:" + hashlib.sha256(
        str(path.resolve()).encode("utf-8")
    ).hexdigest()


def _bytes_digest(value: bytes) -> str:
    return "sha256:" + hashlib.sha256(value).hexdigest()


def _atomic_write(path: Path, value: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=path.parent,
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(value)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.chmod(temporary, 0o600)
        except OSError:
            pass
        if path.is_symlink():
            raise HermesFleetAdapterError(
                "runtime_plugin_path_symlink_forbidden"
            )
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def _plugin_source(
    *,
    managed_root: Path,
    hermes_home: Path,
    python_executable: Path,
) -> str:
    command = [
        str(python_executable),
        "-m",
        "unlimited_skills",
        "fleet",
        "hermes-runtime-start",
        "--managed-root",
        str(managed_root),
        "--hermes-home",
        str(hermes_home),
        "--hook-output",
    ]
    return (
        '"""Unlimited Skills Fleet lifecycle bridge for Hermes."""\n\n'
        "from __future__ import annotations\n\n"
        "import json\n"
        "import os\n"
        "import subprocess\n\n"
        f"_COMMAND = {command!r}\n"
        f"_HERMES_HOME = {str(hermes_home)!r}\n\n\n"
        "def register(ctx):\n"
        "    def on_session_start(session_id='', **kwargs):\n"
        "        payload = {\n"
        "            'hook_event_name': 'on_session_start',\n"
        "            'session_id': str(session_id or ''),\n"
        "        }\n"
        "        environment = dict(os.environ)\n"
        "        environment['HERMES_HOME'] = _HERMES_HOME\n"
        "        try:\n"
        "            subprocess.run(\n"
        "                _COMMAND,\n"
        "                input=json.dumps(payload),\n"
        "                text=True,\n"
        "                capture_output=True,\n"
        "                timeout=15,\n"
        "                check=False,\n"
        "                env=environment,\n"
        "            )\n"
        "        except (OSError, subprocess.SubprocessError):\n"
        "            return None\n"
        "        return None\n\n"
        "    ctx.register_hook('on_session_start', on_session_start)\n"
    )


def _plugin_root(hermes_home: Path) -> Path:
    return hermes_home / "plugins" / HERMES_PLUGIN_NAME


def _provision_hermes_runtime_plugin(
    *,
    managed_root: Path,
    hermes_home: Path,
    python_executable: Path,
    runtime_binding: Mapping[str, Any],
) -> None:
    plugins_root = hermes_home / "plugins"
    if plugins_root.exists() and (
        plugins_root.is_symlink() or not plugins_root.is_dir()
    ):
        raise HermesFleetAdapterError(
            "runtime_plugins_directory_invalid"
        )
    plugins_root.mkdir(parents=True, exist_ok=True)
    plugin_root = _plugin_root(hermes_home)
    if plugin_root.exists() and (
        plugin_root.is_symlink() or not plugin_root.is_dir()
    ):
        raise HermesFleetAdapterError(
            "runtime_plugin_path_invalid"
        )
    marker_path = plugin_root / "fleet-binding.json"
    if plugin_root.exists() and not marker_path.is_file():
        raise HermesFleetAdapterError("runtime_plugin_collision")
    plugin_root.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(plugin_root, 0o700)
    except OSError:
        pass
    source = _plugin_source(
        managed_root=managed_root,
        hermes_home=hermes_home,
        python_executable=python_executable,
    ).encode("utf-8")
    if _bytes_digest(source) != runtime_binding.get(
        "plugin_source_sha256"
    ):
        raise HermesFleetAdapterError(
            "runtime_plugin_binding_invalid"
        )
    manifest = (
        "name: unlimited-skills-fleet\n"
        'version: "1.0.0"\n'
        "description: Unlimited Skills Enterprise Fleet lifecycle bridge\n"
    ).encode("utf-8")
    marker = {
        "schema_version": 1,
        "adapter_id": HERMES_ADAPTER_ID,
        "adapter_version": HERMES_ADAPTER_VERSION,
        "hermes_home_sha256": _path_digest(hermes_home),
        "managed_root_sha256": _path_digest(managed_root),
        "plugin_source_sha256": _bytes_digest(source),
    }
    _atomic_write(plugin_root / "plugin.yaml", manifest)
    _atomic_write(plugin_root / "__init__.py", source)
    _atomic_write(
        marker_path,
        (
            json.dumps(
                marker,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
            + "\n"
        ).encode("utf-8"),
    )


def _assert_hermes_runtime_plugin(
    *,
    managed_root: Path,
    hermes_home: Path,
    runtime_binding: Mapping[str, Any],
) -> None:
    plugin_root = _plugin_root(hermes_home)
    if plugin_root.is_symlink() or not plugin_root.is_dir():
        raise HermesFleetAdapterError(
            "runtime_plugin_not_provisioned"
        )
    source_path = plugin_root / "__init__.py"
    marker_path = plugin_root / "fleet-binding.json"
    try:
        source = source_path.read_bytes()
        marker = json.loads(marker_path.read_text(encoding="utf-8"))
    except (
        OSError,
        UnicodeDecodeError,
        json.JSONDecodeError,
    ) as exc:
        raise HermesFleetAdapterError(
            "runtime_plugin_not_provisioned"
        ) from exc
    expected = {
        "schema_version": 1,
        "adapter_id": HERMES_ADAPTER_ID,
        "adapter_version": HERMES_ADAPTER_VERSION,
        "hermes_home_sha256": _path_digest(hermes_home),
        "managed_root_sha256": _path_digest(managed_root),
        "plugin_source_sha256": _bytes_digest(source),
    }
    if (
        marker != expected
        or _bytes_digest(source)
        != runtime_binding.get("plugin_source_sha256")
    ):
        raise HermesFleetAdapterError(
            "runtime_plugin_binding_invalid"
        )


def parse_hermes_session_start_payload(
    raw: bytes,
) -> dict[str, Any]:
    if not raw or len(raw) > MAX_HERMES_HOOK_INPUT_BYTES:
        raise HermesFleetAdapterError("runtime_hook_input_invalid")
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HermesFleetAdapterError(
            "runtime_hook_input_invalid"
        ) from exc
    if not isinstance(value, dict):
        raise HermesFleetAdapterError(
            "runtime_hook_input_invalid"
        )
    return value


def record_hermes_session_start(
    managed_root: Path,
    hermes_home: Path,
    hook_payload: Mapping[str, Any],
    *,
    process_id: int | None = None,
    parent_process_id: int | None = None,
    observed_at: str | None = None,
) -> dict[str, Any]:
    """Record privacy-safe evidence from a real Hermes session start."""

    try:
        root = Path(managed_root).expanduser().resolve()
        home = Path(hermes_home).expanduser().resolve()
        marker = json.loads(
            (root / "managed-root.json").read_text(encoding="utf-8")
        )
        if (
            not isinstance(marker, dict)
            or marker.get("adapter_id") != HERMES_ADAPTER_ID
            or marker.get("adapter_version")
            != HERMES_ADAPTER_VERSION
        ):
            raise HermesFleetAdapterError(
                "managed_root_marker_invalid"
            )
        binding = marker.get("runtime_binding")
        if not isinstance(binding, dict):
            raise HermesFleetAdapterError(
                "managed_root_marker_invalid"
            )
        if _path_digest(home) != binding.get(
            "hermes_home_sha256"
        ):
            raise HermesFleetAdapterError(
                "runtime_hermes_home_mismatch"
            )
        _assert_hermes_runtime_plugin(
            managed_root=root,
            hermes_home=home,
            runtime_binding=binding,
        )
        if (
            hook_payload.get("hook_event_name")
            != "on_session_start"
        ):
            raise HermesFleetAdapterError(
                "runtime_hook_event_invalid"
            )
        session_id = str(
            hook_payload.get("session_id") or ""
        ).strip()
        if (
            not session_id
            or len(session_id) > 2048
            or "\x00" in session_id
        ):
            raise HermesFleetAdapterError(
                "runtime_session_id_invalid"
            )
        return record_managed_runtime_observation(
            managed_root=root,
            skills_root=(
                home
                / "skills"
                / HERMES_MANAGED_SKILLS_DIR
            ),
            adapter_id=HERMES_ADAPTER_ID,
            adapter_version=HERMES_ADAPTER_VERSION,
            runtime_prefix="hermes-session",
            runtime_token=session_id,
            expected_binding=binding,
            observed_at=observed_at,
            process_id=process_id,
            parent_process_id=parent_process_id,
            extra_marker={
                "hermes_home_sha256": (
                    binding["hermes_home_sha256"]
                ),
                "hook_event_name": "on_session_start",
            },
            error_type=HermesFleetAdapterError,
        )
    except ManagedFleetAdapterError as exc:
        if isinstance(exc, HermesFleetAdapterError):
            raise
        raise HermesFleetAdapterError(str(exc)) from exc
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HermesFleetAdapterError(
            "managed_root_marker_invalid"
        ) from exc


class HermesFleetAdapter(ManagedRuntimeFleetAdapter):
    """Real Hermes adapter bound to one existing Hermes home."""

    adapter_id = HERMES_ADAPTER_ID
    adapter_version = HERMES_ADAPTER_VERSION
    runtime_vendor = "hermes"
    runtime_generation_prefix = "hermes"
    error_type = HermesFleetAdapterError

    def __init__(
        self,
        *,
        registration: RegistrationState,
        managed_root: Path,
        hermes_home: Path,
        pack_client: PrivatePackClient | None = None,
        python_executable: Path | None = None,
        timeout: float = 30.0,
    ) -> None:
        if not registration.registered:
            raise self.error_type(
                "fleet_registered_installation_required"
            )
        expanded_home = Path(hermes_home).expanduser()
        if expanded_home.exists() and (
            expanded_home.is_symlink()
            or not expanded_home.is_dir()
        ):
            raise self.error_type("runtime_hermes_home_invalid")
        expanded_home.resolve().mkdir(parents=True, exist_ok=True)
        self.hermes_home = expanded_home.resolve()
        expanded_root = Path(managed_root).expanduser()
        if expanded_root.exists() and expanded_root.is_symlink():
            raise self.error_type("managed_root_symlink_forbidden")
        expanded_root.resolve().mkdir(parents=True, exist_ok=True)
        self.python_executable = Path(
            python_executable or os.sys.executable
        ).expanduser().resolve()
        source = _plugin_source(
            managed_root=expanded_root.resolve(),
            hermes_home=self.hermes_home,
            python_executable=self.python_executable,
        ).encode("utf-8")
        binding = {
            "hermes_home_sha256": _path_digest(self.hermes_home),
            "plugin_source_sha256": _bytes_digest(source),
        }
        super().__init__(
            registration=registration,
            managed_root=expanded_root,
            skills_root=(
                self.hermes_home
                / "skills"
                / HERMES_MANAGED_SKILLS_DIR
            ),
            runtime_binding=binding,
            pack_client=pack_client,
            timeout=timeout,
        )
        _provision_hermes_runtime_plugin(
            managed_root=self.managed_root,
            hermes_home=self.hermes_home,
            python_executable=self.python_executable,
            runtime_binding=self.runtime_binding,
        )

    def _assert_runtime_parent(self, *, create: bool) -> None:
        skills_parent = self.hermes_home / "skills"
        if skills_parent.exists() and (
            skills_parent.is_symlink()
            or not skills_parent.is_dir()
        ):
            raise self.error_type(
                "runtime_hermes_skills_invalid"
            )
        if create:
            skills_parent.mkdir(parents=True, exist_ok=True)
        if skills_parent.resolve() != self.skills_root.parent:
            raise self.error_type(
                "runtime_hermes_skills_invalid"
            )

    def _unmanaged_skill_names(self) -> set[str]:
        root = self.hermes_home / "skills"
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
                if (
                    child.resolve() == self.skills_root
                    or directory.startswith(
                        (".skills-staging-", ".skills-backup-")
                    )
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
