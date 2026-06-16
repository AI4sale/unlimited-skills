"""Tests for the Registered-tier Money Saved export (O064-09).

These prove the Registered export is a real, runnable, schema-versioned local
artifact built from the same safe aggregates as the Free meter, with a
fail-closed privacy gate and no upload/install-id surface.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pytest

from unlimited_skills.money_saved_meter import (
    REGISTERED_EXPORT_SCHEMA_VERSION,
    build_money_saved_meter_report,
    build_registered_export,
    registered_export_json,
)
from unlimited_skills.commands.money_saved import cmd_money_saved_registered_export

FIXED_TS = "2026-01-01T00:00:00Z"


def _export(tmp_path: Path) -> dict:
    return build_registered_export(tmp_path, generated_at=FIXED_TS)


def test_schema_version_and_tier(tmp_path):
    export = _export(tmp_path)
    assert export["schema_version"] == REGISTERED_EXPORT_SCHEMA_VERSION == "registered-export-v1"
    assert export["tier"] == "registered"
    assert export["export_type"] == "money_saved_registered_export"
    assert export["source"] == "money_saved_meter"


def test_body_carries_only_free_safe_aggregates(tmp_path):
    export = _export(tmp_path)
    body = export["body"]
    # Same safe aggregate fields the Free meter exposes — nothing more.
    assert set(body) == {"mode", "window", "measured_bytes", "estimates", "disabled_by_default"}
    assert body["window"]["target_call_count"] == 100
    assert body["window"]["cadence_not_billing_math"] is True


def test_privacy_block_is_fail_safe(tmp_path):
    priv = _export(tmp_path)["privacy"]
    assert priv["local_only"] is True
    assert priv["upload"] is False
    assert priv["hosted_telemetry"] is False
    # Every *_included flag must be False.
    for key, value in priv.items():
        if key.endswith("_included"):
            assert value is False, key


def test_no_install_or_machine_id_embedded(tmp_path):
    export = _export(tmp_path)
    ident = export["identity"]
    assert ident == {
        "install_id_included": False,
        "machine_id_included": False,
        "account_id_included": False,
    }
    # And no actual id value leaks anywhere in the serialized export.
    blob = registered_export_json(export).lower()
    assert "install_id" not in blob.replace("install_id_included", "")
    assert "machine_id" not in blob.replace("machine_id_included", "")


def test_no_upload_or_submit_surface(tmp_path):
    delivery = _export(tmp_path)["delivery"]
    assert delivery["produced_locally"] is True
    assert delivery["stays_local"] is True
    assert delivery["upload"] is False
    assert delivery["sync"] is False
    assert delivery["hosted_submit"] is False
    assert delivery["submit_verb_present"] is False


def test_deterministic_for_fixed_timestamp(tmp_path):
    a = registered_export_json(build_registered_export(tmp_path, generated_at=FIXED_TS))
    b = registered_export_json(build_registered_export(tmp_path, generated_at=FIXED_TS))
    assert a == b
    # Sorted-key JSON is stable.
    assert json.loads(a)["schema_version"] == "registered-export-v1"


def test_fail_closed_on_injected_forbidden_flag(tmp_path):
    export = _export(tmp_path)
    export["body"]["local_absolute_paths_included"] = True  # privacy violation
    with pytest.raises(RuntimeError):
        registered_export_json(export)


def test_free_meter_output_unchanged(tmp_path):
    # The Registered tier is strictly additive: the Free meter still builds.
    meter = build_money_saved_meter_report(tmp_path, generated_at=FIXED_TS)
    assert meter["report_type"] == "money_saved_meter"
    assert "tier" not in meter  # Free meter is not tagged as a tier export


def test_cli_command_writes_local_file(tmp_path):
    out = tmp_path / "registered-savings-export.json"
    args = argparse.Namespace(
        root=str(tmp_path),
        mode="current",
        mcp_savings_json="",
        audit_log="",
        target_calls=100,
        out=str(out),
        json_status=True,
    )
    rc = cmd_money_saved_registered_export(args)
    assert rc == 0
    assert out.is_file()
    written = json.loads(out.read_text(encoding="utf-8"))
    assert written["schema_version"] == "registered-export-v1"
    assert written["tier"] == "registered"
    assert written["privacy"]["local_only"] is True


def test_cli_command_stdout(tmp_path, capsys):
    args = argparse.Namespace(
        root=str(tmp_path),
        mode="current",
        mcp_savings_json="",
        audit_log="",
        target_calls=100,
        out="",
        json_status=False,
    )
    rc = cmd_money_saved_registered_export(args)
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["export_profile"] == "registered_local"
