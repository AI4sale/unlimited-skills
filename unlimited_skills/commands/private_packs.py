"""Private team pack preview, install, sync, and diagnostics commands."""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from pathlib import Path

from unlimited_skills import cli
from unlimited_skills.private_pack_diagnostics import private_pack_doctor
from unlimited_skills.private_packs import PrivatePackClient, list_installed_private_packs, remove_private_pack
from unlimited_skills.registration import load_registration

from .team import _confirm_or_fail


def _emit_private_pack_items(items, *, as_json: bool) -> int:
    payload = {"count": len(items), "items": [asdict(item) for item in items]}
    if as_json:
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    if not items:
        print("No private team packs found.")
        return 0
    for item in items:
        print(f"{item.pack_id}: {item.name} {item.version} [{item.team_id}]")
    return 0


def cmd_private_packs_list(args: argparse.Namespace) -> int:
    client = PrivatePackClient(load_registration(), timeout=args.timeout)
    return _emit_private_pack_items(client.list(), as_json=args.json)


def cmd_private_packs_preview(args: argparse.Namespace) -> int:
    client = PrivatePackClient(load_registration(), timeout=args.timeout)
    payload = client.preview(args.pack_id)
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    pack = payload["pack"]
    print(f"{pack['pack_id']}: {pack['name']} {pack['version']} [{pack['team_id']}]")
    print(f"Archive SHA256: {pack['archive_sha256']}")
    return 0


def cmd_private_packs_install(args: argparse.Namespace) -> int:
    root = Path(args.root).expanduser()
    client = PrivatePackClient(load_registration(), timeout=args.timeout)
    if not args.dry_run:
        _confirm_or_fail(args.yes, "INSTALL", "Private pack install may change registry/private skill files.")
    result = client.install(root, args.pack_id, dry_run=args.dry_run)
    reindexed = False
    if result.installed and not args.skip_reindex:
        cli.save_index(root)
        reindexed = True
    payload = {"result": asdict(result), "reindexed": reindexed}
    if args.json or args.dry_run:
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print(f"Installed private pack {result.pack_id} {result.version}")
        if reindexed:
            print("Lexical index rebuilt.")
    return 0


def cmd_private_packs_sync(args: argparse.Namespace) -> int:
    root = Path(args.root).expanduser()
    client = PrivatePackClient(load_registration(), timeout=args.timeout)
    dry_run = args.dry_run or not args.yes
    if not dry_run:
        _confirm_or_fail(args.yes, "SYNC", "Private pack sync may install or update registry/private skill packs.")
    payload = client.sync(root, dry_run=dry_run)
    reindexed = False
    if payload["applied"] and not args.skip_reindex:
        cli.save_index(root)
        reindexed = True
    payload["reindexed"] = reindexed
    if args.json or dry_run:
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print(f"Private pack sync applied {len(payload['applied'])} change(s).")
        if reindexed:
            print("Lexical index rebuilt.")
    return 0


def cmd_private_packs_installed(args: argparse.Namespace) -> int:
    root = Path(args.root).expanduser()
    installed = list_installed_private_packs(root)
    payload = {"root": str(root), "count": len(installed), "items": [asdict(item) for item in installed]}
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    if not installed:
        print("No installed private team packs found.")
        return 0
    for item in installed:
        print(f"{item.pack_id}: {item.name} {item.version} -> {item.target}")
    return 0


def cmd_private_packs_remove(args: argparse.Namespace) -> int:
    root = Path(args.root).expanduser()
    result = remove_private_pack(root, args.pack_id, dry_run=args.dry_run or not args.yes)
    reindexed = False
    if result.get("removed") and not args.skip_reindex:
        cli.save_index(root)
        reindexed = True
    payload = {"result": result, "reindexed": reindexed}
    if args.json or result.get("dry_run"):
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print(f"Removed private pack {args.pack_id}")
        if reindexed:
            print("Lexical index rebuilt.")
    return 0


def cmd_private_packs_access_check(args: argparse.Namespace) -> int:
    client = PrivatePackClient(load_registration(), timeout=args.timeout)
    payload = client.access_check_diagnostic(args.pack_id)
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    print(f"Pack: {payload['pack_ref']}")
    print(f"Status: {payload['status']}")
    print("Authorized: " + ("yes" if payload["authorized"] else "no"))
    if payload["denial_reasons"]:
        print("Denial reasons: " + ", ".join(payload["denial_reasons"]))
    if payload["request_id"]:
        print(f"Request: {payload['request_id']}")
    return 0


def cmd_private_packs_doctor(args: argparse.Namespace) -> int:
    root = Path(args.root).expanduser()
    payload = private_pack_doctor(root, state=load_registration())
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    print(f"Status: {payload['status']}")
    print("Registered: " + ("yes" if payload["registered"] else "no"))
    checks = payload["setup"]["checks"]
    print(f"Installed private packs: {checks['installed_count']}")
    print(f"Trust key: {checks['trust_key']}")
    if payload["recommendations"]:
        print("Recommendations: " + " ".join(payload["recommendations"]))
    return 0
