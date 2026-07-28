"""Atomic offline spool for fleet receipt events."""

from __future__ import annotations

import json
import os
import re
import tempfile
from pathlib import Path
from typing import Any, Iterable, Mapping

from .contract import FleetContractError, parse_json_strict, validate_contract_message
from .privacy import FleetPrivacyError, assert_receipt_metadata_safe


_EVENT_FILE_RE = re.compile(r"^evt_[A-Za-z0-9._-]{1,156}\.json$")


class ReceiptSpoolError(RuntimeError):
    pass


class ReceiptSpool:
    def __init__(self, root: Path) -> None:
        self.root = Path(root)

    def _ensure_root(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        try:
            os.chmod(self.root, 0o700)
        except OSError:
            pass

    def append(self, receipt: Mapping[str, Any]) -> Path:
        try:
            normalized = validate_contract_message(receipt)
            assert_receipt_metadata_safe(normalized)
        except (FleetContractError, FleetPrivacyError) as exc:
            raise ReceiptSpoolError(str(exc)) from exc
        event_id = str(normalized["event_id"])
        filename = f"{event_id}.json"
        if not _EVENT_FILE_RE.fullmatch(filename):
            raise ReceiptSpoolError("unsafe_event_id")
        self._ensure_root()
        target = self.root / filename
        payload = (
            json.dumps(normalized, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            + "\n"
        ).encode("utf-8")
        if target.is_symlink():
            raise ReceiptSpoolError("unsafe_receipt_target")
        if target.exists():
            if target.read_bytes() == payload:
                return target
            raise ReceiptSpoolError("event_id_collision")
        fd, temporary_name = tempfile.mkstemp(prefix=".receipt-", suffix=".tmp", dir=self.root)
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
            try:
                os.link(temporary, target)
            except FileExistsError:
                if target.is_symlink():
                    raise ReceiptSpoolError("unsafe_receipt_target")
                if target.read_bytes() == payload:
                    return target
                raise ReceiptSpoolError("event_id_collision")
        finally:
            if temporary.exists():
                temporary.unlink()
        return target

    def pending(self, *, limit: int = 256) -> list[dict[str, Any]]:
        if not self.root.is_dir():
            return []
        safe_limit = max(1, min(int(limit), 256))
        output: list[dict[str, Any]] = []
        for path in self.root.glob("evt_*.json"):
            if not _EVENT_FILE_RE.fullmatch(path.name) or path.is_symlink():
                continue
            try:
                payload = parse_json_strict(path.read_bytes())
                normalized = validate_contract_message(payload)
                assert_receipt_metadata_safe(normalized)
            except (OSError, FleetContractError, FleetPrivacyError) as exc:
                raise ReceiptSpoolError(f"invalid_spooled_receipt:{path.name}") from exc
            output.append(normalized)
        output.sort(
            key=lambda item: (
                str(item["attempt_id"]),
                int(item["event_seq"]),
                str(item["event_id"]),
            )
        )
        return output[:safe_limit]

    def acknowledge(self, event_ids: Iterable[str]) -> int:
        if not self.root.is_dir():
            return 0
        removed = 0
        for event_id in sorted(set(str(value) for value in event_ids)):
            filename = f"{event_id}.json"
            if not _EVENT_FILE_RE.fullmatch(filename):
                raise ReceiptSpoolError("unsafe_event_id")
            path = self.root / filename
            try:
                path.unlink()
            except FileNotFoundError:
                continue
            removed += 1
        return removed
