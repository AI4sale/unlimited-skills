"""Hosted collection updates, release channels, and core self-update commands."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from unlimited_skills import cli
from unlimited_skills.registration import load_registration
from unlimited_skills.self_update import apply_public_repo_update, check_public_repo_update
from unlimited_skills.updates import UpdateClient, load_release_channel, rollback_collection, save_release_channel

from .team import _confirm_or_fail


def cmd_updates_check(args: argparse.Namespace) -> int:
    root = Path(args.root).expanduser()
    client = UpdateClient(load_registration(), timeout=args.timeout, channel=args.channel)
    updates = client.check(root)
    if args.collection:
        updates = [item for item in updates if item.collection == args.collection]
    payload = {"root": str(root), "channel": client.channel, "count": len(updates), "updates": [item.__dict__ for item in updates]}
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    elif updates:
        for item in updates:
            print(f"{item.collection}: {item.version} ({item.notes or 'update available'})")
    else:
        print("No hosted collection updates available.")
    return 0


def cmd_updates_apply(args: argparse.Namespace) -> int:
    root = Path(args.root).expanduser()
    client = UpdateClient(load_registration(), timeout=args.timeout, channel=args.channel)
    updates = client.check(root)
    if args.collection:
        updates = [item for item in updates if item.collection == args.collection]
    if args.dry_run:
        print(json.dumps({"root": str(root), "channel": client.channel, "dry_run": True, "count": len(updates), "updates": [item.__dict__ for item in updates]}, ensure_ascii=False, indent=2))
        return 0
    applied = [client.apply(root, item) for item in updates]
    if applied and not args.skip_reindex:
        cli.save_index(root)
    print(json.dumps({"root": str(root), "channel": client.channel, "applied": applied, "reindexed": bool(applied and not args.skip_reindex)}, ensure_ascii=False, indent=2))
    return 0


def cmd_updates_rollback(args: argparse.Namespace) -> int:
    root = Path(args.root).expanduser()
    if not args.yes and not args.dry_run:
        _confirm_or_fail(False, "ROLLBACK", "Update rollback will replace the active collection with the latest rollback snapshot.")
    if args.dry_run:
        payload = {"root": str(root), "collection": args.collection, "dry_run": True}
    else:
        payload = {"root": str(root), "dry_run": False, "result": rollback_collection(root, args.collection)}
        if not args.skip_reindex:
            cli.save_index(root)
            payload["reindexed"] = True
        else:
            payload["reindexed"] = False
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


def cmd_release_status(args: argparse.Namespace) -> int:
    state = load_release_channel()
    client = UpdateClient(load_registration(), timeout=args.timeout, channel=args.channel)
    payload = client.release_channels()
    payload["local_release_channel"] = state.to_json()
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    print(f"Current local channel: {state.channel} ({'pinned' if state.pinned else 'default'})")
    for item in payload.get("channels", []):
        if isinstance(item, dict):
            marker = "*" if item.get("name") == client.channel else " "
            print(f"{marker} {item.get('name')}: {str(item.get('current_release_id') or '')[:12]} ({item.get('status') or 'active'})")
    return 0


def cmd_release_pin(args: argparse.Namespace) -> int:
    path = save_release_channel(args.channel, pinned=True)
    payload = {"channel": args.channel, "pinned": True, "path": str(path)}
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


def cmd_self_update_check(args: argparse.Namespace) -> int:
    status = check_public_repo_update(repo=args.repo, install_root=Path(args.install_root).expanduser() if args.install_root else None, timeout=args.timeout)
    payload = status.to_json()
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0
    print(f"Install root: {status.install_root}")
    print(f"Public repo: {status.repo}")
    print(f"Current version: {status.current_version}")
    print(f"Latest release: {status.latest_tag} ({status.latest_version})")
    print(f"Git checkout: {'yes' if status.is_git_checkout else 'no'}")
    if status.is_git_checkout:
        print(f"Current ref: {status.current_ref or '(unknown)'}")
        print(f"Dirty: {'yes' if status.dirty else 'no'}")
    print(f"Update available: {'yes' if status.update_available else 'no'}")
    if status.release_url:
        print(f"Release: {status.release_url}")
    return 0


def cmd_self_update_apply(args: argparse.Namespace) -> int:
    status = check_public_repo_update(repo=args.repo, install_root=Path(args.install_root).expanduser() if args.install_root else None, timeout=args.timeout)
    if args.dry_run:
        print(json.dumps({"dry_run": True, "status": status.to_json()}, ensure_ascii=False, indent=2))
        return 0
    result = apply_public_repo_update(status, allow_dirty=args.allow_dirty, method=args.method, timeout=args.timeout)
    router_refreshed = refresh_codex_router_skill(Path(result.install_root).expanduser()) if result.reindex_recommended and not args.skip_router_refresh else ""
    reindexed = False
    if result.reindex_recommended and not args.skip_reindex:
        cli.save_index(Path(args.root).expanduser())
        reindexed = True
    print(json.dumps({"result": result.to_json(), "reindexed": reindexed, "router_refreshed": router_refreshed}, ensure_ascii=False, indent=2))
    return 0


def refresh_codex_router_skill(install_root: Path) -> str:
    source = install_root / "skills" / "skill-router" / "SKILL.md"
    target = Path.home() / ".codex" / "skills" / "unlimited-skills" / "SKILL.md"
    if not source.is_file() or not target.parent.is_dir():
        return ""
    target.write_text(cli.read_text(source), encoding="utf-8")
    return str(target)
