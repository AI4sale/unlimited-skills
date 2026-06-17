"""Local Money Saved Meter command wrappers."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def cmd_money_saved_meter(args: argparse.Namespace) -> int:
    if _use_meter_v2(args):
        return _cmd_meter_v2(args)
    from .. import cli
    from ..money_saved_meter import (
        build_100_call_value_report_fixture,
        build_money_saved_meter_report,
        format_money_saved_meter_markdown,
        load_optional_report,
        money_saved_meter_json,
        write_report,
    )

    root = Path(args.root).expanduser()
    cli.enforce_local_root(root, action="money-saved meter library root")
    if args.fixture_100_call:
        report = build_100_call_value_report_fixture()
    else:
        mcp_savings_report = load_optional_report(args.mcp_savings_json)
        compare_report = load_optional_report(args.compare)
        audit_log = Path(args.audit_log).expanduser() if args.audit_log else None
        report = build_money_saved_meter_report(
            root,
            mode=args.mode,
            mcp_savings_report=mcp_savings_report,
            audit_log=audit_log,
            compare_report=compare_report,
            target_call_count=args.target_calls,
        )
    text = money_saved_meter_json(report) if args.json else format_money_saved_meter_markdown(report)
    if args.out:
        write_report(Path(args.out), text)
        if args.json_status:
            print(json.dumps({"schema_version": 1, "written": True, "format": "json" if args.json else "markdown"}, indent=2))
        else:
            print(f"Money Saved Meter report written ({'json' if args.json else 'markdown'}).")
        return 0
    print(text, end="")
    return 0


def cmd_money_saved_registered_export(args: argparse.Namespace) -> int:
    if _use_registered_export_v2(args):
        return _cmd_registered_export_v2(args)
    from .. import cli
    from ..money_saved_meter import (
        REGISTERED_EXPORT_SCHEMA_VERSION,
        build_registered_export,
        load_optional_report,
        registered_export_json,
        write_report,
    )

    root = Path(args.root).expanduser()
    cli.enforce_local_root(root, action="money-saved registered-export library root")
    mcp_savings_report = load_optional_report(args.mcp_savings_json)
    audit_log = Path(args.audit_log).expanduser() if args.audit_log else None
    export = build_registered_export(
        root,
        mode=args.mode,
        mcp_savings_report=mcp_savings_report,
        audit_log=audit_log,
        target_call_count=args.target_calls,
    )
    text = registered_export_json(export)
    if args.out:
        write_report(Path(args.out), text)
        if args.json_status:
            print(json.dumps({"schema_version": REGISTERED_EXPORT_SCHEMA_VERSION, "written": True, "format": "json"}, indent=2))
        else:
            print(f"Registered Money Saved export written ({args.out}).")
        return 0
    print(text, end="")
    return 0


def cmd_money_saved_team_rollup(args: argparse.Namespace) -> int:
    from .. import cli
    from ..money_saved_meter import write_report
    from ..money_saved_tiers import (
        MSM_TEAM_ROLLUP_SCHEMA_VERSION,
        IncompatibleExportError,
        build_money_saved_team_rollup,
        money_saved_team_rollup_json,
    )

    root = Path(args.root).expanduser()
    cli.enforce_local_root(root, action="money-saved team-rollup library root")
    inputs = [Path(p) for p in (args.input or [])]
    if not inputs:
        print("No --input exports provided. Pass one or more Registered Money Saved export files.")
        return 2
    if _detect_schema(inputs[0]) == "money-saved-registered-export-v2":  # Real Money Saved (v2) path
        return _cmd_team_rollup_v2(args, inputs)
    aliases = list(args.alias) if getattr(args, "alias", None) else None
    try:
        rollup = build_money_saved_team_rollup(inputs, aliases=aliases)
    except IncompatibleExportError as exc:
        print(f"Rejected incompatible input: {exc}")
        return 2
    text = money_saved_team_rollup_json(rollup)
    if args.out:
        write_report(Path(args.out), text)
        if getattr(args, "json_status", False):
            print(json.dumps({"schema_version": MSM_TEAM_ROLLUP_SCHEMA_VERSION, "written": True, "format": "json"}, indent=2))
        else:
            print(f"Money Saved team rollup written ({args.out}).")
        return 0
    print(text, end="")
    return 0


def cmd_money_saved_admin_export(args: argparse.Namespace) -> int:
    from .. import cli
    from ..money_saved_meter import write_report
    from ..money_saved_tiers import (
        IncompatibleExportError,
        build_money_saved_admin_export,
        money_saved_admin_export_csv,
        money_saved_admin_export_json,
    )

    root = Path(args.root).expanduser()
    cli.enforce_local_root(root, action="money-saved admin-export library root")
    if not args.input:
        print("No --input team rollup provided.")
        return 2
    if _detect_schema(Path(args.input)) == "money-saved-team-rollup-v2":  # Real Money Saved (v2) path
        return _cmd_admin_export_v2(args)
    labels = None
    if getattr(args, "labels", ""):
        try:
            labels = json.loads(Path(args.labels).expanduser().read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            print(f"Could not read --labels file: {exc.__class__.__name__}.")
            return 2
    try:
        export = build_money_saved_admin_export(Path(args.input), labels=labels)
    except IncompatibleExportError as exc:
        print(f"Rejected incompatible input: {exc}")
        return 2

    json_text = money_saved_admin_export_json(export)
    csv_text = money_saved_admin_export_csv(export)
    wrote = False
    if getattr(args, "csv", ""):
        write_report(Path(args.csv), csv_text)
        wrote = True
    if getattr(args, "json", ""):
        write_report(Path(args.json), json_text)
        wrote = True
    if wrote:
        print(f"Money Saved admin export written (rows={export['measured']['row_count']}).")
        return 0
    print(json_text, end="")
    return 0


def cmd_money_saved_evidence_pack(args: argparse.Namespace) -> int:
    from .. import cli
    from ..money_saved_tiers import (
        IncompatibleExportError,
        build_money_saved_evidence_pack,
        write_money_saved_evidence_pack,
    )

    root = Path(args.root).expanduser()
    cli.enforce_local_root(root, action="money-saved evidence-pack library root")
    if not args.input:
        print("No --input admin export provided.")
        return 2
    if not args.out:
        print("No --out directory provided for the evidence pack.")
        return 2
    if _detect_schema(Path(args.input)) == "money-saved-admin-export-v2":  # Real Money Saved (v2) path
        return _cmd_evidence_pack_v2(args)
    try:
        pack = build_money_saved_evidence_pack(Path(args.input))
    except IncompatibleExportError as exc:
        print(f"Rejected incompatible input: {exc}")
        return 2
    written = write_money_saved_evidence_pack(pack, Path(args.out))
    print(json.dumps({
        "evidence_pack_written": True,
        "out_dir": str(args.out),
        "files": written,
        "reproducibility_hash": pack["reproducibility_hash"],
    }, indent=2))
    return 0


def cmd_money_saved_verify_evidence_pack(args: argparse.Namespace) -> int:
    from .. import cli
    from ..money_saved_tiers import verify_money_saved_evidence_pack

    root = Path(args.root).expanduser()
    cli.enforce_local_root(root, action="money-saved verify-evidence-pack library root")
    if not args.input:
        print("No --input evidence-pack directory provided.")
        return 2
    if _detect_schema(Path(args.input) / "manifest.json") == "money-saved-evidence-pack-v2":  # Real Money Saved (v2)
        return _cmd_verify_evidence_pack_v2(args)
    report = verify_money_saved_evidence_pack(Path(args.input))
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if report.get("ok") else 1


# --- v2: Real Money Saved (O064-R2) -------------------------------------------

def _print_json(obj) -> None:
    print(json.dumps(obj, ensure_ascii=False, indent=2, sort_keys=True))


def _detect_schema(path: Path) -> str:
    try:
        return str(json.loads(path.read_text(encoding="utf-8")).get("schema_version", ""))
    except (OSError, json.JSONDecodeError):
        return ""


def _include_flags(args: argparse.Namespace) -> tuple[bool, bool]:
    inc_skills = bool(getattr(args, "include_skills", False))
    inc_mcp = bool(getattr(args, "include_mcp", False))
    if not inc_skills and not inc_mcp:  # neither named -> include both
        return True, True
    return inc_skills, inc_mcp


def _use_meter_v2(args: argparse.Namespace) -> bool:
    """Use Real Money Saved by default.

    The legacy v0.6.4 proxy meter remains only for explicit before/after
    compatibility options. The normal product path must work without user model
    configuration: exact runtime binding when visible, supported-agent assumption
    profile when hidden.
    """
    if getattr(args, "fixture_100_call", False):
        return False
    if getattr(args, "mcp_savings_json", "") or getattr(args, "compare", "") or getattr(args, "audit_log", ""):
        return False
    if getattr(args, "mode", "current") != "current":
        return False
    if int(getattr(args, "target_calls", 100) or 100) != 100:
        return False
    return True


def _use_registered_export_v2(args: argparse.Namespace) -> bool:
    if getattr(args, "mcp_savings_json", "") or getattr(args, "audit_log", ""):
        return False
    if getattr(args, "mode", "current") != "current":
        return False
    if int(getattr(args, "target_calls", 100) or 100) != 100:
        return False
    return bool(
        getattr(args, "model", "")
        or getattr(args, "alias", "")
        or getattr(args, "include_skills", False)
        or getattr(args, "include_mcp", False)
        or getattr(args, "price_class", "")
        or int(getattr(args, "event_count", 1) or 1) != 1
        or getattr(args, "token_counter", "anthropic") != "anthropic"
    )


def cmd_money_saved_model_detect(args: argparse.Namespace) -> int:
    from ..model_detect import bind_model, model_detect_report

    report = model_detect_report(bind_model(getattr(args, "model", "") or None))
    _print_json(report)
    # Supported agent with no binding is an integration bug -> exit 2.
    return 0 if report.get("available") else 2


def cmd_money_saved_prices(args: argparse.Namespace) -> int:
    from ..money_pricing import iter_prices, resolve_model

    if getattr(args, "prices_action", "list") == "show":
        price = resolve_model(getattr(args, "model", "") or "", allow_todo=True)
        if price is None:
            _print_json({"ok": False, "error": "model_not_found", "model": getattr(args, "model", "")})
            return 2
        _print_json({
            "ok": True, "provider": price.provider, "model": price.model, "status": price.status,
            "currency": price.currency, "aliases": list(price.aliases),
            "base_input_per_1m": price.base_input_per_1m, "cache_write_5m_per_1m": price.cache_write_5m_per_1m,
            "cache_write_1h_per_1m": price.cache_write_1h_per_1m, "cache_hit_refresh_per_1m": price.cache_hit_refresh_per_1m,
            "output_per_1m": price.output_per_1m, "source_url": price.source_url, "source_date": price.source_date,
        })
        return 0
    rows = [{
        "provider": p.provider, "model": p.model, "status": p.status, "currency": p.currency,
        "base_input_per_1m": p.base_input_per_1m, "output_per_1m": p.output_per_1m, "source_date": p.source_date,
    } for p in iter_prices()]
    _print_json({"schema_version": "money-saved-prices-list-v1", "count": len(rows), "prices": rows})
    return 0


def cmd_money_saved_events(args: argparse.Namespace) -> int:
    from ..money_events import build_event, events_inspect, money_saved_dir, record_event

    if getattr(args, "events_action", "inspect") == "record-fixture":
        directory = money_saved_dir()
        count = max(1, int(getattr(args, "event_count", 3)))
        for i in range(count):
            event_type = "session_start" if i == 0 else "compaction"
            record_event(build_event(
                agent="claude-code", event_type=event_type, provider="anthropic",
                model=getattr(args, "model", "") or "claude-opus-4.8", model_source="fixture",
                currency="USD", price_source_date="2026-06-17", token_counter_method="anthropic_count_tokens",
                skills={"visible_skill_count": 372, "baseline_tokens": 18110, "actual_router_tokens": 60},
                mcp={"baseline_tokens": 0, "actual_gateway_tokens": 0},
            ), directory)
        _print_json({"ok": True, "recorded": count, "dir": str(directory)})
        return 0
    _print_json(events_inspect())
    return 0


def _meter_v2_report(args: argparse.Namespace):
    from ..money_saved_meter_v2 import build_meter_v2

    inc_skills, inc_mcp = _include_flags(args)
    return build_meter_v2(
        model=getattr(args, "model", "") or None,
        include_skills=inc_skills, include_mcp=inc_mcp,
        token_counter=getattr(args, "token_counter", "anthropic"),
        event_count=int(getattr(args, "event_count", 1) or 1),
        price_class=getattr(args, "price_class", "") or None,
        root=Path(args.root).expanduser(),
    )


def _cmd_meter_v2(args: argparse.Namespace) -> int:
    from .. import cli
    from ..money_saved_meter import write_report

    root = Path(args.root).expanduser()
    cli.enforce_local_root(root, action="money-saved meter library root")
    report = _meter_v2_report(args)
    # Headline = MEASURED money from real recorded events (session starts + compactions),
    # not the per-event 'rate' above. Empty until the hooks have recorded events.
    if report.get("available"):
        try:
            from ..model_detect import bind_model
            from ..money_events import load_summary
            from ..money_saved_meter_v2 import money_from_summary
            binding = bind_model(getattr(args, "model", "") or None, agent=getattr(args, "agent", "") or None)
            if binding.price is not None:
                report["measured"] = money_from_summary(
                    load_summary(), binding.price, provider=binding.provider, model=binding.model
                )
        except Exception:
            pass
    text = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True)
    if getattr(args, "out", ""):
        write_report(Path(args.out), text + "\n")
        print(f"Money Saved meter v2 written ({args.out}).")
        return 0
    print(text)
    return 0 if report.get("available") else 2


def _cmd_registered_export_v2(args: argparse.Namespace) -> int:
    from .. import cli
    from ..money_saved_meter import write_report
    from ..money_saved_tiers_v2 import build_registered_export_v2

    root = Path(args.root).expanduser()
    cli.enforce_local_root(root, action="money-saved registered-export library root")
    meter = _meter_v2_report(args)
    if not meter.get("available"):
        _print_json(meter)
        return 2
    export = build_registered_export_v2(meter, alias=getattr(args, "alias", "") or "unknown")
    text = json.dumps(export, ensure_ascii=False, indent=2, sort_keys=True)
    if getattr(args, "out", ""):
        write_report(Path(args.out), text + "\n")
        print(f"Registered Money Saved export v2 written ({args.out}).")
        return 0
    print(text)
    return 0


def _cmd_team_rollup_v2(args: argparse.Namespace, inputs: list) -> int:
    from ..money_saved_meter import write_report
    from ..money_saved_tiers_v2 import (
        IncompatibleExportError, build_team_rollup_v2, load_registered_export_v2,
    )

    exports = []
    for path in inputs:
        try:
            exports.append(load_registered_export_v2(path))
        except (IncompatibleExportError, OSError) as exc:
            print(f"Rejected incompatible input {path}: {exc}")
            return 2
    rollup = build_team_rollup_v2(exports)
    text = json.dumps(rollup, ensure_ascii=False, indent=2, sort_keys=True)
    if getattr(args, "out", ""):
        write_report(Path(args.out), text + "\n")
        print(f"Money Saved team rollup v2 written ({args.out}).")
        return 0
    print(text)
    return 0


def _cmd_admin_export_v2(args: argparse.Namespace) -> int:
    from ..money_saved_meter import write_report
    from ..money_saved_tiers_v2 import (
        admin_export_v2_csv, admin_export_v2_json, build_admin_export_v2,
    )

    rollup = json.loads(Path(args.input).expanduser().read_text(encoding="utf-8"))
    labels = None
    if getattr(args, "labels", ""):
        try:
            labels = json.loads(Path(args.labels).expanduser().read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            print(f"Could not read --labels file: {exc.__class__.__name__}.")
            return 2
    export = build_admin_export_v2(rollup, labels=labels)
    json_text = admin_export_v2_json(export)
    csv_text = admin_export_v2_csv(export)
    wrote = False
    if getattr(args, "csv", ""):
        write_report(Path(args.csv), csv_text)
        wrote = True
    if getattr(args, "json", ""):
        write_report(Path(args.json), json_text)
        wrote = True
    if wrote:
        print(f"Money Saved admin export v2 written (rows={export['row_count']}).")
        return 0
    print(json_text, end="")
    return 0


def _cmd_evidence_pack_v2(args: argparse.Namespace) -> int:
    from ..money_evidence_pack import write_evidence_pack

    admin = json.loads(Path(args.input).expanduser().read_text(encoding="utf-8"))
    manifest = write_evidence_pack(admin, Path(args.out))
    _print_json({"evidence_pack_written": True, "out_dir": str(args.out),
                 "files": [f["name"] for f in manifest["files"]] + ["manifest.json"],
                 "pack_sha256": manifest["pack_sha256"]})
    return 0


def _cmd_verify_evidence_pack_v2(args: argparse.Namespace) -> int:
    from ..money_evidence_pack import verify_evidence_pack

    report = verify_evidence_pack(Path(args.input))
    _print_json(report)
    return int(report.get("exit_code", 1))


def cmd_money_saved_record_event(args: argparse.Namespace) -> int:
    """Record ONE real context-load event (session_start / compaction / ...).

    The shared, agent-agnostic entrypoint that every host's lifecycle calls:
    Claude Code SessionStart/PreCompact hooks, and Codex/OpenClaw/Hermes from
    their own session lifecycle. Best-effort: it must NEVER break a session, so
    any failure is swallowed and reported as ok=false.
    """
    try:
        from ..mcp_savings import build_mcp_savings, gateway_is_configured
        from ..model_detect import bind_model
        from ..money_events import build_event, record_event
        from ..skills_savings import build_skills_savings

        root = Path(args.root).expanduser()
        binding = bind_model(getattr(args, "model", "") or None, agent=getattr(args, "agent", "") or None)
        if not binding.available or binding.price is None:
            _print_json({"ok": False, "reason": "model_binding_missing", "agent": binding.agent})
            return 0
        price = binding.price
        sk = build_skills_savings(provider=price.provider, model_api_id=None, root=root)
        mcp = {"baseline_tokens": 0, "actual_gateway_tokens": 0}
        if gateway_is_configured():  # MCP only counted behind our gateway
            m = build_mcp_savings(provider=price.provider)
            mcp = {"baseline_tokens": int(m["baseline_tokens"]), "actual_gateway_tokens": int(m["actual_gateway_tokens"])}
        event = build_event(
            agent=binding.agent, event_type=getattr(args, "event_type", "session_start"),
            provider=price.provider, model=price.model, model_source=binding.source,
            currency=price.currency, price_source_date=price.source_date,
            token_counter_method=sk["token_counter"]["method"],
            skills={"visible_skill_count": sk["baseline_skill_count"],
                    "baseline_tokens": sk["baseline_tokens"], "actual_router_tokens": sk["actual_router_tokens"]},
            mcp=mcp,
        )
        summary = record_event(event)
        _print_json({"ok": True, "event_type": event["event_type"], "agent": binding.agent,
                     "model": price.model, "price_class": event["cache"]["price_class"],
                     "counter_genesis_at": summary.get("counter_genesis_at")})
    except Exception as exc:  # never break the host session
        _print_json({"ok": False, "reason": "record_failed", "error": exc.__class__.__name__})
    return 0
