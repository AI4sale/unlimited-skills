"""Enterprise Skill Lock policy commands."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from unlimited_skills.policy import (
    explain_policy,
    install_policy,
    load_policy,
    policy_summary,
    read_policy_file,
    remove_policy,
    verify_policy_payload,
)
from unlimited_skills.policy_sync import managed_policy_status, sync_managed_policy


def cmd_policy_status(args: argparse.Namespace) -> int:
    payload = policy_summary(load_policy())
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


def cmd_policy_verify(args: argparse.Namespace) -> int:
    payload = verify_policy_payload(read_policy_file(Path(args.policy_json).expanduser()))
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


def cmd_policy_install(args: argparse.Namespace) -> int:
    payload = install_policy(Path(args.policy_json).expanduser())
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


def cmd_policy_remove(args: argparse.Namespace) -> int:
    payload = remove_policy(yes=args.yes)
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


def cmd_policy_explain(args: argparse.Namespace) -> int:
    print(explain_policy(load_policy()))
    return 0


def cmd_policy_sync(args: argparse.Namespace) -> int:
    payload = sync_managed_policy(root=args.root, dry_run=args.dry_run, timeout=args.timeout)
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        state = payload["managed_state"]
        print("Managed policy sync: " + ("dry-run" if payload["dry_run"] else "applied"))
        print(f"Action: {state.get('action')}")
        print(f"Changed: {str(payload.get('changed')).lower()}")
        if state.get("policy_id"):
            print(f"Policy: {state.get('policy_id')}")
        if state.get("path"):
            print(f"Path: {state.get('path')}")
    return 0


def cmd_policy_managed_status(args: argparse.Namespace) -> int:
    payload = managed_policy_status()
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        managed = payload["managed_state"]
        installed = payload["installed_policy"]
        print("Managed: " + ("yes" if managed.get("managed") else "no"))
        print("Last sync: " + (managed.get("last_sync_at") or "never"))
        print("Installed policy: " + (installed.get("policy_id") or "(none)"))
        print("Mode: " + str(installed.get("mode") or "disabled"))
    return 0
