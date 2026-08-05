"""Shared filesystem mechanics for non-Claude Enterprise Fleet adapters.

The public wire protocol stays vendor neutral.  This module owns the local,
signed-pack lifecycle shared by OpenClaw, Codex, and Hermes: immutable revisions,
atomic complete-inventory activation, drift detection, and runtime evidence
validation.  Vendor modules remain responsible for binding evidence to a real
runtime lifecycle event.
"""

from __future__ import annotations

import hashlib
import os
import secrets
import shutil
import tempfile
from pathlib import Path
from typing import Any, Callable, Mapping

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
from .claude_code import (
    MAX_ARCHIVE_BYTES,
    _assert_beneath,
    _assert_managed_directory_path,
    _atomic_write_json,
    _ensure_owned_root,
    _existing_owned_root,
    _inventory_row,
    _make_read_only,
    _opaque_segment,
    _optional_json_object,
    _read_json_object,
    _resolve_skills_source,
    _runtime_marker_matches_history,
    _sha256_bytes,
    _sha256_file,
    _state_digest,
    _strict_extract_zip,
    _tree_digest,
    _utc_now,
    managed_inventory_digest,
    private_pack_release_id,
)
from .contract import MAX_ITEMS, canonical_json_bytes


MANAGED_RUNTIME_ROOT_SCHEMA_VERSION = 1
MANAGED_RUNTIME_ACTIVE_SCHEMA_VERSION = 1
MANAGED_RUNTIME_MARKER_SCHEMA_VERSION = 1
MAX_MANAGED_PACKS = MAX_ITEMS
INSTALL_STAGING_PREFIX = ".s-"


class ManagedRuntimeFleetAdapterError(ManagedFleetAdapterError):
    """Raised when a managed non-Claude runtime cannot prove safe state."""


def _translate_errors(method: Callable[..., Any]) -> Callable[..., Any]:
    def translated(self: "ManagedRuntimeFleetAdapter", *args: Any, **kwargs: Any) -> Any:
        try:
            return method(self, *args, **kwargs)
        except ManagedFleetAdapterError as exc:
            if isinstance(exc, self.error_type):
                raise
            raise self.error_type(str(exc)) from exc

    translated.__name__ = method.__name__
    translated.__doc__ = method.__doc__
    return translated


def _runtime_active_inventory(
    *,
    state: Mapping[str, Any],
    skills_root: Path,
    adapter_id: str,
    adapter_version: str,
    error_type: type[ManagedFleetAdapterError],
) -> tuple[list[dict[str, Any]], str, str, bool]:
    if (
        state.get("schema_version")
        != MANAGED_RUNTIME_ACTIVE_SCHEMA_VERSION
        or state.get("adapter_id") != adapter_id
        or state.get("adapter_version") != adapter_version
    ):
        raise error_type("active_state_invalid")
    raw_inventory = state.get("managed_inventory")
    if (
        not isinstance(raw_inventory, list)
        or not raw_inventory
        or len(raw_inventory) > MAX_MANAGED_PACKS
    ):
        raise error_type("active_state_invalid")
    inventory: list[dict[str, Any]] = []
    pack_ids: set[str] = set()
    for raw_row in raw_inventory:
        if not isinstance(raw_row, dict):
            raise error_type("active_state_invalid")
        try:
            row = _inventory_row(raw_row)
        except (KeyError, TypeError, ValueError) as exc:
            raise error_type("active_state_invalid") from exc
        pack_id = str(row["pack_id"])
        if not pack_id or pack_id in pack_ids:
            raise error_type("active_state_invalid")
        pack_ids.add(pack_id)
        inventory.append(row)
    inventory.sort(key=lambda value: str(value["pack_id"]))
    expected_inventory_digest = managed_inventory_digest(inventory)
    if (
        state.get("expected_inventory_digest")
        != expected_inventory_digest
    ):
        raise error_type("active_state_invalid")
    if skills_root.is_symlink() or not skills_root.is_dir():
        raise error_type("managed_skills_directory_invalid")
    observed_tree = _tree_digest(skills_root)
    expected_tree = str(state.get("skills_tree_sha256") or "")
    drifted = observed_tree != expected_tree
    digest = (
        _sha256_bytes(
            canonical_json_bytes(
                {
                    "managed_inventory": inventory,
                    "observed_tree_sha256": observed_tree,
                }
            )
        )
        if drifted
        else expected_inventory_digest
    )
    return inventory, digest, observed_tree, drifted


