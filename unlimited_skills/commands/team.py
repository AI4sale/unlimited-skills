"""Team registration, membership, and sync commands."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from unlimited_skills import cli
from unlimited_skills.registration import load_registration
from unlimited_skills.team import (
    TeamClient,
    collection_to_json,
    load_team_state,
    member_to_json,
    parse_duration_hours,
    redacted_team_status,
    save_team_state,
    team_state_with_mode,
    write_team_audit,
)
from unlimited_skills.updates import UpdateClient


def _confirm_or_fail(flag: bool, phrase: str, message: str) -> None:
    if flag:
        return
    if not sys.stdin.isatty():
        raise RuntimeError(f"{message} Pass --yes to confirm in non-interactive mode.")
    typed = input(f"Type {phrase} to continue: ")
    if typed.strip() != phrase:
        raise RuntimeError("Operation cancelled.")


def _reason_or_prompt(reason: str) -> str:
    if reason:
        return reason
    if not sys.stdin.isatty():
        raise RuntimeError("This command requires --reason in non-interactive mode.")
    typed = input("Reason: ").strip()
    if not typed:
        raise RuntimeError("Reason is required.")
    return typed


def cmd_team_status(args: argparse.Namespace) -> int:
    team = load_team_state()
    registration = load_registration()
    payload = redacted_team_status(team, registration)
    if getattr(args, "refresh", False):
        client = TeamClient(registration, timeout=args.timeout)
        refreshed = client.status(team)
        payload["refresh"] = refreshed
        payload["member_count"] = int(refreshed.get("member_count") or payload["member_count"])
        payload["pending_count"] = int(refreshed.get("pending_count") or payload["pending_count"])
        if isinstance(refreshed.get("limits"), dict):
            payload["limits"] = refreshed["limits"]
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    print("Registered: " + ("yes" if payload["registered"] else "no"))
    print(f"Team: {payload['team_name'] or '(none)'} ({payload['team_id'] or 'no team id'})")
    print(f"Role: {payload['role']} / status: {payload['status'] or 'none'}")
    print(f"Approval mode: {payload['approval_mode']}")
    if payload["auto_approval_expires_at"]:
        print(f"Auto approval expires: {payload['auto_approval_expires_at']}")
    print(f"Last sync: {payload['last_sync_at'] or '(never)'}")
    if payload["recommendations"]:
        print("Recommendations: " + " ".join(payload["recommendations"]))
    return 0


def cmd_team_create(args: argparse.Namespace) -> int:
    root = Path(args.root).expanduser()
    name = args.name_option or args.name
    if not name:
        raise RuntimeError("Team name is required.")
    registration = load_registration()
    client = TeamClient(registration, timeout=args.timeout)
    team, response = client.create(root, name=name)
    path = save_team_state(team)
    payload = redacted_team_status(team, registration)
    payload["team_file"] = str(path)
    if "join_code" in response:
        payload["join_code"] = response["join_code"]
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def cmd_team_join(args: argparse.Namespace) -> int:
    root = Path(args.root).expanduser()
    registration = load_registration()
    client = TeamClient(registration, timeout=args.timeout)
    team, _ = client.join(root, join_code=args.join_code, display_name=args.display_name, agent_surfaces=tuple(args.agent_surface or ()))
    path = save_team_state(team)
    payload = redacted_team_status(team, registration)
    payload["team_file"] = str(path)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def cmd_team_sync(args: argparse.Namespace) -> int:
    root = Path(args.root).expanduser()
    registration = load_registration()
    team = load_team_state()
    team_client = TeamClient(registration, timeout=args.timeout)
    plan = team_client.sync_manifest(root, team)
    updates = plan.updates
    if args.collection:
        updates = [item for item in updates if item.collection == args.collection]
    if args.dry_run:
        payload = plan.dry_run_payload(root)
        if args.collection:
            payload["collections"] = [item for item in payload["collections"] if item["collection"] == args.collection]
        write_team_audit("team_sync_dry_run", team=team, registration=registration, request_id=plan.request_id)
        print(json.dumps({"root": str(root), "dry_run": True, "plan": payload}, ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    _confirm_or_fail(args.yes, "SYNC", "Team sync may change local team-owned skill collections.")
    update_client = UpdateClient(registration, timeout=args.timeout)
    applied = [update_client.apply(root, item) for item in updates]
    reindexed = False
    if not args.skip_reindex:
        cli.save_index(root)
        reindexed = True
    team = team_client.mark_synced(team)
    save_team_state(team)
    write_team_audit("team_sync_applied", team=team, registration=registration, result=f"{len(applied)} applied", request_id=plan.request_id)
    print(json.dumps({"root": str(root), "applied": applied, "reindexed": reindexed, "team": redacted_team_status(team, registration)}, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


def cmd_team_members(args: argparse.Namespace) -> int:
    team = load_team_state()
    client = TeamClient(load_registration(), timeout=args.timeout)
    members = client.members(team, include_all=args.all, pending_only=args.pending)
    payload = {"count": len(members), "members": [member_to_json(member, full_id=args.full_id) for member in members]}
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    for member in payload["members"]:
        print(f"{member['install_id']}: {member['display_name'] or '(unnamed)'} [{member['role']}/{member['status']}]")
    return 0


def cmd_team_pending(args: argparse.Namespace) -> int:
    team = load_team_state()
    client = TeamClient(load_registration(), timeout=args.timeout)
    payload = client.pending(team)
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    items = payload.get("items") or payload.get("members") or []
    for item in items if isinstance(items, list) else []:
        install_id = str(item.get("install_id") or "")
        short = install_id if args.full_id or len(install_id) <= 16 else f"{install_id[:12]}..."
        print(f"{short}: {item.get('display_name') or '(unnamed)'} {item.get('client_version') or ''}")
    return 0


def cmd_team_approve(args: argparse.Namespace) -> int:
    team = load_team_state()
    client = TeamClient(load_registration(), timeout=args.timeout)
    print(json.dumps(client.approve(team, member_install_id=args.install_id), ensure_ascii=False, indent=2, sort_keys=True))
    return 0


def cmd_team_reject(args: argparse.Namespace) -> int:
    team = load_team_state()
    client = TeamClient(load_registration(), timeout=args.timeout)
    reason = _reason_or_prompt(args.reason)
    print(json.dumps(client.reject(team, member_install_id=args.install_id, reason=reason), ensure_ascii=False, indent=2, sort_keys=True))
    return 0


def cmd_team_revoke(args: argparse.Namespace) -> int:
    team = load_team_state()
    client = TeamClient(load_registration(), timeout=args.timeout)
    _confirm_or_fail(args.yes, "REVOKE", "Team revoke removes hosted team access for that instance.")
    print(json.dumps(client.revoke(team, member_install_id=args.install_id, reason=args.reason), ensure_ascii=False, indent=2, sort_keys=True))
    return 0


def cmd_team_mode(args: argparse.Namespace) -> int:
    team = load_team_state()
    registration = load_registration()
    client = TeamClient(registration, timeout=args.timeout)
    duration = f"{args.hours}h" if getattr(args, "hours", 0) else args.duration
    hours = parse_duration_hours(duration, plan=(registration.plan or "team-free")) if args.mode == "auto" else 0
    response = client.set_mode(team, mode=args.mode, hours=hours)
    save_team_state(team_state_with_mode(team, response, mode=args.mode, hours=hours))
    print(json.dumps(response, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


def cmd_team_collections(args: argparse.Namespace) -> int:
    team = load_team_state()
    client = TeamClient(load_registration(), timeout=args.timeout)
    collections = client.collections(team)
    payload = {"count": len(collections), "collections": [collection_to_json(item) for item in collections]}
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


def cmd_team_leave(args: argparse.Namespace) -> int:
    team = load_team_state()
    registration = load_registration()
    client = TeamClient(registration, timeout=args.timeout)
    _confirm_or_fail(args.yes, "LEAVE", "Leaving the team stops hosted team sync for this installation.")
    response = client.leave(team)
    left = client.left_state(team)
    save_team_state(left)
    print(json.dumps({"result": response, "team": redacted_team_status(left, registration)}, ensure_ascii=False, indent=2, sort_keys=True))
    return 0
