"""Community catalog browse, install, submit, and removal commands."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path

from unlimited_skills import cli
from unlimited_skills.community import (
    CommunityClient,
    build_submission_draft,
    confirm_upload_or_fail,
    list_installed_community_items,
    remove_community_item,
)
from unlimited_skills.registration import load_registration


def _split_csv(value: str) -> tuple[str, ...]:
    return tuple(item.strip() for item in (value or "").split(",") if item.strip())


def _emit_community_items(items, *, as_json: bool) -> int:
    payload = {"count": len(items), "items": [asdict(item) for item in items]}
    if as_json:
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    if not items:
        print("No community skills found.")
        return 0
    for item in items:
        label = item.display_name or item.name
        version = f" {item.version}" if item.version else ""
        print(f"{item.item_id}: {label}{version} [{item.kind}]")
        if item.description:
            print(f"  {item.description}")
        if item.publisher:
            print(f"  publisher: {item.publisher}")
    return 0


def cmd_community_list(args: argparse.Namespace) -> int:
    root = Path(args.root).expanduser()
    client = CommunityClient(load_registration(), timeout=args.timeout)
    items = client.list_community_items_v2(root, limit=args.limit, compatible_agent=args.compatible_agent, tags=_split_csv(args.tags), channel=args.channel)
    return _emit_community_items(items, as_json=args.json)


def cmd_community_search(args: argparse.Namespace) -> int:
    root = Path(args.root).expanduser()
    client = CommunityClient(load_registration(), timeout=args.timeout)
    items = client.search_community_items(
        root,
        query=args.query,
        tags=_split_csv(args.tags),
        compatible_agent=args.compatible_agent,
        limit=args.limit,
    )
    return _emit_community_items(items, as_json=args.json)


def cmd_community_preview(args: argparse.Namespace) -> int:
    client = CommunityClient(load_registration(), timeout=args.timeout)
    preview = client.preview_community_item(args.catalog_item_id)
    payload = asdict(preview)
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    item = preview.item
    print(f"{item.item_id}: {item.display_name or item.name} [{item.kind}]")
    if preview.description or item.description:
        print(preview.description or item.description)
    if preview.included_skill_names:
        print("Skills: " + ", ".join(preview.included_skill_names))
    if preview.warnings:
        print("Warnings: " + "; ".join(preview.warnings))
    return 0


def cmd_community_install(args: argparse.Namespace) -> int:
    root = Path(args.root).expanduser()
    client = CommunityClient(load_registration(), timeout=args.timeout)
    if not args.dry_run and not args.yes:
        if not sys.stdin.isatty():
            raise RuntimeError("Community install requires --yes in non-interactive mode.")
        typed = input("Type INSTALL to install this community item: ")
        if typed.strip() != "INSTALL":
            raise RuntimeError("Community install cancelled.")
    result = client.install_community_item(
        root,
        item_id=args.catalog_item_id,
        target_collection=args.collection,
        dry_run=args.dry_run,
        force=args.force,
    )
    reindexed = False
    if not args.dry_run and not args.skip_reindex:
        cli.save_index(root)
        reindexed = True
    payload = {"result": asdict(result), "reindexed": reindexed}
    if args.json or args.dry_run:
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print(f"Installed {payload['result']['collection']} {payload['result']['version']}")
        if reindexed:
            print("Lexical index rebuilt.")
    return 0


def cmd_community_submit(args: argparse.Namespace) -> int:
    draft = build_submission_draft(
        Path(args.path),
        name=args.name,
        description=args.description,
        tags=_split_csv(args.tags),
        compatible_agents=tuple(args.compatible_agent or ()),
        visibility=args.visibility,
    )
    payload = {
        "preview_path": draft.preview_path,
        "name": draft.name,
        "description": draft.description,
        "skills": list(draft.skills),
        "files": [{key: value for key, value in row.items() if key != "content_base64"} for row in draft.files],
        "total_bytes": draft.total_bytes,
        "warnings": list(draft.warnings),
        "note": "Community submission uploads the selected skill/pack content for maintainer review.",
    }
    if args.dry_run:
        payload["result"] = {
            "submission_id": "",
            "status": "draft",
            "preview_path": draft.preview_path,
            "uploaded": False,
            "message": "Dry run: no content uploaded.",
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    client = CommunityClient(load_registration(), timeout=args.timeout)
    confirm = confirm_upload_or_fail(args.yes)
    result = client.submit_community_skill(draft, confirm=confirm)
    payload["result"] = asdict(result)
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


def cmd_community_submission_status(args: argparse.Namespace) -> int:
    client = CommunityClient(load_registration(), timeout=args.timeout)
    payload = client.get_submission_status(args.submission_id)
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


def cmd_community_withdraw(args: argparse.Namespace) -> int:
    client = CommunityClient(load_registration(), timeout=args.timeout)
    payload = client.withdraw_submission(args.submission_id)
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


def cmd_community_review_notes(args: argparse.Namespace) -> int:
    client = CommunityClient(load_registration(), timeout=args.timeout)
    payload = client.review_notes(args.submission_id)
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


def cmd_community_installed(args: argparse.Namespace) -> int:
    root = Path(args.root).expanduser()
    installed = list_installed_community_items(root)
    payload = {"root": str(root), "count": len(installed), "items": [asdict(item) for item in installed]}
    if args.refresh:
        client = CommunityClient(load_registration(), timeout=args.timeout)
        payload["refresh"] = {"available_count": len(client.list_community_items(root, limit=1))}
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    if not installed:
        print("No installed community skills found.")
        return 0
    for item in installed:
        print(f"{item.collection}: {item.name} {item.version} [{item.source}]")
    return 0


def cmd_community_remove(args: argparse.Namespace) -> int:
    root = Path(args.root).expanduser()
    result = remove_community_item(root, args.collection_or_skill_name, dry_run=args.dry_run or not args.yes, force=args.force)
    reindexed = False
    if result.get("removed") and not args.skip_reindex:
        cli.save_index(root)
        reindexed = True
    payload = {"result": result, "reindexed": reindexed}
    if args.json or result.get("dry_run"):
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print(f"Removed {result['collection']}")
        if reindexed:
            print("Lexical index rebuilt.")
    return 0
