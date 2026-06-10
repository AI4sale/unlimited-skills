"""Organization, plan, billing, and enhancement commands."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from unlimited_skills.billing_status import doctor as billing_doctor
from unlimited_skills.billing_status import format_billing_status, redacted_billing_summary, refresh_billing_status
from unlimited_skills.org_status import local_org_status, refresh_org_status
from unlimited_skills.plan_status import doctor as plan_doctor
from unlimited_skills.plan_status import explain_feature, format_plan_status, redacted_plan_summary, refresh_plan_status
from unlimited_skills.registration import load_registration
from unlimited_skills.updates import UpdateClient


def cmd_org_status(args: argparse.Namespace) -> int:
    registration = load_registration()
    if args.refresh:
        payload = refresh_org_status(registration, timeout=args.timeout)
    else:
        payload = local_org_status(registration)
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    print("Registered: " + ("yes" if payload["registered"] else "no"))
    print(f"Plan: {payload['plan']}")
    org = payload["organization"]
    print(f"Organization: {org.get('name') or '(none)'} ({org.get('status') or 'unknown'}, role: {org.get('role') or 'none'})")
    team = payload["team"]
    print(f"Team: {team.get('team_name') or '(none)'} ({team.get('status') or 'none'}, role: {team.get('role') or 'none'})")
    print(f"Source: {payload['source']}")
    if payload["last_refreshed_at"]:
        print(f"Last refreshed: {payload['last_refreshed_at']}")
    if payload["recommendations"]:
        print("Recommendations: " + " ".join(payload["recommendations"]))
    return 0


def cmd_plan_status(args: argparse.Namespace) -> int:
    payload = redacted_plan_summary()
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print(format_plan_status(payload))
    return 0


def cmd_plan_refresh(args: argparse.Namespace) -> int:
    payload = refresh_plan_status(timeout=args.timeout)
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print(format_plan_status(payload["plan_status"]))
    return 0


def cmd_plan_explain(args: argparse.Namespace) -> int:
    payload = explain_feature(args.feature)
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print(f"Feature: {payload['feature']}")
        print("Allowed: " + ("yes" if payload["allowed"] else "no"))
        if payload["denial_reason"]:
            print(f"Denial reason: {payload['denial_reason']}")
            print(payload["message"])
    return 0


def cmd_plan_doctor(args: argparse.Namespace) -> int:
    payload = plan_doctor()
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print("Plan doctor: " + ("ok" if payload["ok"] else "needs attention"))
        print(format_plan_status(payload["plan_status"]))
        for name, check in payload["checks"].items():
            print(f"{name}: {'ok' if check['ok'] else 'attention'}")
            if check.get("denial_reason"):
                print(f"  denial_reason={check['denial_reason']}")
    return 0


def cmd_billing_status(args: argparse.Namespace) -> int:
    payload = redacted_billing_summary()
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print(format_billing_status(payload))
    return 0


def cmd_billing_refresh(args: argparse.Namespace) -> int:
    payload = refresh_billing_status(timeout=args.timeout)
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print(format_billing_status(payload["billing_status"]))
    return 0


def cmd_billing_doctor(args: argparse.Namespace) -> int:
    payload = billing_doctor()
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print("Billing doctor: " + ("ok" if payload["ok"] else "needs attention"))
        print(format_billing_status(payload["billing_status"]))
        for name, check in payload["checks"].items():
            print(f"{name}: {'ok' if check['ok'] else 'attention'}")
            if check.get("denial_reason"):
                print(f"  denial_reason={check['denial_reason']}")
    return 0


def cmd_enhance_download(args: argparse.Namespace) -> int:
    root = Path(args.root).expanduser()
    client = UpdateClient(load_registration(), timeout=args.timeout)
    target_dir = Path(args.target_dir).expanduser() if args.target_dir else None
    path = client.download_enhancement_script(root, target_dir=target_dir)
    payload = {"root": str(root), "script": str(path)}
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(path)
    return 0


def cmd_enhance_run(args: argparse.Namespace) -> int:
    root = Path(args.root).expanduser()
    client = UpdateClient(load_registration(), timeout=args.timeout)
    target_dir = Path(args.target_dir).expanduser() if args.target_dir else None
    return client.run_enhancement_script(root, apply=args.apply, limit=args.limit, target_dir=target_dir)
