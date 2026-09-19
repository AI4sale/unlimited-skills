"""Durable per-package progress; a failed peer never resets completed work."""
from __future__ import annotations

from .adapter import InstalledRevision, ManagedFleetAdapterError, RuntimeAttestation

CAPABILITY = "independent-items-v1"


def reconcile_independent(owner, desired, inventory, *, already_seen):
    from .reconciler import ReconcileError, _adapter_failure_receipt
    adapter = owner.adapter
    if not callable(getattr(adapter, "activate_independent", None)):
        raise ReconcileError("adapter_independent_activation_required")
    receipts = []
    pending = False
    # The receipt spool persists each item immediately, including across a
    # process crash. The epoch checkpoint is not a batch-completion flag.
    owner._write_epoch_state(desired, already_seen=already_seen)
    for raw in desired["items"]:
        context = desired.get("attempt_contexts", {}).get(raw["attempt_id"], desired)
        item = {**raw, "agent_id": desired["agent_id"],
                "rollout_id": context["rollout_id"],
                "desired_state_revision": context["desired_state_revision"]}
        builder = owner._receipt_builder(context, item)
        last = owner.spool.last_event_type(item["attempt_id"])
        if last in {"FAILED_TERMINAL", "REJECTED"}:
            pending = True
            continue
        if last == "RUNTIME_ATTESTED" and owner.spool.last_runtime_generation(item["attempt_id"]) == inventory.runtime_generation:
            continue
        try:
            if last not in {"INSTALL_COMMITTED", "ACTIVATION_PENDING", "RUNTIME_ATTESTED"}:
                if not last or last == "FAILED_RETRYABLE":
                    owner._spool_receipt(receipts, builder, "DESIRED_SEEN", runtime_generation=inventory.runtime_generation)
                    last = "DESIRED_SEEN"
                revision = adapter.install_revision(item)
                if (not isinstance(revision, InstalledRevision) or not revision.install_committed
                    or (revision.pack_id, revision.release_id, revision.version, revision.archive_sha256) !=
                    (item["pack_id"], item["release_id"], item["version"], item["archive_sha256"])):
                    raise ReconcileError("install_failed")
                adapter.verify_revision(item, revision)
                milestones = ["DESIRED_SEEN", "MANIFEST_VERIFIED", "ARTIFACT_VERIFIED", "INSTALL_COMMITTED"]
                for event in milestones[milestones.index(last) + 1:]:
                    owner._spool_receipt(receipts, builder, event)
                last = "INSTALL_COMMITTED"
            if not owner.auto_activate:
                pending = True
                continue
            if last == "INSTALL_COMMITTED":
                adapter.activate_independent(item)
                owner._spool_receipt(receipts, builder, "ACTIVATION_PENDING",
                    reason_code="activation_pending", activation_nonce=item["activation_nonce"])
        except ManagedFleetAdapterError as exc:
            event, reason = _adapter_failure_receipt(exc)
            owner._spool_receipt(receipts, builder, event, reason_code=reason)
            pending = True
            continue
        except Exception as exc:
            event = "FAILED_TERMINAL" if isinstance(exc, ReconcileError) else "FAILED_RETRYABLE"
            owner._spool_receipt(receipts, builder, event,
                reason_code="install_failed" if isinstance(exc, ReconcileError) else "adapter_unavailable")
            pending = True
            continue
    # Attest only after all independent activations, so every receipt refers to
    # the runtime generation that actually loaded that package. Activation is
    # useful immediately; missing runtime evidence is never fabricated.
    for raw in desired["items"]:
        last = owner.spool.last_event_type(raw["attempt_id"])
        if last not in {"ACTIVATION_PENDING", "RUNTIME_ATTESTED"}:
            continue
        context = desired.get("attempt_contexts", {}).get(raw["attempt_id"], desired)
        item = {**raw, "agent_id": desired["agent_id"], "rollout_id": context["rollout_id"],
                "desired_state_revision": context["desired_state_revision"]}
        try:
            proof = adapter.attest_independent(item)
            if (not isinstance(proof, RuntimeAttestation) or
                (proof.pack_id, proof.release_id, proof.active_archive_sha256, proof.activation_nonce, proof.adapter_version) !=
                (item["pack_id"], item["release_id"], item["archive_sha256"], item["activation_nonce"], adapter.adapter_version)):
                raise ReconcileError("runtime_attestation_invalid")
            if last == "RUNTIME_ATTESTED" and owner.spool.last_runtime_generation(item["attempt_id"]) == proof.runtime_generation:
                continue
            owner._spool_receipt(receipts, owner._receipt_builder(context, item), "RUNTIME_ATTESTED",
                runtime_generation=proof.runtime_generation, activation_nonce=proof.activation_nonce,
                active_archive_sha256=proof.active_archive_sha256,
                active_inventory_digest=proof.active_inventory_digest)
        except ManagedFleetAdapterError as exc:
            pending = True
            if str(exc) != "runtime_attestation_pending":
                event, reason = _adapter_failure_receipt(exc)
                owner._spool_receipt(receipts, owner._receipt_builder(context, item), event, reason_code=reason)
        except ReconcileError:
            pending = True
            owner._spool_receipt(receipts, owner._receipt_builder(context, item), "FAILED_TERMINAL", reason_code="runtime_attestation_invalid")
    return owner._result(desired, receipts, activation_pending=pending, already_seen=True)
