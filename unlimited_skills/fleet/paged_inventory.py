"""Download an immutable desired-state document without a library-size cap."""
from __future__ import annotations

import base64
import hashlib
import json
import tempfile
from .contract import FleetContractError, verify_desired_state_signature

PAGE_BYTES = 96 * 1024


def download_desired(first, *, agent_id, installation_id, fetch, public_keys):
    if not isinstance(first, dict):
        raise FleetContractError("invalid_inventory_transfer")
    identity = {k: first.get(k) for k in ("format", "revision", "sha256", "size_bytes")}
    if (identity["format"] != "paged-inventory-v1" or
        type(identity["size_bytes"]) is not int or identity["size_bytes"] <= 0):
        raise FleetContractError("invalid_inventory_transfer")
    offset = 0
    digest = hashlib.sha256()
    page = first
    # Spill larger manifests to disk rather than reserving their announced size.
    with tempfile.SpooledTemporaryFile(max_size=1024 * 1024) as stream:
        while True:
            if not isinstance(page, dict) or any(page.get(k) != v for k, v in identity.items()):
                raise FleetContractError("inventory_transfer_changed")
            try:
                chunk = base64.b64decode(page["content_b64"], validate=True)
            except (ValueError, KeyError, TypeError) as exc:
                raise FleetContractError("inventory_page_invalid") from exc
            next_offset = offset + len(chunk)
            if (not chunk or len(chunk) > PAGE_BYTES or type(page.get("offset")) is not int or
                page["offset"] != offset or type(page.get("next_offset")) is not int or
                page["next_offset"] != next_offset or next_offset > identity["size_bytes"] or
                type(page.get("eof")) is not bool or page["eof"] != (next_offset == identity["size_bytes"]) or
                (not page["eof"] and len(chunk) != PAGE_BYTES)):
                raise FleetContractError("inventory_page_discontinuous")
            stream.write(chunk); digest.update(chunk); offset = next_offset
            if page["eof"]:
                break
            response = fetch({"revision": identity["revision"], "sha256": identity["sha256"], "offset": offset})
            if (response.get("agent_id") != agent_id or response.get("installation_id") != installation_id or
                response.get("desired_state") is not None):
                raise FleetContractError("inventory_page_binding_mismatch")
            page = response.get("desired_state_transfer")
        if "sha256:" + digest.hexdigest() != identity["sha256"]:
            raise FleetContractError("inventory_transfer_hash_mismatch")
        stream.seek(0)
        def unique(pairs):
            result = {}
            for key, value in pairs:
                if key in result:
                    raise FleetContractError("duplicate_json_property")
                result[key] = value
            return result
        try:
            desired = json.load(stream, object_pairs_hook=unique)
        except (ValueError, UnicodeDecodeError) as exc:
            raise FleetContractError("invalid_inventory_json") from exc
    verify_desired_state_signature(desired, public_keys=public_keys)
    if desired["agent_id"] != agent_id or desired["desired_state_revision"] != identity["revision"]:
        raise FleetContractError("inventory_transfer_binding_mismatch")
    return desired