def _runtime_pack_maps(
    state: Mapping[str, Any],
    *,
    error_type: type[ManagedFleetAdapterError],
) -> tuple[dict[str, str], dict[str, str], dict[str, str]]:
    raw_packs = state.get("active_packs")
    if not isinstance(raw_packs, list) or not raw_packs:
        raise error_type("active_state_invalid")
    nonces: dict[str, str] = {}
    revisions: dict[str, str] = {}
    archives: dict[str, str] = {}
    for raw_pack in raw_packs:
        if not isinstance(raw_pack, dict):
            raise error_type("active_state_invalid")
        pack_id = str(raw_pack.get("pack_id") or "")
        release_id = str(raw_pack.get("release_id") or "")
        archive_sha256 = str(
            raw_pack.get("archive_sha256") or ""
        )
        nonce = str(raw_pack.get("activation_nonce") or "")
        if (
            not pack_id
            or pack_id in revisions
            or not release_id
            or not archive_sha256.startswith("sha256:")
            or not nonce
        ):
            raise error_type("active_state_invalid")
        nonces[pack_id] = nonce
        revisions[pack_id] = release_id
        archives[pack_id] = archive_sha256
    return nonces, revisions, archives


def record_managed_runtime_observation(
    *,
    managed_root: Path,
    skills_root: Path,
    adapter_id: str,
    adapter_version: str,
    runtime_prefix: str,
    runtime_token: str,
    expected_binding: Mapping[str, Any],
    observed_at: str | None = None,
    process_id: int | None = None,
    parent_process_id: int | None = None,
    extra_marker: Mapping[str, Any] | None = None,
    error_type: type[ManagedFleetAdapterError] = (
        ManagedRuntimeFleetAdapterError
    ),
) -> dict[str, Any]:
    """Persist privacy-safe evidence from one real vendor lifecycle event."""

    root = _existing_owned_root(managed_root)
    root_marker = _read_json_object(
        root / "managed-root.json",
        "managed_root_marker_invalid",
    )
    if (
        root_marker.get("schema_version")
        != MANAGED_RUNTIME_ROOT_SCHEMA_VERSION
        or root_marker.get("adapter_id") != adapter_id
        or root_marker.get("adapter_version") != adapter_version
        or root_marker.get("runtime_binding")
        != dict(expected_binding)
    ):
        raise error_type("managed_root_marker_invalid")
    if not runtime_token or len(runtime_token) > 2048 or "\x00" in runtime_token:
        raise error_type("runtime_token_invalid")
    state = _read_json_object(
        root / "state" / "active.json",
        "active_state_invalid",
    )
    inventory, inventory_digest, observed_tree, drifted = (
        _runtime_active_inventory(
            state=state,
            skills_root=skills_root,
            adapter_id=adapter_id,
            adapter_version=adapter_version,
            error_type=error_type,
        )
    )
    del inventory
    nonces, revisions, archives = _runtime_pack_maps(
        state,
        error_type=error_type,
    )
    state_digest = _state_digest(state)
    generation_hash = hashlib.sha256(
        (
            f"{runtime_token}\n{state.get('activation_marker', '')}\n"
            f"{parent_process_id or os.getppid()}"
        ).encode("utf-8")
    ).hexdigest()[:40]
    runtime_generation = f"{runtime_prefix}:{generation_hash}"
    marker: dict[str, Any] = {
        "schema_version": MANAGED_RUNTIME_MARKER_SCHEMA_VERSION,
        "adapter_id": adapter_id,
        "adapter_version": adapter_version,
        "runtime_generation": runtime_generation,
        "runtime_token_sha256": _sha256_bytes(
            runtime_token.encode("utf-8")
        ),
        "observed_at": observed_at or _utc_now(),
        "process_id": int(
            process_id if process_id is not None else os.getpid()
        ),
        "parent_process_id": int(
            parent_process_id
            if parent_process_id is not None
            else os.getppid()
        ),
        "active_state_sha256": state_digest,
        "activation_marker": str(
            state.get("activation_marker") or ""
        ),
        "activation_nonces": nonces,
        "active_revisions": revisions,
        "active_archive_sha256": archives,
        "active_inventory_digest": inventory_digest,
        "observed_skills_tree_sha256": observed_tree,
        "drifted": drifted,
    }
    if extra_marker:
        for key, value in extra_marker.items():
            if key in marker:
                raise error_type("runtime_marker_field_conflict")
            marker[str(key)] = value
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
            raise error_type("runtime_generation_conflict")
    else:
        try:
            with history_path.open("x", encoding="utf-8") as handle:
                import json

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
                raise error_type("runtime_generation_conflict")
    _atomic_write_json(root / "state" / "runtime-current.json", marker)
    return {
        "recorded": True,
        "runtime_generation": runtime_generation,
        "active_inventory_digest": inventory_digest,
        "drifted": drifted,
    }


