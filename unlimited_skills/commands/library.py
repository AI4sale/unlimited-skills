"""Local library commands: index, search, view, import, adapt, and setup."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from dataclasses import asdict
from pathlib import Path

from unlimited_skills import cli
from unlimited_skills.adapters import (
    SKILL_PACKS,
    adapt_library,
    adaptation_task,
    apply_agent_adaptation,
    import_github_repo,
    import_skill_dirs,
    install_pack,
    next_skill_for_agent,
)
from unlimited_skills.doctor import build_doctor_report, doctor_json, format_doctor_text
from unlimited_skills.native import DEFAULT_AGENT_ORDER, sync_native_sources
from unlimited_skills.setup_wizard import build_setup_report, format_setup_text
from unlimited_skills.support_bundle import build_bundle_report, format_bundle_text


def cmd_reindex(args: argparse.Namespace) -> int:
    root = Path(args.root).expanduser()
    cli.enforce_local_root(root, action="reindex library root")
    native_sync = cli.maybe_sync_native(args, root)
    path = cli.save_index(root)
    count = len(json.loads(cli.read_text(path)))
    if args.json:
        print(json.dumps({"root": str(root), "indexed": count, "index": str(path), "native_sync": native_sync}, ensure_ascii=False, indent=2))
    else:
        print(f"Indexed {count} skills: {path}")
    return 0


def cmd_search(args: argparse.Namespace) -> int:
    root = Path(args.root).expanduser()
    cli.enforce_local_root(root, action="search library root")
    cli.maybe_sync_native(args, root)
    if args.mode == "lexical":
        hits = cli.lexical_search(root, args.query, args.limit, args.collection, args.fresh)
    elif args.mode == "vector":
        hits = cli.vector_search(root, args.query, args.limit, args.model, args.collection)
    else:
        hits = cli.hybrid_search(root, args.query, args.limit, args.model, args.collection, args.fresh, args.require_vector)
    cli.log_event(root, "search", {"query": args.query, "mode": args.mode, "hits": [asdict(hit) for hit in hits[:5]]})
    return cli.emit_hits(hits, args.json)


def cmd_suggest(args: argparse.Namespace) -> int:
    # Delegate to the import-cheap suggest module so the classic CLI and the
    # fast `python -m unlimited_skills suggest` path share one implementation.
    from unlimited_skills import suggest as suggest_mod

    argv = [args.query, "--root", str(args.root), "--limit", str(args.limit)]
    if args.floor is not None:
        argv.extend(["--floor", str(args.floor)])
    if args.collection:
        argv.extend(["--collection", args.collection])
    if args.json:
        argv.append("--json")
    return suggest_mod.main(argv)


def cmd_skills_check_effectiveness(args: argparse.Namespace) -> int:
    # Alias for the CI script: `unlimited-skills skills check-effectiveness`
    # loads scripts/check-skill-effectiveness.py and runs its main(), so the
    # CLI and CI share ONE implementation (the script stays the CI entry
    # point). Requires a source checkout: the script and the frozen eval set
    # are not shipped inside the installed package.
    import importlib.util

    script = Path(__file__).resolve().parents[2] / "scripts" / "check-skill-effectiveness.py"
    if not script.is_file():
        print(
            "skills check-effectiveness requires a source checkout: scripts/check-skill-effectiveness.py was not found.",
            file=sys.stderr,
        )
        return 2
    spec = importlib.util.spec_from_file_location("check_skill_effectiveness", script)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    argv: list[str] = []
    if args.json:
        argv.append("--json")
    if args.cadence_check:
        argv.append("--cadence-check")
    if args.no_record:
        argv.append("--no-record")
    return int(module.main(argv))


def cmd_list(args: argparse.Namespace) -> int:
    root = Path(args.root).expanduser()
    cli.enforce_local_root(root, action="list library root")
    cli.maybe_sync_native(args, root)
    hits = cli.list_skills(root, collection=args.collection, filter_text=args.filter, fresh=args.fresh)
    shown = hits[: args.limit] if args.limit > 0 else hits
    payload = {
        "root": str(root),
        "total": len(hits),
        "shown": len(shown),
        "collections": cli.collection_counts(hits),
        "skills": [asdict(hit) for hit in shown],
    }
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0
    print(f"Total skills: {payload['total']}")
    if payload["collections"]:
        print("Collections: " + ", ".join(f"{name}={count}" for name, count in payload["collections"].items()))
    if len(shown) < len(hits):
        print(f"Showing first {len(shown)} skills. Use --limit 0 to show all.")
    for hit in shown:
        if args.names_only:
            print(hit.name)
            continue
        print(f"{hit.name} [{hit.collection}]")
        if hit.description:
            print(f"  {hit.description}")
        if args.paths:
            print(f"  {hit.path}")
    cli.log_event(root, "list", {"collection": args.collection or "", "filter": args.filter, "shown": len(shown), "total": len(hits)})
    return 0


def cmd_vector_reindex(args: argparse.Namespace) -> int:
    root = Path(args.root).expanduser()
    cli.enforce_local_root(root, action="vector reindex library root")
    cli.maybe_sync_native(args, root)
    records = cli.load_records(root, fresh=args.fresh)
    client = cli.chroma_client(root)
    try:
        client.delete_collection(cli.CHROMA_COLLECTION)
    except Exception:
        pass
    collection = client.get_or_create_collection(name=cli.CHROMA_COLLECTION, metadata={"hnsw:space": "cosine"})
    batch_size = max(1, min(args.batch_size, 128))
    total = 0
    sidecar_records: list[dict] = []
    for start in range(0, len(records), batch_size):
        batch = records[start : start + batch_size]
        ids = []
        docs = []
        metas = []
        for hit, body in batch:
            ids.append(str(Path(hit.path)).lower().replace("\\", "/"))
            docs.append(cli.vector_text(hit, body))
            metas.append({"name": hit.name, "description": hit.description, "collection": hit.collection, "path": hit.path})
        embeddings = cli.embed_texts(docs, args.model)
        collection.add(ids=ids, documents=docs, metadatas=metas, embeddings=embeddings)
        for meta, embedding in zip(metas, embeddings):
            sidecar_records.append({**meta, "embedding": [round(float(value), 8) for value in embedding]})
        total += len(batch)
        if args.verbose:
            print(f"Indexed {total}/{len(records)}")
    cli.vector_sidecar_path(root).write_text(
        json.dumps(
            {
                "schema_version": 1,
                "collection": cli.CHROMA_COLLECTION,
                "model": args.model,
                "count": total,
                "generated_at": time.time(),
                "records": sidecar_records,
            },
            ensure_ascii=False,
            separators=(",", ":"),
        ),
        encoding="utf-8",
    )
    cli.vector_meta_path(root).write_text(
        json.dumps(
            {
                "collection": cli.CHROMA_COLLECTION,
                "model": args.model,
                "count": total,
                "chroma_path": str(root / cli.CHROMA_DIR_NAME),
                "sidecar_path": str(cli.vector_sidecar_path(root)),
                "query_fast_path": "sidecar",
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"Vector-indexed {total} skills with {args.model}: {cli.vector_sidecar_path(root)}")
    print(f"Chroma compatibility index: {root / cli.CHROMA_DIR_NAME}")
    return 0


def cmd_view(args: argparse.Namespace) -> int:
    root = Path(args.root).expanduser()
    cli.enforce_local_root(root, action="view library root")
    cli.maybe_sync_native(args, root)
    path = cli.find_by_name(root, args.name)
    if not path:
        print(f"Skill not found: {args.name}", file=sys.stderr)
        return 2
    print(cli.read_text(path))
    cli.log_event(root, "view", {"name": args.name, "path": str(path)})
    return 0


def cmd_where(args: argparse.Namespace) -> int:
    root = Path(args.root).expanduser()
    cli.enforce_local_root(root, action="where library root")
    cli.maybe_sync_native(args, root)
    path = cli.find_by_name(root, args.name)
    if not path:
        print(f"Skill not found: {args.name}", file=sys.stderr)
        return 2
    print(path)
    return 0


def cmd_use(args: argparse.Namespace) -> int:
    root = Path(args.root).expanduser()
    cli.enforce_local_root(root, action="use library root")
    cli.maybe_sync_native(args, root)
    path = cli.find_by_name(root, args.name)
    payload = {"name": args.name, "query": args.query, "task": args.task, "path": str(path) if path else ""}
    cli.log_event(root, "skill_used", payload)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def cmd_feedback(args: argparse.Namespace) -> int:
    root = Path(args.root).expanduser()
    raw_row = {
        "ts": time.time(),
        "name": args.name,
        "query": args.query,
        "verdict": args.verdict,
        "notes": args.notes,
    }
    row = cli.event_safe_payload(root, "feedback", raw_row)
    cli.write_jsonl(root / ".learning" / cli.FEEDBACK_LOG, row)
    print(json.dumps(row, ensure_ascii=False, indent=2))
    return 0


def _bump(counter: dict[str, int], key: object) -> None:
    label = "none" if key is None else str(key)
    counter[label] = counter.get(label, 0) + 1


# A3.1.1: events that advance the suggest -> view -> use funnel. The daemon
# variants are the long-running-server equivalents of the one-shot CLI events.
_VIEW_EVENT_TYPES = {"view", "daemon_view"}
_USE_EVENT_TYPES = {"skill_used", "daemon_skill_used"}


def compute_event_metrics(root: Path) -> dict:
    """Aggregate local effectiveness metrics from ``events.jsonl`` (A3.1.1).

    Local-only and privacy-safe: emits counts, rates, and tier/bucket
    distributions only — never query text, skill bodies, or filesystem paths.
    The suggest -> view -> use funnel is correlated by the hashed
    ``session_correlation_id`` stamped on each event; sessions without one are
    still counted at the suggest level but cannot be attributed to a funnel.
    """
    metrics: dict = {
        "total_events": 0,
        "suggest_count": 0,
        "carded_suggest_count": 0,
        "injected_count": 0,
        "injection_rate": None,
        "tier_counts": {},
        "score_bucket_counts": {},
        "margin_bucket_counts": {},
        "attributed_sessions": 0,
        "suggest_sessions": 0,
        "post_suggest_view_rate": None,
        "post_suggest_use_rate": None,
        "card_to_action_proxy_rate": None,
        "missed_after_hint_rate": None,
        "card_used_without_view": 0,
    }
    path = root / ".learning" / cli.EVENT_LOG
    if not path.is_file():
        return metrics

    sessions: dict[str, list[tuple[float, str, dict]]] = {}
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        metrics["total_events"] += 1
        etype = str(row.get("type") or "")
        payload = row.get("payload")
        if not isinstance(payload, dict):
            payload = {}
        try:
            ts = float(row.get("ts") or 0.0)
        except (TypeError, ValueError):
            ts = 0.0
        if etype == "suggest":
            metrics["suggest_count"] += 1
            _bump(metrics["score_bucket_counts"], payload.get("score_bucket"))
            _bump(metrics["margin_bucket_counts"], payload.get("margin_bucket"))
            tier = payload.get("delivery_tier")
            if tier is not None:
                metrics["carded_suggest_count"] += 1
                _bump(metrics["tier_counts"], tier)
            if payload.get("injected"):
                metrics["injected_count"] += 1
        sid = payload.get("session_correlation_id")
        if sid:
            sessions.setdefault(str(sid), []).append((ts, etype, payload))

    if metrics["carded_suggest_count"]:
        metrics["injection_rate"] = round(
            metrics["injected_count"] / metrics["carded_suggest_count"], 3
        )

    suggest_sessions = view_after = use_after = 0
    card_sessions = card_then_use = card_used_without_view = 0
    hint_sessions = hint_missed = 0
    for events in sessions.values():
        events.sort(key=lambda e: e[0])
        suggests = [e for e in events if e[1] == "suggest"]
        if not suggests:
            continue
        suggest_sessions += 1
        first_suggest_ts = suggests[0][0]
        has_view = any(t >= first_suggest_ts and et in _VIEW_EVENT_TYPES for (t, et, _p) in events)
        has_use = any(t >= first_suggest_ts and et in _USE_EVENT_TYPES for (t, et, _p) in events)
        if has_view:
            view_after += 1
        if has_use:
            use_after += 1
        injected_in_session = any(p.get("injected") for (_t, _et, p) in suggests)
        hint_in_session = any(p.get("delivery_tier") == 2 for (_t, _et, p) in suggests)
        if injected_in_session:
            card_sessions += 1
            if has_use:
                card_then_use += 1
            if has_use and not has_view:
                card_used_without_view += 1
        elif hint_in_session:
            hint_sessions += 1
            if not has_view and not has_use:
                hint_missed += 1

    metrics["attributed_sessions"] = len(sessions)
    metrics["suggest_sessions"] = suggest_sessions
    metrics["card_used_without_view"] = card_used_without_view
    if suggest_sessions:
        metrics["post_suggest_view_rate"] = round(view_after / suggest_sessions, 3)
        metrics["post_suggest_use_rate"] = round(use_after / suggest_sessions, 3)
    if card_sessions:
        metrics["card_to_action_proxy_rate"] = round(card_then_use / card_sessions, 3)
    if hint_sessions:
        metrics["missed_after_hint_rate"] = round(hint_missed / hint_sessions, 3)
    return metrics


def cmd_learning_summary(args: argparse.Namespace) -> int:
    root = Path(args.root).expanduser()
    feedback_path = root / ".learning" / cli.FEEDBACK_LOG
    counts: dict[str, dict[str, int]] = {}
    verdict_keys = (
        {"accepted": 0, "rejected": 0, "neutral": 0, "missed": 0, "wrong": 0}
        if getattr(args, "events", False)
        else {"accepted": 0, "rejected": 0, "neutral": 0}
    )
    if feedback_path.is_file():
        for line in feedback_path.read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            name = str(row.get("name") or "")
            verdict = str(row.get("verdict") or "")
            counts.setdefault(name, dict(verdict_keys))
            if verdict in counts[name]:
                counts[name][verdict] += 1
    if getattr(args, "events", False):
        payload = {"feedback": counts, "effectiveness": compute_event_metrics(root)}
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print(json.dumps(counts, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


def cmd_draft_skill(args: argparse.Namespace) -> int:
    root = Path(args.root).expanduser()
    slug = re.sub(r"[^a-zA-Z0-9_.-]+", "-", args.name.strip().lower()).strip("-") or "new-skill"
    body = "\n".join(
        [
            "---",
            f"name: {slug}",
            f"description: {args.description}",
            "---",
            "",
            f"# {args.name}",
            "",
            "Use this skill when the task matches the description above.",
            "",
            "## Workflow",
            "",
            "1. Inspect the task context and confirm that this skill is relevant.",
            "2. Follow the project-specific conventions before introducing new patterns.",
            "3. Verify the result on the real artifact or route when practical.",
            "",
            "## Evidence",
            "",
            args.evidence or "No evidence notes were provided.",
            "",
        ]
    )
    if args.write:
        target = root / "generated" / "skills" / slug / "SKILL.md"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(body, encoding="utf-8")
        print(target)
    else:
        print(body)
    return 0


def cmd_adapt(args: argparse.Namespace) -> int:
    root = Path(args.root).expanduser()
    results = adapt_library(
        root,
        collection=args.collection,
        source_pack=args.source_pack,
        source_repo=args.source_repo,
        force=args.force,
        dry_run=args.dry_run,
    )
    changed = [item for item in results if item.changed]
    payload = {
        "root": str(root),
        "collection": args.collection,
        "dry_run": args.dry_run,
        "count": len(results),
        "changed": len(changed),
        "items": [asdict(item) for item in changed[: args.limit]],
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def cmd_packs(args: argparse.Namespace) -> int:
    print(json.dumps(SKILL_PACKS, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


def cmd_install_pack(args: argparse.Namespace) -> int:
    root = Path(args.root).expanduser()
    results = install_pack(root, args.pack, ref=args.ref, keep_clone=Path(args.keep_clone).expanduser() if args.keep_clone else None)
    cli.save_index(root)
    payload = {
        "root": str(root),
        "pack": args.pack,
        "count": len(results),
        "items": [asdict(item) for item in results[: args.limit]],
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def cmd_sync_native(args: argparse.Namespace) -> int:
    root = Path(args.root).expanduser()
    agents = args.agent or list(DEFAULT_AGENT_ORDER)
    results = sync_native_sources(root, agents=agents, apply=not args.dry_run, refresh_collection=not args.no_refresh)
    reindexed = False
    if not args.dry_run and not args.skip_reindex:
        cli.save_index(root)
        reindexed = True
    payload = {
        "root": str(root),
        "dry_run": args.dry_run,
        "agents": agents,
        "reindexed": reindexed,
        "results": [asdict(item) for item in results],
    }
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0
    for item in results:
        status = "skipped" if item.skipped else f"{item.imported_count} skills"
        suffix = f" ({item.reason})" if item.reason else ""
        print(f"{item.collection}: {status}{suffix}")
        print(f"  source: {item.source_root}")
    if reindexed:
        print("Lexical index rebuilt.")
    return 0


def _print_import_report(report, *, as_json: bool) -> None:
    from dataclasses import asdict as _asdict

    if as_json:
        print(json.dumps(_asdict(report), ensure_ascii=False, indent=2))
        return
    verb = "Would import" if report.dry_run else "Imported"
    print(f"{verb} {len(report.imported)} skill(s) into local/{report.collection}")
    print(f"  source: {report.source}")
    if report.skipped_identical:
        print(f"  skipped (identical): {len(report.skipped_identical)}")
    if report.conflicts:
        print(f"  conflicts (same name, different content): {len(report.conflicts)}")
        for conflict in report.conflicts:
            print(f"    - {conflict.name}: {conflict.reason}")
            print(f"      incoming: {conflict.source_path}")
            print(f"      existing: {conflict.existing_path}")
        if not report.dry_run:
            print("  conflicting skills were copied to the collection's duplicates/ folder.")


def cmd_import_dir(args: argparse.Namespace) -> int:
    root = Path(args.root).expanduser()
    source = Path(args.path).expanduser()
    if not source.is_dir():
        print(f"Source directory not found: {source}", file=sys.stderr)
        return 1
    report = import_skill_dirs(source, root, args.collection, dry_run=args.dry_run)
    if not args.dry_run and not args.skip_reindex and report.imported:
        cli.save_index(root)
    _print_import_report(report, as_json=args.json)
    return 0


def cmd_import_github(args: argparse.Namespace) -> int:
    root = Path(args.root).expanduser()
    collection = args.collection or _collection_from_repo(args.repo)
    try:
        report = import_github_repo(
            root,
            args.repo,
            collection,
            ref=args.ref or "",
            subdir=args.subdir or "",
            dry_run=args.dry_run,
        )
    except (RuntimeError, OSError) as exc:
        print(f"Import failed: {exc}", file=sys.stderr)
        return 1
    if not args.dry_run and not args.skip_reindex and report.imported:
        cli.save_index(root)
    _print_import_report(report, as_json=args.json)
    return 0


def _collection_from_repo(repo: str) -> str:
    tail = repo.rstrip("/").split("/")[-1]
    return re.sub(r"[^a-z0-9._-]+", "-", tail.removesuffix(".git").lower()).strip("-.") or "imported"


def cmd_adapt_one(args: argparse.Namespace) -> int:
    root = Path(args.root).expanduser()
    path = cli.resolve_skill_path(root, args.name_or_path)
    if not path:
        print(f"Skill not found: {args.name_or_path}", file=sys.stderr)
        return 2
    print(json.dumps(adaptation_task(path, root=root, source_pack=args.source_pack, source_repo=args.source_repo), ensure_ascii=False, indent=2))
    return 0


def cmd_adapt_next(args: argparse.Namespace) -> int:
    root = Path(args.root).expanduser()
    path = next_skill_for_agent(root, collection=args.collection)
    if not path:
        print(json.dumps({"status": "done", "message": "No unprocessed skills found."}, ensure_ascii=False, indent=2))
        return 0
    print(json.dumps(adaptation_task(path, root=root, source_pack=args.source_pack, source_repo=args.source_repo), ensure_ascii=False, indent=2))
    return 0


def cmd_apply_adaptation(args: argparse.Namespace) -> int:
    root = Path(args.root).expanduser()
    data = json.loads(cli.read_text(Path(args.input).expanduser()))
    path_value = args.path or data.get("source_path") or data.get("path")
    if not path_value:
        print("Adaptation JSON must include source_path, or pass --path.", file=sys.stderr)
        return 2
    path = cli.resolve_skill_path(root, str(path_value))
    if not path:
        print(f"Skill not found: {path_value}", file=sys.stderr)
        return 2
    result = apply_agent_adaptation(
        path,
        root=root,
        data=data,
        source_pack=args.source_pack,
        source_repo=args.source_repo,
        dry_run=args.dry_run,
    )
    if not args.dry_run:
        cli.save_index(root)
    print(json.dumps(asdict(result), ensure_ascii=False, indent=2))
    return 0


def cmd_serve(args: argparse.Namespace) -> int:
    try:
        import uvicorn  # type: ignore
    except ImportError as exc:
        raise RuntimeError(
            "Install server dependencies with: pip install \"unlimited-skills[server]\" "
            "(or, from a repo clone: pip install -e \".[server]\")"
        ) from exc
    os.environ["UNLIMITED_SKILLS_ROOT"] = str(Path(args.root).expanduser())
    os.environ["UNLIMITED_SKILLS_EMBED_MODEL"] = args.model
    uvicorn.run("unlimited_skills.server:app", host=args.host, port=args.port, log_level=args.log_level)
    return 0


def cmd_doctor(args: argparse.Namespace) -> int:
    root = Path(args.root).expanduser()
    report = build_doctor_report(root, agent=args.agent)
    print(doctor_json(report) if args.json else format_doctor_text(report))
    return 0


def cmd_setup(args: argparse.Namespace) -> int:
    root = Path(args.root).expanduser()
    mode = "overview"
    if getattr(args, "setup_command", "") == "doctor":
        mode = "overview"
    elif args.local_only:
        mode = "local-only"
    elif args.registered:
        mode = "registered"
    elif args.hub:
        mode = "hub"
    elif args.enterprise:
        mode = "enterprise"
    elif args.private_packs:
        mode = "private-packs"
    payload = build_setup_report(root, mode=mode, dry_run=args.dry_run, agent=getattr(args, "agent", "all"))
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print(format_setup_text(payload))
    return 0


def cmd_quickstart(args: argparse.Namespace) -> int:
    """A1 golden path: bundled import (when empty) -> first search -> MCP savings."""
    from unlimited_skills.quickstart import format_quickstart_text, run_quickstart

    root = Path(args.root).expanduser()
    cli.enforce_local_root(root, action="quickstart library root")
    report = run_quickstart(
        root,
        query=args.query,
        claude_config=Path(args.claude_config).expanduser() if args.claude_config else None,
        timeout=args.timeout,
        skip_mcp_check=args.skip_mcp_check,
    )
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print(format_quickstart_text(report))
    return 0


def cmd_support_bundle(args: argparse.Namespace) -> int:
    root = Path(args.root).expanduser()
    out = Path(args.out).expanduser() if args.out else None
    report = build_bundle_report(
        root,
        out=out,
        dry_run=args.dry_run,
        include_paths=args.include_paths,
        include_private_pack_refs=args.include_private_pack_refs,
    )
    if args.json:
        print(json.dumps(report["manifest"], ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print(format_bundle_text(report))
    return 0
