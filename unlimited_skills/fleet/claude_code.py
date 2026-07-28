"""Claude Code Enterprise fleet adapter.

The adapter keeps downloaded pack revisions immutable and side by side under
one installation-bound managed root.  Activation materializes only the
adapter-owned ``runtime/.claude/skills`` directory.  A Claude Code
``SessionStart`` hook must then record that it observed the exact activation
before the adapter can return a runtime attestation.

No registry token, device key, prompt, transcript path, working directory, or
raw Claude session identifier is written to adapter state.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import secrets
import shlex
import shutil
import stat
import subprocess
import sys
import tempfile
import time
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any, Mapping

from ..frontmatter import load_frontmatter
from ..private_packs import PrivatePackClient
from ..registration import RegistrationState
from .adapter import (
    InstalledRevision,
    ManagedFleetAdapterError,
    RuntimeAttestation,
    RuntimeInventory,
    RuntimeInventoryAttestation,
)
from .contract import (
    DESIRED_STATE_SIGNING_ROLE,
    FLEET_CONTRACT_ID,
    FLEET_CONTRACT_VERSION,
    MAX_ITEMS,
    canonical_json_bytes,
)


CLAUDE_CODE_ADAPTER_ID = "claude-code"
CLAUDE_CODE_ADAPTER_VERSION = "claude-code-fleet/1.0.0"
MANAGED_ROOT_SCHEMA_VERSION = 1
ACTIVE_STATE_SCHEMA_VERSION = 2
RUNTIME_MARKER_SCHEMA_VERSION = 1
MAX_ARCHIVE_BYTES = 128 * 1024 * 1024
MAX_EXPANDED_BYTES = 512 * 1024 * 1024
MAX_ARCHIVE_MEMBERS = 20_000
MAX_HOOK_INPUT_BYTES = 64 * 1024
_ALLOWED_SESSION_SOURCES = {"startup", "resume"}
_CLAUDE_CONFIG_DIR_ENV = "CLAUDE_CONFIG_DIR"
_FLEET_MANAGED_ROOT_ENV = "UNLIMITED_SKILLS_FLEET_MANAGED_ROOT"
_WINDOWS_RESERVED_NAMES = {
    "aux",
    "com1",
    "com2",
    "com3",
    "com4",
    "com5",
    "com6",
    "com7",
    "com8",
    "com9",
    "con",
    "lpt1",
    "lpt2",
    "lpt3",
    "lpt4",
    "lpt5",
    "lpt6",
    "lpt7",
    "lpt8",
    "lpt9",
    "nul",
    "prn",
}


class ClaudeCodeFleetAdapterError(ManagedFleetAdapterError):
    """Raised when the Claude Code managed runtime cannot prove safe state."""


def _utc_now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _sha256_bytes(value: bytes) -> str:
    return "sha256:" + hashlib.sha256(value).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()


def _opaque_segment(value: str) -> str:
    return hashlib.sha256(str(value).encode("utf-8")).hexdigest()[:32]


def _ensure_owned_root(path: Path) -> Path:
    expanded = path.expanduser()
    if expanded.exists() and expanded.is_symlink():
        raise ClaudeCodeFleetAdapterError("managed_root_symlink_forbidden")
    root = expanded.resolve()
    root.mkdir(parents=True, exist_ok=True)
    if not root.is_dir():
        raise ClaudeCodeFleetAdapterError("managed_root_directory_required")
    try:
        os.chmod(root, 0o700)
    except OSError:
        pass
    return root


def _existing_owned_root(path: Path) -> Path:
    expanded = path.expanduser()
    if (
        not expanded.exists()
        or expanded.is_symlink()
        or not expanded.is_dir()
    ):
        raise ClaudeCodeFleetAdapterError("managed_root_invalid")
    return expanded.resolve()


def _assert_beneath(root: Path, path: Path, reason: str) -> Path:
    resolved_root = root.resolve()
    resolved = path.resolve()
    if resolved != resolved_root and resolved_root not in resolved.parents:
        raise ClaudeCodeFleetAdapterError(reason)
    return resolved


def _assert_managed_directory_path(
    root: Path,
    path: Path,
    reason: str,
    *,
    create: bool = False,
) -> Path:
    """Reject symlinked/non-directory components below a managed root."""

    root = root.resolve()
    try:
        relative = path.relative_to(root)
    except ValueError as exc:
        raise ClaudeCodeFleetAdapterError(reason) from exc
    current = root
    for part in relative.parts:
        current = current / part
        if current.exists():
            if current.is_symlink() or not current.is_dir():
                raise ClaudeCodeFleetAdapterError(reason)
        elif create:
            try:
                current.mkdir()
            except FileExistsError:
                if current.is_symlink() or not current.is_dir():
                    raise ClaudeCodeFleetAdapterError(reason)
        else:
            raise ClaudeCodeFleetAdapterError(reason)
    return path


def _atomic_write_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = canonical_json_bytes(dict(value)) + b"\n"
    fd, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=path.parent,
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.chmod(temporary, 0o600)
        except OSError:
            pass
        if path.is_symlink():
            raise ClaudeCodeFleetAdapterError("managed_state_symlink_forbidden")
        os.replace(temporary, path)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def _read_json_object(path: Path, reason: str) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise ClaudeCodeFleetAdapterError(reason)
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ClaudeCodeFleetAdapterError(reason) from exc
    if not isinstance(value, dict):
        raise ClaudeCodeFleetAdapterError(reason)
    return value


def _optional_json_object(path: Path, reason: str) -> dict[str, Any] | None:
    if not path.exists():
        return None
    return _read_json_object(path, reason)


def _tree_manifest(root: Path) -> list[dict[str, Any]]:
    if root.is_symlink() or not root.is_dir():
        raise ClaudeCodeFleetAdapterError("managed_skills_directory_invalid")
    rows: list[dict[str, Any]] = []
    for path in sorted(root.rglob("*"), key=lambda item: item.as_posix()):
        if path.is_symlink():
            raise ClaudeCodeFleetAdapterError("managed_skills_symlink_forbidden")
        if path.is_dir():
            continue
        if not path.is_file():
            raise ClaudeCodeFleetAdapterError("managed_skills_special_file_forbidden")
        relative = path.relative_to(root).as_posix()
        rows.append(
            {
                "path": relative,
                "sha256": _sha256_file(path),
                "size": path.stat().st_size,
            }
        )
    return rows


def _tree_digest(root: Path) -> str:
    return _sha256_bytes(
        canonical_json_bytes({"files": _tree_manifest(root)})
    )


def _inventory_row(item: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "action": str(item["action"]),
        "archive_sha256": str(item["archive_sha256"]),
        "pack_id": str(item["pack_id"]),
        "release_id": str(item["release_id"]),
        "required": bool(item["required"]),
    }


def managed_inventory_digest(rows: list[dict[str, Any]]) -> str:
    inventory = sorted(
        [dict(row) for row in rows],
        key=lambda value: str(value["pack_id"]),
    )
    return _sha256_bytes(
        canonical_json_bytes({"managed_inventory": inventory})
    )


def _drift_inventory_digest(
    rows: list[dict[str, Any]],
    observed_tree_digest: str,
) -> str:
    inventory = sorted(
        [dict(row) for row in rows],
        key=lambda value: str(value["pack_id"]),
    )
    return _sha256_bytes(
        canonical_json_bytes(
            {
                "managed_inventory": inventory,
                "observed_tree_sha256": observed_tree_digest,
            }
        )
    )


def private_pack_release_id(
    pack_id: str,
    version: str,
    archive_sha256: str,
) -> str:
    digest = str(archive_sha256).removeprefix("sha256:")
    return "release_" + hashlib.sha256(
        f"{pack_id}\n{version}\n{digest}".encode("utf-8")
    ).hexdigest()[:32]


def _strict_extract_zip(archive: Path, target: Path) -> None:
    if archive.stat().st_size > MAX_ARCHIVE_BYTES:
        raise ClaudeCodeFleetAdapterError("pack_archive_too_large")
    target.mkdir(parents=True, exist_ok=False)
    target_root = target.resolve()
    seen: set[str] = set()
    expanded_bytes = 0
    try:
        with zipfile.ZipFile(archive) as bundle:
            members = bundle.infolist()
            if not members or len(members) > MAX_ARCHIVE_MEMBERS:
                raise ClaudeCodeFleetAdapterError(
                    "pack_archive_member_count_invalid"
                )
            for member in members:
                name = str(member.filename)
                if (
                    not name
                    or "\x00" in name
                    or "\\" in name
                    or len(name) > 1024
                ):
                    raise ClaudeCodeFleetAdapterError(
                        "pack_archive_path_invalid"
                    )
                pure = PurePosixPath(name)
                if pure.is_absolute() or any(
                    part in {"", ".", ".."} for part in pure.parts
                ):
                    raise ClaudeCodeFleetAdapterError(
                        "pack_archive_path_invalid"
                    )
                for part in pure.parts:
                    stem = part.split(".", 1)[0].casefold()
                    if (
                        ":" in part
                        or part.endswith((" ", "."))
                        or any(ord(character) < 32 for character in part)
                        or stem in _WINDOWS_RESERVED_NAMES
                    ):
                        raise ClaudeCodeFleetAdapterError(
                            "pack_archive_path_invalid"
                        )
                normalized = pure.as_posix().rstrip("/")
                collision_key = normalized.casefold()
                if collision_key in seen:
                    raise ClaudeCodeFleetAdapterError(
                        "pack_archive_path_collision"
                    )
                seen.add(collision_key)
                unix_mode = (member.external_attr >> 16) & 0xFFFF
                file_type = stat.S_IFMT(unix_mode)
                if file_type and file_type not in {
                    stat.S_IFREG,
                    stat.S_IFDIR,
                }:
                    raise ClaudeCodeFleetAdapterError(
                        "pack_archive_special_file_forbidden"
                    )
                expanded_bytes += int(member.file_size)
                if expanded_bytes > MAX_EXPANDED_BYTES:
                    raise ClaudeCodeFleetAdapterError(
                        "pack_archive_expanded_size_exceeded"
                    )
                destination = (target / Path(*pure.parts)).resolve()
                if (
                    destination != target_root
                    and target_root not in destination.parents
                ):
                    raise ClaudeCodeFleetAdapterError(
                        "pack_archive_path_invalid"
                    )
                if member.is_dir() or name.endswith("/"):
                    destination.mkdir(parents=True, exist_ok=True)
                    continue
                destination.parent.mkdir(parents=True, exist_ok=True)
                with bundle.open(member, "r") as source:
                    with destination.open("xb") as output:
                        shutil.copyfileobj(source, output)
    except zipfile.BadZipFile as exc:
        raise ClaudeCodeFleetAdapterError(
            "pack_archive_invalid"
        ) from exc


def _resolve_skills_source(extracted: Path) -> Path:
    candidates: list[Path] = []
    for candidate in [extracted / "skills", *extracted.glob("*/skills")]:
        if candidate.is_dir() and candidate not in candidates:
            candidates.append(candidate)
    if not candidates:
        for skill_file in extracted.rglob("SKILL.md"):
            parent = skill_file.parent
            if parent.parent.name == "skills":
                candidate = parent.parent
                if candidate not in candidates:
                    candidates.append(candidate)
    if len(candidates) != 1:
        raise ClaudeCodeFleetAdapterError(
            "pack_archive_skills_directory_invalid"
        )
    skills = candidates[0]
    skill_files = [
        path for path in skills.glob("*/SKILL.md") if path.is_file()
    ]
    if not skill_files:
        raise ClaudeCodeFleetAdapterError("pack_archive_has_no_skills")
    return skills


def _skill_runtime_name(skill_dir: Path) -> str:
    try:
        text = (skill_dir / "SKILL.md").read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise ClaudeCodeFleetAdapterError(
            "pack_skills_layout_invalid"
        ) from exc
    metadata, _ = load_frontmatter(text)
    name = str(metadata.get("name") or skill_dir.name).strip()
    if (
        not name
        or len(name) > 160
        or "\x00" in name
        or "/" in name
        or "\\" in name
    ):
        raise ClaudeCodeFleetAdapterError(
            "pack_skill_name_invalid"
        )
    return name.casefold()


def _make_read_only(root: Path) -> None:
    for path in sorted(
        root.rglob("*"),
        key=lambda item: len(item.parts),
        reverse=True,
    ):
        try:
            os.chmod(path, 0o555 if path.is_dir() else 0o444)
        except OSError:
            pass
    try:
        os.chmod(root, 0o555)
    except OSError:
        pass


def _state_digest(value: Mapping[str, Any]) -> str:
    return _sha256_bytes(canonical_json_bytes(dict(value)))


def managed_claude_config_dir(managed_root: Path) -> Path:
    """Return the isolated Claude configuration directory for one agent."""

    root = managed_root.expanduser().resolve()
    return root / "runtime" / ".claude"


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
            "runtime-start",
            "--managed-root",
            str(root),
            "--json",
        ]
    )


def _is_fleet_runtime_hook_entry(entry: object) -> bool:
    if not isinstance(entry, dict):
        return False
    for hook in entry.get("hooks") or []:
        if not isinstance(hook, dict):
            continue
        command = str(hook.get("command") or "")
        if (
            "unlimited_skills" in command
            and "fleet" in command
            and "runtime-start" in command
        ):
            return True
    return False


def _provision_runtime_hook(root: Path) -> None:
    config_dir = managed_claude_config_dir(root)
    _assert_managed_directory_path(
        root,
        config_dir,
        "runtime_config_directory_invalid",
        create=True,
    )
    settings_path = config_dir / "settings.json"
    try:
        raw = (
            settings_path.read_text(encoding="utf-8")
            if settings_path.is_file()
            else ""
        )
        settings = json.loads(raw) if raw.strip() else {}
    except (OSError, json.JSONDecodeError) as exc:
        raise ClaudeCodeFleetAdapterError(
            "runtime_settings_invalid"
        ) from exc
    if not isinstance(settings, dict):
        raise ClaudeCodeFleetAdapterError("runtime_settings_invalid")
    hooks = settings.setdefault("hooks", {})
    if not isinstance(hooks, dict):
        raise ClaudeCodeFleetAdapterError("runtime_settings_invalid")
    entries = hooks.get("SessionStart")
    if not isinstance(entries, list):
        entries = []
    entries = [
        entry
        for entry in entries
        if not _is_fleet_runtime_hook_entry(entry)
    ]
    entries.append(
        {
            "hooks": [
                {
                    "type": "command",
                    "command": _runtime_hook_command(root),
                    "timeout": 15,
                }
            ]
        }
    )
    hooks["SessionStart"] = entries
    _atomic_write_json(settings_path, settings)


def _assert_runtime_hook_provisioned(root: Path) -> None:
    _assert_managed_directory_path(
        root,
        managed_claude_config_dir(root),
        "runtime_config_directory_invalid",
    )
    settings = _read_json_object(
        managed_claude_config_dir(root) / "settings.json",
        "runtime_settings_invalid",
    )
    hooks = settings.get("hooks")
    entries = hooks.get("SessionStart") if isinstance(hooks, dict) else None
    expected_command = _runtime_hook_command(root)
    if not isinstance(entries, list) or not any(
        isinstance(entry, dict)
        and any(
            isinstance(hook, dict)
            and hook.get("type") == "command"
            and hook.get("command") == expected_command
            for hook in entry.get("hooks") or []
        )
        for entry in entries
    ):
        raise ClaudeCodeFleetAdapterError(
            "runtime_hook_not_provisioned"
        )


def _validate_managed_marker(
    root: Path,
    *,
    installation_id: str = "",
) -> dict[str, Any]:
    marker = _read_json_object(
        root / "managed-root.json",
        "managed_root_marker_invalid",
    )
    if (
        marker.get("schema_version") != MANAGED_ROOT_SCHEMA_VERSION
        or marker.get("adapter_id") != CLAUDE_CODE_ADAPTER_ID
        or marker.get("adapter_version") != CLAUDE_CODE_ADAPTER_VERSION
    ):
        raise ClaudeCodeFleetAdapterError("managed_root_marker_invalid")
    if installation_id and marker.get("installation_id") != installation_id:
        raise ClaudeCodeFleetAdapterError(
            "managed_root_installation_mismatch"
        )
    return marker


def _active_inventory(
    root: Path,
    state: Mapping[str, Any],
) -> tuple[list[dict[str, Any]], str, str, bool]:
    if state.get("schema_version") != ACTIVE_STATE_SCHEMA_VERSION:
        raise ClaudeCodeFleetAdapterError("active_state_invalid")
    raw_inventory = state.get("managed_inventory")
    if (
        not isinstance(raw_inventory, list)
        or not raw_inventory
        or len(raw_inventory) > MAX_ITEMS
    ):
        raise ClaudeCodeFleetAdapterError("active_state_invalid")
    inventory: list[dict[str, Any]] = []
    pack_ids: set[str] = set()
    for raw_row in raw_inventory:
        if not isinstance(raw_row, dict):
            raise ClaudeCodeFleetAdapterError("active_state_invalid")
        try:
            row = _inventory_row(raw_row)
        except (KeyError, TypeError, ValueError) as exc:
            raise ClaudeCodeFleetAdapterError(
                "active_state_invalid"
            ) from exc
        pack_id = str(row["pack_id"])
        if not pack_id or pack_id in pack_ids:
            raise ClaudeCodeFleetAdapterError("active_state_invalid")
        pack_ids.add(pack_id)
        inventory.append(row)
    inventory.sort(key=lambda value: str(value["pack_id"]))
    expected_inventory_digest = managed_inventory_digest(inventory)
    if (
        state.get("expected_inventory_digest")
        != expected_inventory_digest
    ):
        raise ClaudeCodeFleetAdapterError("active_state_invalid")
    skills_root = root / "runtime" / ".claude" / "skills"
    _assert_managed_directory_path(
        root,
        skills_root,
        "managed_skills_directory_invalid",
    )
    observed_tree = _tree_digest(skills_root)
    expected_tree = str(state.get("skills_tree_sha256") or "")
    drifted = observed_tree != expected_tree
    digest = (
        _drift_inventory_digest(inventory, observed_tree)
        if drifted
        else managed_inventory_digest(inventory)
    )
    return inventory, digest, observed_tree, drifted


def _active_pack_maps(
    state: Mapping[str, Any],
) -> tuple[dict[str, str], dict[str, str], dict[str, str]]:
    raw_packs = state.get("active_packs")
    if not isinstance(raw_packs, list) or not raw_packs:
        raise ClaudeCodeFleetAdapterError("active_state_invalid")
    activation_nonces: dict[str, str] = {}
    active_revisions: dict[str, str] = {}
    active_archives: dict[str, str] = {}
    for raw_pack in raw_packs:
        if not isinstance(raw_pack, dict):
            raise ClaudeCodeFleetAdapterError("active_state_invalid")
        pack_id = str(raw_pack.get("pack_id") or "")
        release_id = str(raw_pack.get("release_id") or "")
        archive_sha256 = str(
            raw_pack.get("archive_sha256") or ""
        )
        activation_nonce = str(
            raw_pack.get("activation_nonce") or ""
        )
        if (
            not pack_id
            or pack_id in active_revisions
            or not release_id
            or not archive_sha256.startswith("sha256:")
            or not activation_nonce
        ):
            raise ClaudeCodeFleetAdapterError("active_state_invalid")
        active_revisions[pack_id] = release_id
        active_archives[pack_id] = archive_sha256
        activation_nonces[pack_id] = activation_nonce
    return activation_nonces, active_revisions, active_archives


def record_claude_session_start(
    managed_root: Path,
    hook_payload: Mapping[str, Any],
    *,
    environment: Mapping[str, str] | None = None,
    process_id: int | None = None,
    parent_process_id: int | None = None,
    observed_at: str | None = None,
) -> dict[str, Any]:
    """Record privacy-safe evidence from a real Claude ``SessionStart`` hook."""

    root = _existing_owned_root(managed_root)
    _validate_managed_marker(root)
    _assert_managed_directory_path(
        root,
        root / "state",
        "managed_state_directory_invalid",
    )
    runtime_environment = environment if environment is not None else os.environ
    configured_dir = str(
        runtime_environment.get(_CLAUDE_CONFIG_DIR_ENV) or ""
    ).strip()
    if not configured_dir:
        raise ClaudeCodeFleetAdapterError(
            "runtime_config_dir_unproven"
        )
    configured_path = Path(configured_dir).expanduser()
    if (
        configured_path.exists()
        and configured_path.is_symlink()
    ):
        raise ClaudeCodeFleetAdapterError(
            "runtime_config_symlink_forbidden"
        )
    if configured_path.resolve() != managed_claude_config_dir(root):
        raise ClaudeCodeFleetAdapterError(
            "runtime_config_dir_mismatch"
        )
    if str(
        runtime_environment.get(_FLEET_MANAGED_ROOT_ENV) or ""
    ).strip():
        asserted_root = Path(
            str(runtime_environment[_FLEET_MANAGED_ROOT_ENV])
        ).expanduser()
        if asserted_root.resolve() != root:
            raise ClaudeCodeFleetAdapterError(
                "runtime_managed_root_mismatch"
            )
    _assert_runtime_hook_provisioned(root)
    if hook_payload.get("hook_event_name") != "SessionStart":
        raise ClaudeCodeFleetAdapterError("runtime_hook_event_invalid")
    source = str(hook_payload.get("source") or "")
    if source not in _ALLOWED_SESSION_SOURCES:
        return {
            "recorded": False,
            "reason": "runtime_source_not_new_generation",
            "source": source,
        }
    session_id = str(hook_payload.get("session_id") or "")
    if not session_id or len(session_id) > 512 or "\x00" in session_id:
        raise ClaudeCodeFleetAdapterError("runtime_session_id_invalid")
    state_path = root / "state" / "active.json"
    state = _read_json_object(state_path, "active_state_invalid")
    _, inventory_digest, observed_tree, drifted = _active_inventory(
        root,
        state,
    )
    (
        activation_nonces,
        active_revisions,
        active_archives,
    ) = _active_pack_maps(state)
    state_digest = _state_digest(state)
    generation_hash = hashlib.sha256(
        (
            f"{session_id}\n{state.get('activation_marker', '')}\n"
            f"{parent_process_id or os.getppid()}"
        ).encode("utf-8")
    ).hexdigest()[:40]
    runtime_generation = f"claude-session:{generation_hash}"
    marker = {
        "schema_version": RUNTIME_MARKER_SCHEMA_VERSION,
        "adapter_id": CLAUDE_CODE_ADAPTER_ID,
        "adapter_version": CLAUDE_CODE_ADAPTER_VERSION,
        "runtime_generation": runtime_generation,
        "session_id_sha256": _sha256_bytes(session_id.encode("utf-8")),
        "source": source,
        "observed_at": observed_at or _utc_now(),
        "process_id": int(process_id if process_id is not None else os.getpid()),
        "parent_process_id": int(
            parent_process_id
            if parent_process_id is not None
            else os.getppid()
        ),
        "active_state_sha256": state_digest,
        "activation_marker": str(state.get("activation_marker") or ""),
        "activation_nonces": activation_nonces,
        "active_revisions": active_revisions,
        "active_archive_sha256": active_archives,
        "active_inventory_digest": inventory_digest,
        "observed_skills_tree_sha256": observed_tree,
        "drifted": drifted,
    }
    history = _assert_managed_directory_path(
        root,
        root / "runtime-history",
        "runtime_history_directory_invalid",
        create=True,
    )
    history_path = history / f"{generation_hash}.json"
    if history_path.exists():
        existing = _read_json_object(
            history_path,
            "runtime_history_invalid",
        )
        if existing != marker:
            raise ClaudeCodeFleetAdapterError(
                "runtime_generation_conflict"
            )
    else:
        try:
            with history_path.open("x", encoding="utf-8") as handle:
                handle.write(
                    json.dumps(
                        marker,
                        ensure_ascii=False,
                        sort_keys=True,
                        separators=(",", ":"),
                    )
                    + "\n"
                )
                handle.flush()
                os.fsync(handle.fileno())
            try:
                os.chmod(history_path, 0o600)
            except OSError:
                pass
        except FileExistsError:
            existing = _read_json_object(
                history_path,
                "runtime_history_invalid",
            )
            if existing != marker:
                raise ClaudeCodeFleetAdapterError(
                    "runtime_generation_conflict"
                )
    _atomic_write_json(root / "state" / "runtime-current.json", marker)
    return {
        "recorded": True,
        "runtime_generation": runtime_generation,
        "active_inventory_digest": inventory_digest,
        "drifted": drifted,
    }


def parse_session_start_payload(raw: bytes) -> dict[str, Any]:
    if not raw or len(raw) > MAX_HOOK_INPUT_BYTES:
        raise ClaudeCodeFleetAdapterError("runtime_hook_input_invalid")
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ClaudeCodeFleetAdapterError(
            "runtime_hook_input_invalid"
        ) from exc
    if not isinstance(value, dict):
        raise ClaudeCodeFleetAdapterError("runtime_hook_input_invalid")
    return value


def load_fleet_public_keys(path: Path) -> dict[str, bytes]:
    """Load explicitly provisioned fleet desired-state trust anchors."""

    payload = _read_json_object(path, "fleet_public_keys_invalid")
    if payload.get("schema_version") != 1:
        raise ClaudeCodeFleetAdapterError("fleet_public_keys_invalid")
    if payload.get("contract_id") not in {None, FLEET_CONTRACT_ID}:
        raise ClaudeCodeFleetAdapterError("fleet_public_keys_invalid")
    if payload.get("contract_version") not in {
        None,
        FLEET_CONTRACT_VERSION,
    }:
        raise ClaudeCodeFleetAdapterError("fleet_public_keys_invalid")
    keys = payload.get("keys")
    if not isinstance(keys, list) or not keys:
        raise ClaudeCodeFleetAdapterError("fleet_public_keys_invalid")
    trusted: dict[str, bytes] = {}
    for row in keys:
        if (
            not isinstance(row, dict)
            or row.get("algorithm") != "ed25519"
            or row.get("role") != DESIRED_STATE_SIGNING_ROLE
            or row.get("status", "active") != "active"
        ):
            continue
        key_id = str(row.get("key_id") or "")
        encoded = str(row.get("public_key") or "")
        if not key_id or key_id in trusted or not encoded:
            raise ClaudeCodeFleetAdapterError(
                "fleet_public_keys_invalid"
            )
        try:
            padding = "=" * (-len(encoded) % 4)
            public_key = base64.urlsafe_b64decode(encoded + padding)
        except (ValueError, TypeError) as exc:
            raise ClaudeCodeFleetAdapterError(
                "fleet_public_keys_invalid"
            ) from exc
        if len(public_key) != 32:
            raise ClaudeCodeFleetAdapterError(
                "fleet_public_keys_invalid"
            )
        trusted[key_id] = public_key
    if not trusted:
        raise ClaudeCodeFleetAdapterError("fleet_public_keys_invalid")
    return trusted


class ClaudeCodeFleetAdapter:
    """Real Claude Code adapter for one isolated managed agent root."""

    adapter_id = CLAUDE_CODE_ADAPTER_ID
    adapter_version = CLAUDE_CODE_ADAPTER_VERSION

    def __init__(
        self,
        *,
        registration: RegistrationState,
        managed_root: Path,
        pack_client: PrivatePackClient | None = None,
        timeout: float = 30.0,
    ) -> None:
        if not registration.registered:
            raise ClaudeCodeFleetAdapterError(
                "fleet_registered_installation_required"
            )
        self.registration = registration
        self.managed_root = _ensure_owned_root(managed_root)
        self.releases_root = self.managed_root / "releases"
        self.state_root = self.managed_root / "state"
        self.skills_root = (
            self.managed_root / "runtime" / ".claude" / "skills"
        )
        _assert_managed_directory_path(
            self.managed_root,
            self.releases_root,
            "managed_releases_directory_invalid",
            create=True,
        )
        _assert_managed_directory_path(
            self.managed_root,
            self.state_root,
            "managed_state_directory_invalid",
            create=True,
        )
        marker_path = self.managed_root / "managed-root.json"
        marker = {
            "schema_version": MANAGED_ROOT_SCHEMA_VERSION,
            "adapter_id": self.adapter_id,
            "adapter_version": self.adapter_version,
            "installation_id": registration.install_id,
            "runtime_vendor": "claude-code",
        }
        if marker_path.exists():
            _validate_managed_marker(
                self.managed_root,
                installation_id=registration.install_id,
            )
        else:
            _atomic_write_json(marker_path, marker)
        _provision_runtime_hook(self.managed_root)
        self.pack_client = pack_client or PrivatePackClient(
            registration,
            timeout=timeout,
        )

    def _release_root(
        self,
        pack_id: str,
        release_id: str,
    ) -> Path:
        _assert_managed_directory_path(
            self.managed_root,
            self.releases_root,
            "managed_releases_directory_invalid",
        )
        path = (
            self.releases_root
            / _opaque_segment(pack_id)
            / _opaque_segment(release_id)
        )
        return _assert_beneath(
            self.releases_root,
            path,
            "release_path_invalid",
        )

    def _assert_state_root(self) -> None:
        _assert_managed_directory_path(
            self.managed_root,
            self.state_root,
            "managed_state_directory_invalid",
        )

    def _installed_from_metadata(
        self,
        metadata: Mapping[str, Any],
    ) -> InstalledRevision:
        return InstalledRevision(
            pack_id=str(metadata.get("pack_id") or ""),
            release_id=str(metadata.get("release_id") or ""),
            version=str(metadata.get("version") or ""),
            archive_sha256=str(
                metadata.get("archive_sha256") or ""
            ),
            install_committed=True,
            metadata={
                "manifest_sha256": str(
                    metadata.get("manifest_sha256") or ""
                ),
                "skills_tree_sha256": str(
                    metadata.get("skills_tree_sha256") or ""
                ),
            },
        )

    def _validate_manifest(
        self,
        item: Mapping[str, Any],
        manifest: Mapping[str, Any],
    ) -> tuple[str, str]:
        pack_id = str(item["pack_id"])
        version = str(item["version"])
        expected_archive = str(item["archive_sha256"])
        expected_release = str(item["release_id"])
        manifest_archive = "sha256:" + str(
            manifest.get("sha256") or ""
        ).removeprefix("sha256:")
        if (
            manifest.get("manifest_type")
            != "private-team-pack-manifest"
            or manifest.get("visibility") != "private-team"
            or manifest.get("revoked") is True
            or str(manifest.get("pack_id") or "") != pack_id
            or str(manifest.get("version") or "") != version
            or manifest_archive != expected_archive
            or private_pack_release_id(
                pack_id,
                version,
                expected_archive,
            )
            != expected_release
            or str(item.get("manifest_ref") or "")
            != (
                f"registry:private-pack/{pack_id}/"
                f"{expected_release}"
            )
        ):
            raise ClaudeCodeFleetAdapterError(
                "pack_manifest_desired_state_mismatch"
            )
        manifest_sha = _sha256_bytes(
            canonical_json_bytes(dict(manifest))
        )
        return manifest_archive, manifest_sha

    def discover(self) -> RuntimeInventory:
        self._assert_state_root()
        state = _optional_json_object(
            self.state_root / "active.json",
            "active_state_invalid",
        )
        if state is None:
            return RuntimeInventory(
                runtime_generation="claude-code:inactive",
                active_revisions={},
                inventory_digest=managed_inventory_digest([]),
            )
        inventory, digest, _, _ = _active_inventory(
            self.managed_root,
            state,
        )
        marker = _optional_json_object(
            self.state_root / "runtime-current.json",
            "runtime_marker_invalid",
        )
        if (
            marker is not None
            and marker.get("schema_version")
            == RUNTIME_MARKER_SCHEMA_VERSION
            and marker.get("adapter_id") == self.adapter_id
            and marker.get("adapter_version") == self.adapter_version
            and marker.get("active_state_sha256")
            == _state_digest(state)
            and marker.get("activation_marker")
            == state.get("activation_marker")
        ):
            generation = str(
                marker.get("runtime_generation") or ""
            )
        else:
            generation = (
                "claude-code:pending:"
                + _opaque_segment(
                    str(state.get("activation_marker") or "")
                )[:24]
            )
        active_revisions = {
            str(row["pack_id"]): str(row["release_id"])
            for row in inventory
        }
        return RuntimeInventory(
            runtime_generation=generation,
            active_revisions=active_revisions,
            inventory_digest=digest,
        )

    def install_revision(
        self,
        item: Mapping[str, Any],
    ) -> InstalledRevision:
        pack_id = str(item["pack_id"])
        release_id = str(item["release_id"])
        final_root = self._release_root(pack_id, release_id)
        metadata_path = final_root / "installed.json"
        if metadata_path.is_file():
            metadata = _read_json_object(
                metadata_path,
                "installed_revision_invalid",
            )
            installed = self._installed_from_metadata(metadata)
            self.verify_revision(item, installed)
            return installed

        manifest_payload = self.pack_client.signed_manifest(pack_id)
        manifest = manifest_payload.get("manifest")
        if not isinstance(manifest, dict):
            raise ClaudeCodeFleetAdapterError(
                "pack_manifest_invalid"
            )
        manifest_archive, manifest_sha = self._validate_manifest(
            item,
            manifest,
        )
        archive_bytes = self.pack_client.download_archive(
            pack_id,
            release_id=release_id,
            expected_sha256=manifest_archive,
        )
        if (
            not isinstance(archive_bytes, bytes)
            or not archive_bytes
            or len(archive_bytes) > MAX_ARCHIVE_BYTES
        ):
            raise ClaudeCodeFleetAdapterError(
                "pack_archive_size_invalid"
            )
        if int(manifest.get("bytes") or 0) not in {
            0,
            len(archive_bytes),
        }:
            raise ClaudeCodeFleetAdapterError(
                "pack_archive_size_mismatch"
            )
        archive_sha = _sha256_bytes(archive_bytes)
        if archive_sha != manifest_archive:
            raise ClaudeCodeFleetAdapterError(
                "pack_archive_hash_mismatch"
            )

        final_root.parent.mkdir(parents=True, exist_ok=True)
        staging_root = Path(
            tempfile.mkdtemp(
                prefix=".release-staging-",
                dir=final_root.parent,
            )
        )
        committed = False
        try:
            archive = staging_root / "archive.zip"
            archive.write_bytes(archive_bytes)
            extracted = staging_root / "extracted"
            _strict_extract_zip(archive, extracted)
            source = _resolve_skills_source(extracted)
            payload_root = staging_root / "payload"
            shutil.copytree(source, payload_root)
            skills_tree_sha = _tree_digest(payload_root)
            metadata = {
                "schema_version": 1,
                "adapter_id": self.adapter_id,
                "adapter_version": self.adapter_version,
                "installation_id": self.registration.install_id,
                "pack_id": pack_id,
                "release_id": release_id,
                "version": str(item["version"]),
                "archive_sha256": archive_sha,
                "manifest_sha256": manifest_sha,
                "skills_tree_sha256": skills_tree_sha,
                "installed_at": _utc_now(),
            }
            shutil.rmtree(extracted)
            _atomic_write_json(
                staging_root / "installed.json",
                metadata,
            )
            _make_read_only(payload_root)
            try:
                os.chmod(archive, 0o444)
            except OSError:
                pass
            try:
                os.replace(staging_root, final_root)
                committed = True
            except OSError:
                if not final_root.is_dir():
                    raise
            if not committed:
                shutil.rmtree(staging_root, ignore_errors=True)
            installed_metadata = _read_json_object(
                metadata_path,
                "installed_revision_invalid",
            )
            installed = self._installed_from_metadata(
                installed_metadata
            )
            self.verify_revision(item, installed)
            return installed
        finally:
            if staging_root.exists():
                shutil.rmtree(staging_root, ignore_errors=True)

    def verify_revision(
        self,
        item: Mapping[str, Any],
        installed: InstalledRevision,
    ) -> None:
        release_root = self._release_root(
            str(item["pack_id"]),
            str(item["release_id"]),
        )
        metadata = _read_json_object(
            release_root / "installed.json",
            "installed_revision_invalid",
        )
        expected = {
            "pack_id": str(item["pack_id"]),
            "release_id": str(item["release_id"]),
            "version": str(item["version"]),
            "archive_sha256": str(item["archive_sha256"]),
            "installation_id": self.registration.install_id,
            "adapter_id": self.adapter_id,
            "adapter_version": self.adapter_version,
        }
        if any(
            str(metadata.get(key) or "") != value
            for key, value in expected.items()
        ):
            raise ClaudeCodeFleetAdapterError(
                "installed_revision_mismatch"
            )
        if (
            installed.pack_id != expected["pack_id"]
            or installed.release_id != expected["release_id"]
            or installed.version != expected["version"]
            or installed.archive_sha256
            != expected["archive_sha256"]
            or not installed.install_committed
        ):
            raise ClaudeCodeFleetAdapterError(
                "installed_revision_mismatch"
            )
        archive = release_root / "archive.zip"
        if (
            archive.is_symlink()
            or not archive.is_file()
            or archive.stat().st_size > MAX_ARCHIVE_BYTES
            or _sha256_file(archive) != expected["archive_sha256"]
        ):
            raise ClaudeCodeFleetAdapterError(
                "installed_revision_tampered"
            )
        verification_root = _assert_managed_directory_path(
            self.managed_root,
            self.state_root / "verification",
            "managed_verification_directory_invalid",
            create=True,
        )
        with tempfile.TemporaryDirectory(
            prefix=".archive-verify-",
            dir=verification_root,
        ) as temporary:
            extracted = Path(temporary) / "extracted"
            _strict_extract_zip(archive, extracted)
            archive_tree = _tree_digest(
                _resolve_skills_source(extracted)
            )
        observed_tree = _tree_digest(release_root / "payload")
        if (
            observed_tree
            != str(metadata.get("skills_tree_sha256") or "")
            or archive_tree != observed_tree
        ):
            raise ClaudeCodeFleetAdapterError(
                "installed_revision_tampered"
            )

    def activate_inventory(
        self,
        items: list[Mapping[str, Any]],
        installed: Mapping[str, InstalledRevision],
        *,
        activation_nonces: Mapping[str, str],
    ) -> None:
        self._assert_state_root()
        if not items or len(items) > MAX_ITEMS:
            raise ClaudeCodeFleetAdapterError(
                "managed_inventory_invalid"
            )
        normalized_items = sorted(
            [dict(item) for item in items],
            key=lambda value: str(value["pack_id"]),
        )
        pack_ids = [str(item["pack_id"]) for item in normalized_items]
        if (
            len(set(pack_ids)) != len(pack_ids)
            or set(installed) != set(pack_ids)
            or set(activation_nonces) != set(pack_ids)
        ):
            raise ClaudeCodeFleetAdapterError(
                "managed_inventory_invalid"
            )
        release_roots: dict[str, Path] = {}
        release_metadata: dict[str, dict[str, Any]] = {}
        active_packs: list[dict[str, Any]] = []
        for item in normalized_items:
            pack_id = str(item["pack_id"])
            revision = installed[pack_id]
            if str(activation_nonces[pack_id]) != str(
                item["activation_nonce"]
            ):
                raise ClaudeCodeFleetAdapterError(
                    "activation_nonce_mismatch"
                )
            self.verify_revision(item, revision)
            release_root = self._release_root(
                revision.pack_id,
                revision.release_id,
            )
            metadata = _read_json_object(
                release_root / "installed.json",
                "installed_revision_invalid",
            )
            release_roots[pack_id] = release_root
            release_metadata[pack_id] = metadata
            active_packs.append(
                {
                    "action": str(item["action"]),
                    "activation_nonce": str(
                        activation_nonces[pack_id]
                    ),
                    "archive_sha256": revision.archive_sha256,
                    "pack_id": pack_id,
                    "release_id": revision.release_id,
                    "skills_tree_sha256": str(
                        metadata.get("skills_tree_sha256") or ""
                    ),
                    "version": revision.version,
                }
            )
        inventory = [_inventory_row(item) for item in normalized_items]
        expected_inventory_digest = managed_inventory_digest(inventory)
        existing = _optional_json_object(
            self.state_root / "active.json",
            "active_state_invalid",
        )
        same_activation = bool(
            existing
            and existing.get("active_packs") == active_packs
            and existing.get("managed_inventory") == inventory
        )
        if same_activation:
            try:
                _, _, _, drifted = _active_inventory(
                    self.managed_root,
                    existing,
                )
            except ClaudeCodeFleetAdapterError:
                drifted = True
            if not drifted:
                return

        _assert_managed_directory_path(
            self.managed_root,
            self.skills_root.parent,
            "runtime_config_directory_invalid",
        )
        staging = Path(
            tempfile.mkdtemp(
                prefix=".skills-staging-",
                dir=self.skills_root.parent,
            )
        )
        backup = (
            self.skills_root.parent
            / f".skills-backup-{secrets.token_hex(12)}"
        )
        had_previous = self.skills_root.exists()
        try:
            claimed_skill_names: dict[str, str] = {}
            for item in normalized_items:
                pack_id = str(item["pack_id"])
                source = release_roots[pack_id] / "payload"
                observed_source_tree = _tree_digest(source)
                if observed_source_tree != str(
                    release_metadata[pack_id].get(
                        "skills_tree_sha256"
                    )
                    or ""
                ):
                    raise ClaudeCodeFleetAdapterError(
                        "activation_payload_mismatch"
                    )
                for child in sorted(
                    source.iterdir(),
                    key=lambda value: value.name.casefold(),
                ):
                    if child.is_symlink() or not child.is_dir():
                        raise ClaudeCodeFleetAdapterError(
                            "pack_skills_layout_invalid"
                        )
                    if not (child / "SKILL.md").is_file():
                        raise ClaudeCodeFleetAdapterError(
                            "pack_skills_layout_invalid"
                        )
                    collision_key = _skill_runtime_name(child)
                    if collision_key in claimed_skill_names:
                        raise ClaudeCodeFleetAdapterError(
                            "managed_skill_collision"
                        )
                    claimed_skill_names[collision_key] = pack_id
                    shutil.copytree(child, staging / child.name)
            observed_tree = _tree_digest(staging)
            if had_previous:
                if self.skills_root.is_symlink():
                    raise ClaudeCodeFleetAdapterError(
                        "managed_skills_symlink_forbidden"
                    )
                os.replace(self.skills_root, backup)
            os.replace(staging, self.skills_root)
            active_state = {
                "schema_version": ACTIVE_STATE_SCHEMA_VERSION,
                "adapter_id": self.adapter_id,
                "adapter_version": self.adapter_version,
                "installation_id": self.registration.install_id,
                "active_packs": active_packs,
                "activation_marker": (
                    "activation_" + secrets.token_urlsafe(24)
                ),
                "managed_inventory": inventory,
                "expected_inventory_digest": expected_inventory_digest,
                "skills_tree_sha256": observed_tree,
                "activated_at": _utc_now(),
            }
            try:
                _atomic_write_json(
                    self.state_root / "active.json",
                    active_state,
                )
            except Exception:
                shutil.rmtree(self.skills_root, ignore_errors=True)
                if had_previous and backup.exists():
                    os.replace(backup, self.skills_root)
                raise
            if backup.exists():
                shutil.rmtree(backup, ignore_errors=True)
        finally:
            if staging.exists():
                shutil.rmtree(staging, ignore_errors=True)
            if backup.exists():
                shutil.rmtree(backup, ignore_errors=True)

    def _activate(
        self,
        item: Mapping[str, Any],
        installed: InstalledRevision,
        *,
        activation_nonce: str,
    ) -> None:
        self.activate_inventory(
            [item],
            {str(item["pack_id"]): installed},
            activation_nonces={
                str(item["pack_id"]): activation_nonce
            },
        )

    def activate_revision(
        self,
        item: Mapping[str, Any],
        installed: InstalledRevision,
        *,
        activation_nonce: str,
    ) -> None:
        if item.get("action") != "activate":
            raise ClaudeCodeFleetAdapterError(
                "activation_action_invalid"
            )
        self._activate(
            item,
            installed,
            activation_nonce=activation_nonce,
        )

    def rollback_revision(
        self,
        item: Mapping[str, Any],
        installed: InstalledRevision,
        *,
        activation_nonce: str,
    ) -> None:
        if item.get("action") != "rollback":
            raise ClaudeCodeFleetAdapterError(
                "rollback_action_invalid"
            )
        self._activate(
            item,
            installed,
            activation_nonce=activation_nonce,
        )

    def attest_inventory(
        self,
        items: list[Mapping[str, Any]],
        *,
        activation_nonces: Mapping[str, str],
    ) -> RuntimeInventoryAttestation:
        self._assert_state_root()
        state = _read_json_object(
            self.state_root / "active.json",
            "active_state_invalid",
        )
        marker = _read_json_object(
            self.state_root / "runtime-current.json",
            "runtime_attestation_pending",
        )
        inventory, digest, observed_tree, drifted = _active_inventory(
            self.managed_root,
            state,
        )
        (
            state_nonces,
            active_revisions,
            active_archives,
        ) = _active_pack_maps(state)
        expected_items = sorted(
            [dict(item) for item in items],
            key=lambda value: str(value["pack_id"]),
        )
        expected_inventory = [
            _inventory_row(item) for item in expected_items
        ]
        expected_revisions = {
            str(item["pack_id"]): str(item["release_id"])
            for item in expected_items
        }
        expected_archives = {
            str(item["pack_id"]): str(item["archive_sha256"])
            for item in expected_items
        }
        expected_nonces = {
            str(item["pack_id"]): str(item["activation_nonce"])
            for item in expected_items
        }
        if (
            drifted
            or marker.get("schema_version")
            != RUNTIME_MARKER_SCHEMA_VERSION
            or marker.get("adapter_id") != self.adapter_id
            or marker.get("adapter_version") != self.adapter_version
            or marker.get("active_state_sha256")
            != _state_digest(state)
            or marker.get("activation_marker")
            != state.get("activation_marker")
            or dict(activation_nonces) != expected_nonces
            or state_nonces != expected_nonces
            or marker.get("activation_nonces")
            != expected_nonces
            or active_revisions != expected_revisions
            or marker.get("active_revisions")
            != expected_revisions
            or active_archives != expected_archives
            or marker.get("active_archive_sha256")
            != expected_archives
            or marker.get("observed_skills_tree_sha256")
            != observed_tree
            or marker.get("active_inventory_digest") != digest
            or inventory != expected_inventory
        ):
            raise ClaudeCodeFleetAdapterError(
                "runtime_attestation_invalid"
            )
        return RuntimeInventoryAttestation(
            runtime_generation=str(marker["runtime_generation"]),
            activation_nonces=expected_nonces,
            active_revisions=expected_revisions,
            active_archive_sha256=expected_archives,
            active_inventory_digest=digest,
            adapter_version=self.adapter_version,
        )

    def attest_runtime(
        self,
        item: Mapping[str, Any],
        *,
        activation_nonce: str,
    ) -> RuntimeAttestation:
        attestation = self.attest_inventory(
            [item],
            activation_nonces={
                str(item["pack_id"]): activation_nonce
            },
        )
        pack_id = str(item["pack_id"])
        return RuntimeAttestation(
            runtime_generation=attestation.runtime_generation,
            activation_nonce=activation_nonce,
            pack_id=pack_id,
            release_id=attestation.active_revisions[pack_id],
            active_archive_sha256=(
                attestation.active_archive_sha256[pack_id]
            ),
            active_inventory_digest=(
                attestation.active_inventory_digest
            ),
            adapter_version=attestation.adapter_version,
        )

    def detect_inventory_drift(
        self,
        items: list[Mapping[str, Any]],
    ) -> bool:
        self._assert_state_root()
        state = _read_json_object(
            self.state_root / "active.json",
            "active_state_invalid",
        )
        try:
            inventory, _, _, drifted = _active_inventory(
                self.managed_root,
                state,
            )
        except ClaudeCodeFleetAdapterError:
            return True
        expected = sorted(
            [_inventory_row(item) for item in items],
            key=lambda value: str(value["pack_id"]),
        )
        return drifted or inventory != expected

    def detect_drift(self, item: Mapping[str, Any]) -> bool:
        return self.detect_inventory_drift([item])