class ManagedRuntimeFleetAdapter:
    """Base for one registered, isolated vendor runtime instance."""

    adapter_id = "managed-runtime"
    adapter_version = "managed-runtime-fleet/0"
    runtime_vendor = "managed-runtime"
    runtime_generation_prefix = "managed-runtime"
    error_type: type[ManagedFleetAdapterError] = (
        ManagedRuntimeFleetAdapterError
    )

    @_translate_errors
    def __init__(
        self,
        *,
        registration: RegistrationState,
        managed_root: Path,
        skills_root: Path,
        runtime_binding: Mapping[str, Any],
        pack_client: PrivatePackClient | None = None,
        timeout: float = 30.0,
    ) -> None:
        if not registration.registered:
            raise self.error_type(
                "fleet_registered_installation_required"
            )
        self.registration = registration
        self.managed_root = _ensure_owned_root(managed_root)
        self.releases_root = self.managed_root / "releases"
        self.state_root = self.managed_root / "state"
        self.skills_root = Path(skills_root).expanduser().resolve()
        self.runtime_binding = dict(runtime_binding)
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
        self._assert_runtime_parent(create=True)
        marker = {
            "schema_version": MANAGED_RUNTIME_ROOT_SCHEMA_VERSION,
            "adapter_id": self.adapter_id,
            "adapter_version": self.adapter_version,
            "installation_id": registration.install_id,
            "runtime_vendor": self.runtime_vendor,
            "runtime_binding": self.runtime_binding,
        }
        marker_path = self.managed_root / "managed-root.json"
        if marker_path.exists():
            existing = _read_json_object(
                marker_path,
                "managed_root_marker_invalid",
            )
            if existing != marker:
                raise self.error_type(
                    "managed_root_installation_mismatch"
                )
        else:
            _atomic_write_json(marker_path, marker)
        self.pack_client = pack_client or PrivatePackClient(
            registration,
            timeout=timeout,
            endpoint_prefix="/v1/fleet/private-packs",
        )

    def _assert_runtime_parent(self, *, create: bool) -> None:
        parent = self.skills_root.parent
        if parent.exists() and (
            parent.is_symlink() or not parent.is_dir()
        ):
            raise self.error_type(
                "runtime_skills_parent_invalid"
            )
        if create:
            parent.mkdir(parents=True, exist_ok=True)
        if not parent.is_dir():
            raise self.error_type(
                "runtime_skills_parent_invalid"
            )

    def _unmanaged_skill_names(self) -> set[str]:
        return set()

    def _release_root(self, pack_id: str, release_id: str) -> Path:
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
            != f"registry:private-pack/{pack_id}/{expected_release}"
        ):
            raise self.error_type(
                "pack_manifest_desired_state_mismatch"
            )
        manifest_sha = _sha256_bytes(
            canonical_json_bytes(dict(manifest))
        )
        return manifest_archive, manifest_sha

    @_translate_errors
    def discover(self) -> RuntimeInventory:
        self._assert_state_root()
        state = _optional_json_object(
            self.state_root / "active.json",
            "active_state_invalid",
        )
        if state is None:
            return RuntimeInventory(
                runtime_generation=f"{self.runtime_generation_prefix}:inactive",
                active_revisions={},
                inventory_digest=managed_inventory_digest([]),
            )
        inventory, digest, _, _ = _runtime_active_inventory(
            state=state,
            skills_root=self.skills_root,
            adapter_id=self.adapter_id,
            adapter_version=self.adapter_version,
            error_type=self.error_type,
        )
        marker = _optional_json_object(
            self.state_root / "runtime-current.json",
            "runtime_marker_invalid",
        )
        if (
            marker is not None
            and marker.get("schema_version")
            == MANAGED_RUNTIME_MARKER_SCHEMA_VERSION
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
                f"{self.runtime_generation_prefix}:pending:"
                + _opaque_segment(
                    str(state.get("activation_marker") or "")
                )[:24]
            )
        return RuntimeInventory(
            runtime_generation=generation,
            active_revisions={
                str(row["pack_id"]): str(row["release_id"])
                for row in inventory
            },
            inventory_digest=digest,
        )

    @_translate_errors
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
        manifest_payload = self.pack_client.signed_manifest(
            pack_id,
            request_context=item,
        )
        manifest = manifest_payload.get("manifest")
        if not isinstance(manifest, dict):
            raise self.error_type("pack_manifest_invalid")
        manifest_archive, manifest_sha = self._validate_manifest(
            item,
            manifest,
        )
        archive_bytes = self.pack_client.download_archive(
            pack_id,
            release_id=release_id,
            expected_sha256=manifest_archive,
            request_context=item,
        )
        if (
            not isinstance(archive_bytes, bytes)
            or not archive_bytes
            or len(archive_bytes) > MAX_ARCHIVE_BYTES
        ):
            raise self.error_type("pack_archive_size_invalid")
        if int(manifest.get("bytes") or 0) not in {
            0,
            len(archive_bytes),
        }:
            raise self.error_type("pack_archive_size_mismatch")
        archive_sha = _sha256_bytes(archive_bytes)
        if archive_sha != manifest_archive:
            raise self.error_type("pack_archive_hash_mismatch")
        final_root.parent.mkdir(parents=True, exist_ok=True)
        staging_root = Path(
            tempfile.mkdtemp(
                # Keep this deliberately short.  The staging directory lives
                # below two opaque release segments; a verbose prefix can push
                # otherwise valid pack members beyond the legacy Windows
                # MAX_PATH boundary before the immutable release is committed.
                prefix=INSTALL_STAGING_PREFIX,
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
            installed = self._installed_from_metadata(
                _read_json_object(
                    metadata_path,
                    "installed_revision_invalid",
                )
            )
            self.verify_revision(item, installed)
            return installed
        finally:
            if staging_root.exists():
                shutil.rmtree(staging_root, ignore_errors=True)

    @_translate_errors
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
            raise self.error_type("installed_revision_mismatch")
        if (
            installed.pack_id != expected["pack_id"]
            or installed.release_id != expected["release_id"]
            or installed.version != expected["version"]
            or installed.archive_sha256
            != expected["archive_sha256"]
            or not installed.install_committed
        ):
            raise self.error_type("installed_revision_mismatch")
        archive = release_root / "archive.zip"
        if (
            archive.is_symlink()
            or not archive.is_file()
            or archive.stat().st_size > MAX_ARCHIVE_BYTES
            or _sha256_file(archive) != expected["archive_sha256"]
        ):
            raise self.error_type("installed_revision_tampered")
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
            raise self.error_type("installed_revision_tampered")

    def _skill_name(self, skill_dir: Path) -> str:
        try:
            text = (skill_dir / "SKILL.md").read_text(
                encoding="utf-8"
            )
        except (OSError, UnicodeDecodeError) as exc:
            raise self.error_type("pack_skills_layout_invalid") from exc
        metadata, _ = load_frontmatter(text)
        name = str(metadata.get("name") or skill_dir.name).strip()
        if (
            not name
            or len(name) > 160
            or "\x00" in name
            or "/" in name
            or "\\" in name
        ):
            raise self.error_type("pack_skill_name_invalid")
        return name.casefold()

    @_translate_errors
    def activate_inventory(
        self,
        items: list[Mapping[str, Any]],
        installed: Mapping[str, InstalledRevision],
        *,
        activation_nonces: Mapping[str, str],
    ) -> None:
        self._assert_state_root()
        if not items or len(items) > MAX_MANAGED_PACKS:
            raise self.error_type("managed_inventory_invalid")
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
            raise self.error_type("managed_inventory_invalid")
        release_roots: dict[str, Path] = {}
        release_metadata: dict[str, dict[str, Any]] = {}
        active_packs: list[dict[str, Any]] = []
        for item in normalized_items:
            pack_id = str(item["pack_id"])
            revision = installed[pack_id]
            if str(activation_nonces[pack_id]) != str(
                item["activation_nonce"]
            ):
                raise self.error_type("activation_nonce_mismatch")
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
        existing = _optional_json_object(
            self.state_root / "active.json",
            "active_state_invalid",
        )
        if (
            existing
            and existing.get("active_packs") == active_packs
            and existing.get("managed_inventory") == inventory
        ):
            try:
                _, _, _, drifted = _runtime_active_inventory(
                    state=existing,
                    skills_root=self.skills_root,
                    adapter_id=self.adapter_id,
                    adapter_version=self.adapter_version,
                    error_type=self.error_type,
                )
            except ManagedFleetAdapterError:
                drifted = True
            if not drifted:
                return
        self._assert_runtime_parent(create=True)
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
            claimed_names: dict[str, str] = {}
            unmanaged_names = self._unmanaged_skill_names()
            for item in normalized_items:
                pack_id = str(item["pack_id"])
                source = release_roots[pack_id] / "payload"
                if _tree_digest(source) != str(
                    release_metadata[pack_id].get(
                        "skills_tree_sha256"
                    )
                    or ""
                ):
                    raise self.error_type(
                        "activation_payload_mismatch"
                    )
                for child in sorted(
                    source.iterdir(),
                    key=lambda value: value.name.casefold(),
                ):
                    if child.is_symlink() or not child.is_dir():
                        raise self.error_type(
                            "pack_skills_layout_invalid"
                        )
                    if not (child / "SKILL.md").is_file():
                        raise self.error_type(
                            "pack_skills_layout_invalid"
                        )
                    skill_name = self._skill_name(child)
                    skill_tree_sha256 = _tree_digest(child)
                    if skill_name in claimed_names:
                        if claimed_names[skill_name] == skill_tree_sha256:
                            continue
                        raise self.error_type("managed_skill_collision")
                    if skill_name in unmanaged_names:
                        raise self.error_type(
                            "unmanaged_skill_collision"
                        )
                    claimed_names[skill_name] = skill_tree_sha256
                    shutil.copytree(child, staging / child.name)
            observed_tree = _tree_digest(staging)
            if had_previous:
                if self.skills_root.is_symlink():
                    raise self.error_type(
                        "managed_skills_symlink_forbidden"
                    )
                os.replace(self.skills_root, backup)
            os.replace(staging, self.skills_root)
            active_state = {
                "schema_version": (
                    MANAGED_RUNTIME_ACTIVE_SCHEMA_VERSION
                ),
                "adapter_id": self.adapter_id,
                "adapter_version": self.adapter_version,
                "installation_id": self.registration.install_id,
                "active_packs": active_packs,
                "activation_marker": (
                    "activation_" + secrets.token_urlsafe(24)
                ),
                "managed_inventory": inventory,
                "expected_inventory_digest": (
                    managed_inventory_digest(inventory)
                ),
                "skills_tree_sha256": observed_tree,
                "activated_at": _utc_now(),
            }
            try:
                _atomic_write_json(
                    self.state_root / "active.json",
                    active_state,
                )
            except Exception:
                shutil.rmtree(
                    self.skills_root,
                    ignore_errors=True,
                )
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

    def activate_revision(
        self,
        item: Mapping[str, Any],
        installed: InstalledRevision,
        *,
        activation_nonce: str,
    ) -> None:
        if item.get("action") != "activate":
            raise self.error_type("activation_action_invalid")
        self.activate_inventory(
            [item],
            {str(item["pack_id"]): installed},
            activation_nonces={
                str(item["pack_id"]): activation_nonce
            },
        )

    def rollback_revision(
        self,
        item: Mapping[str, Any],
        installed: InstalledRevision,
        *,
        activation_nonce: str,
    ) -> None:
        if item.get("action") != "rollback":
            raise self.error_type("rollback_action_invalid")
        self.activate_inventory(
            [item],
            {str(item["pack_id"]): installed},
            activation_nonces={
                str(item["pack_id"]): activation_nonce
            },
        )

    @_translate_errors
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
        inventory, digest, observed_tree, drifted = (
            _runtime_active_inventory(
                state=state,
                skills_root=self.skills_root,
                adapter_id=self.adapter_id,
                adapter_version=self.adapter_version,
                error_type=self.error_type,
            )
        )
        state_nonces, revisions, archives = _runtime_pack_maps(
            state,
            error_type=self.error_type,
        )
        normalized_items = sorted(
            [dict(item) for item in items],
            key=lambda value: str(value["pack_id"]),
        )
        expected_inventory = [
            _inventory_row(item) for item in normalized_items
        ]
        expected_nonces = {
            str(item["pack_id"]): str(item["activation_nonce"])
            for item in normalized_items
        }
        expected_revisions = {
            str(item["pack_id"]): str(item["release_id"])
            for item in normalized_items
        }
        expected_archives = {
            str(item["pack_id"]): str(item["archive_sha256"])
            for item in normalized_items
        }
        if (
            drifted
            or dict(activation_nonces) != expected_nonces
            or state_nonces != expected_nonces
            or revisions != expected_revisions
            or archives != expected_archives
            or inventory != expected_inventory
        ):
            raise self.error_type("runtime_attestation_invalid")
        if (
            marker.get("schema_version")
            != MANAGED_RUNTIME_MARKER_SCHEMA_VERSION
            or marker.get("adapter_id") != self.adapter_id
            or marker.get("adapter_version")
            != self.adapter_version
            or not _runtime_marker_matches_history(
                self.managed_root,
                marker,
            )
        ):
            raise self.error_type("runtime_attestation_invalid")
        if (
            marker.get("active_state_sha256")
            != _state_digest(state)
            or marker.get("activation_marker")
            != state.get("activation_marker")
            or marker.get("activation_nonces") != expected_nonces
            or marker.get("active_revisions")
            != expected_revisions
            or marker.get("active_archive_sha256")
            != expected_archives
            or marker.get("observed_skills_tree_sha256")
            != observed_tree
            or marker.get("active_inventory_digest") != digest
        ):
            raise self.error_type("runtime_attestation_pending")
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

    @_translate_errors
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
            inventory, _, _, drifted = _runtime_active_inventory(
                state=state,
                skills_root=self.skills_root,
                adapter_id=self.adapter_id,
                adapter_version=self.adapter_version,
                error_type=self.error_type,
            )
        except ManagedFleetAdapterError:
            return True
        expected = sorted(
            [_inventory_row(item) for item in items],
            key=lambda value: str(value["pack_id"]),
        )
        return drifted or inventory != expected

    def detect_drift(self, item: Mapping[str, Any]) -> bool:
        return self.detect_inventory_drift([item])
