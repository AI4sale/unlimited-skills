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
_SEQUENCE_STATE_FILENAME = "sequence-state.json"


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

    @property
    def _sequence_state_path(self) -> Path:
        return self.root / _SEQUENCE_STATE_FILENAME

    def _read_sequence_state(self) -> dict[str, tuple[int, str]]:
        path = self._sequence_state_path
        if not path.exists():
            return {}
        if path.is_symlink() or not path.is_file():
            raise ReceiptSpoolError("unsafe_sequence_state")
        try:
            payload = parse_json_strict(path.read_bytes())
        except (OSError, FleetContractError) as exc:
            raise ReceiptSpoolError("invalid_sequence_state") from exc
        if (
            not isinstance(payload, dict)
            or payload.get("schema_version") not in {1, 2}
            or set(payload) != {"schema_version", "attempts"}
            or not isinstance(payload.get("attempts"), dict)
        ):
            raise ReceiptSpoolError("invalid_sequence_state")
        schema_version = int(payload["schema_version"])
        output: dict[str, tuple[int, str]] = {}
        for attempt_id, value in payload["attempts"].items():
            if schema_version == 1:
                event_seq = value
                event_type = ""
            elif (
                isinstance(value, dict)
                and set(value) == {"event_seq", "event_type"}
            ):
                event_seq = value["event_seq"]
                event_type = value["event_type"]
            else:
                raise ReceiptSpoolError("invalid_sequence_state")
            if (
                not isinstance(attempt_id, str)
                or not attempt_id
                or isinstance(event_seq, bool)
                or not isinstance(event_seq, int)
                or event_seq < 1
                or not isinstance(event_type, str)
                or len(event_type) > 64
            ):
                raise ReceiptSpoolError("invalid_sequence_state")
            output[attempt_id] = (event_seq, event_type)
        return output

    def _write_sequence_state(
        self,
        attempts: Mapping[str, tuple[int, str]],
    ) -> None:
        self._ensure_root()
        target = self._sequence_state_path
        if target.is_symlink():
            raise ReceiptSpoolError("unsafe_sequence_state")
        serialized = {
            attempt_id: {
                "event_seq": event_seq,
                "event_type": event_type,
            }
            for attempt_id, (event_seq, event_type) in attempts.items()
        }
        payload = (
            json.dumps(
                {"schema_version": 2, "attempts": serialized},
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
            + "\n"
        ).encode("utf-8")
        fd, temporary_name = tempfile.mkstemp(
            prefix=".sequence-state-",
            suffix=".tmp",
            dir=self.root,
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
            os.replace(temporary, target)
        finally:
            if temporary.exists():
                temporary.unlink()

    def _record_event_sequence(self, receipt: Mapping[str, Any]) -> None:
        attempt_id = str(receipt["attempt_id"])
        event_seq = int(receipt["event_seq"])
        event_type = str(receipt["event_type"])
        attempts = self._read_sequence_state()
        current_seq, current_type = attempts.get(attempt_id, (0, ""))
        if event_seq < current_seq:
            return
        if event_seq == current_seq:
            if current_type == event_type:
                return
            if current_type:
                raise ReceiptSpoolError("sequence_event_conflict")
        attempts[attempt_id] = (event_seq, event_type)
        self._write_sequence_state(attempts)

    def _all_pending(self) -> list[dict[str, Any]]:
        if not self.root.is_dir():
            return []
        output: list[dict[str, Any]] = []
        for path in self.root.glob("evt_*.json"):
            if not _EVENT_FILE_RE.fullmatch(path.name) or path.is_symlink():
                continue
            try:
                payload = parse_json_strict(path.read_bytes())
                normalized = validate_contract_message(payload)
                assert_receipt_metadata_safe(normalized)
            except (OSError, FleetContractError, FleetPrivacyError) as exc:
                raise ReceiptSpoolError(
                    f"invalid_spooled_receipt:{path.name}"
                ) from exc
            output.append(normalized)
        output.sort(
            key=lambda item: (
                str(item["attempt_id"]),
                int(item["event_seq"]),
                str(item["event_id"]),
            )
        )
        return output

    def last_event_sequence(self, attempt_id: str) -> int:
        safe_attempt_id = str(attempt_id)
        if not safe_attempt_id:
            raise ReceiptSpoolError("invalid_attempt_id")
        highest = self._read_sequence_state().get(
            safe_attempt_id,
            (0, ""),
        )[0]
        for receipt in self._all_pending():
            if receipt["attempt_id"] == safe_attempt_id:
                highest = max(highest, int(receipt["event_seq"]))
        return highest

    def last_event_type(self, attempt_id: str) -> str:
        safe_attempt_id = str(attempt_id)
        if not safe_attempt_id:
            raise ReceiptSpoolError("invalid_attempt_id")
        highest, event_type = self._read_sequence_state().get(
            safe_attempt_id,
            (0, ""),
        )
        for receipt in self._all_pending():
            if receipt["attempt_id"] != safe_attempt_id:
                continue
            receipt_seq = int(receipt["event_seq"])
            receipt_type = str(receipt["event_type"])
            if receipt_seq > highest:
                highest = receipt_seq
                event_type = receipt_type
            elif receipt_seq == highest:
                if event_type and event_type != receipt_type:
                    raise ReceiptSpoolError("sequence_event_conflict")
                event_type = receipt_type
        return event_type

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
                self._record_event_sequence(normalized)
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
                    self._record_event_sequence(normalized)
                    return target
                raise ReceiptSpoolError("event_id_collision")
        finally:
            if temporary.exists():
                temporary.unlink()
        self._record_event_sequence(normalized)
        return target

    def pending(self, *, limit: int = 256) -> list[dict[str, Any]]:
        safe_limit = max(1, min(int(limit), 256))
        return self._all_pending()[:safe_limit]

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
                payload = parse_json_strict(path.read_bytes())
                normalized = validate_contract_message(payload)
                assert_receipt_metadata_safe(normalized)
                self._record_event_sequence(normalized)
                path.unlink()
            except FileNotFoundError:
                continue
            except (OSError, FleetContractError, FleetPrivacyError) as exc:
                raise ReceiptSpoolError(
                    f"invalid_spooled_receipt:{path.name}"
                ) from exc
            removed += 1
        return removed
