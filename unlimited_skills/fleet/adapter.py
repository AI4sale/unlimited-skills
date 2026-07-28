"""Vendor-neutral local agent adapter interface.

This is a public local Python API.  It is deliberately not part of the JSON
wire protocol between the reconciler and the private registry.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Protocol, runtime_checkable


class ManagedFleetAdapterError(RuntimeError):
    """Base error for local managed-runtime adapter failures."""


@dataclass(frozen=True)
class InstalledRevision:
    pack_id: str
    release_id: str
    version: str
    archive_sha256: str
    install_committed: bool
    metadata: Mapping[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class RuntimeInventory:
    runtime_generation: str
    active_revisions: Mapping[str, str]
    inventory_digest: str


@dataclass(frozen=True)
class RuntimeAttestation:
    runtime_generation: str
    activation_nonce: str
    pack_id: str
    release_id: str
    active_archive_sha256: str
    active_inventory_digest: str
    adapter_version: str


@dataclass(frozen=True)
class RuntimeInventoryAttestation:
    """Evidence that one runtime generation loaded an exact pack inventory."""

    runtime_generation: str
    activation_nonces: Mapping[str, str]
    active_revisions: Mapping[str, str]
    active_archive_sha256: Mapping[str, str]
    active_inventory_digest: str
    adapter_version: str


@runtime_checkable
class AgentAdapter(Protocol):
    """Finite adapter surface available to the reconciler."""

    adapter_id: str
    adapter_version: str

    def discover(self) -> RuntimeInventory:
        """Return the current managed runtime generation and active inventory."""

    def install_revision(self, item: Mapping[str, Any]) -> InstalledRevision:
        """Install a revision into a managed side-by-side location."""

    def verify_revision(self, item: Mapping[str, Any], installed: InstalledRevision) -> None:
        """Verify the manifest and artifact before activation."""

    def activate_revision(
        self,
        item: Mapping[str, Any],
        installed: InstalledRevision,
        *,
        activation_nonce: str,
    ) -> None:
        """Atomically select an installed revision for the managed runtime."""

    def attest_runtime(
        self,
        item: Mapping[str, Any],
        *,
        activation_nonce: str,
    ) -> RuntimeAttestation:
        """Return post-activation evidence from the current runtime generation."""

    def detect_drift(self, item: Mapping[str, Any]) -> bool:
        """Return True when managed runtime state differs from the desired item."""

    def rollback_revision(
        self,
        item: Mapping[str, Any],
        installed: InstalledRevision,
        *,
        activation_nonce: str,
    ) -> None:
        """Atomically activate an older signed revision for a new rollout."""


@runtime_checkable
class InventoryAgentAdapter(AgentAdapter, Protocol):
    """Adapter extension for atomic multi-pack desired-state activation."""

    def activate_inventory(
        self,
        items: list[Mapping[str, Any]],
        installed: Mapping[str, InstalledRevision],
        *,
        activation_nonces: Mapping[str, str],
    ) -> None:
        """Atomically replace the complete managed runtime inventory."""

    def attest_inventory(
        self,
        items: list[Mapping[str, Any]],
        *,
        activation_nonces: Mapping[str, str],
    ) -> RuntimeInventoryAttestation:
        """Return proof for the complete inventory from one runtime generation."""

    def detect_inventory_drift(
        self,
        items: list[Mapping[str, Any]],
    ) -> bool:
        """Return True when the active runtime differs from the full target."""
