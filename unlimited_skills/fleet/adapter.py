"""Vendor-neutral local agent adapter interface.

This is a public local Python API.  It is deliberately not part of the JSON
wire protocol between the reconciler and the private registry.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Protocol, runtime_checkable


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
