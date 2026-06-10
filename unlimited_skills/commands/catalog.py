"""Hosted catalog browsing, quality, feedback, and maintainer-queue commands."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path

from unlimited_skills import cli
from unlimited_skills.catalog_browser import CatalogBrowserClient
from unlimited_skills.catalog_feedback import CatalogFeedbackClient, build_feedback_payload
from unlimited_skills.catalog_quality import CatalogQualityClient, dumps_status
from unlimited_skills.maintainer_queue_status import MaintainerQueueStatusClient, dumps_queue
from unlimited_skills.plan_status import redacted_plan_summary
from unlimited_skills.policy import load_policy, policy_summary
from unlimited_skills.recommendation_preview import build_policy_aware_preview, dumps_preview, fixture_preview
from unlimited_skills.registration import load_registration
from unlimited_skills.skill_improvements import SkillImprovementClient, dumps_improvement
from unlimited_skills.updates import UpdateClient


def cmd_catalog_list(args: argparse.Namespace) -> int:
    root = Path(args.root).expanduser()
    client = UpdateClient(load_registration(), timeout=args.timeout, channel=args.channel)
    payload = client.catalog(root)
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


def _emit_catalog_browser_items(items, *, as_json: bool, show_quality: bool = False) -> int:
    payload = {"count": len(items), "items": [asdict(item) for item in items]}
    if as_json:
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    if not items:
        print("No catalog items found.")
        return 0
    for item in items:
        label = item.pack_id or item.item_id
        suffix = f" {item.version}" if item.version else ""
        status = item.review_status
        marker = "installable" if item.installable else "not-installable"
        print(f"{item.item_id}: {label}{suffix} [{item.source}/{status}/{marker}]")
        if item.description:
            print(f"  {item.description}")
        if item.warnings:
            print("  warnings: " + ", ".join(item.warnings))
        if show_quality and item.quality_grade:
            print(f"  quality: {item.quality_grade.upper()} / {item.score_band or 'unknown'}")
            if item.last_eval_at:
                print(f"  last eval: {item.last_eval_at}")
            if item.blockers:
                print("  blockers: " + ", ".join(item.blockers))
            if item.compatibility_notes:
                print("  compatibility: " + ", ".join(item.compatibility_notes))
            if item.feedback_issue_categories:
                print("  feedback issues: " + ", ".join(item.feedback_issue_categories))
    return 0


def _catalog_client(args: argparse.Namespace) -> CatalogBrowserClient:
    return CatalogBrowserClient(load_registration(), timeout=args.timeout)


def _catalog_feedback_client(args: argparse.Namespace) -> CatalogFeedbackClient:
    return CatalogFeedbackClient(load_registration(), timeout=args.timeout)


def _catalog_quality_client(args: argparse.Namespace) -> CatalogQualityClient:
    return CatalogQualityClient(load_registration(), timeout=args.timeout)


def _skill_improvement_client(args: argparse.Namespace) -> SkillImprovementClient:
    return SkillImprovementClient(load_registration(), timeout=args.timeout)


def _maintainer_queue_client(args: argparse.Namespace) -> MaintainerQueueStatusClient:
    return MaintainerQueueStatusClient(load_registration(), timeout=args.timeout)


def cmd_catalog_browse(args: argparse.Namespace) -> int:
    root = Path(args.root).expanduser()
    items = _catalog_client(args).browse(
        root,
        channel=args.channel,
        source=args.source,
        compatible_agent=args.compatible_agent,
        skill_kind=args.skill_kind,
        category=args.category,
        include_deprecated=args.include_deprecated,
        show_quality=args.show_quality,
        limit=args.limit,
    )
    return _emit_catalog_browser_items(items, as_json=args.json, show_quality=args.show_quality)


def cmd_catalog_search(args: argparse.Namespace) -> int:
    root = Path(args.root).expanduser()
    items = _catalog_client(args).search(
        root,
        query=args.query,
        channel=args.channel,
        source=args.source,
        compatible_agent=args.compatible_agent,
        skill_kind=args.skill_kind,
        category=args.category,
        include_deprecated=args.include_deprecated,
        show_quality=args.show_quality,
        limit=args.limit,
    )
    return _emit_catalog_browser_items(items, as_json=args.json, show_quality=args.show_quality)


def cmd_catalog_filters(args: argparse.Namespace) -> int:
    payload = _catalog_client(args).filters(channel=args.channel)
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


def cmd_catalog_preview(args: argparse.Namespace) -> int:
    payload = _catalog_client(args).preview(args.item_id, channel=args.channel)
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    item = payload["item"]
    preview = item.get("preview", {}) if isinstance(item.get("preview"), dict) else {}
    print(f"{item.get('item_id')}: {item.get('pack_id')} {item.get('version', '')} [{item.get('source')}/{item.get('review_status')}]")
    if preview.get("description") or item.get("description"):
        print(preview.get("description") or item.get("description"))
    if preview.get("requirements"):
        print("Requirements: " + ", ".join(str(value) for value in preview["requirements"]))
    if item.get("warnings"):
        print("Warnings: " + ", ".join(str(value) for value in item["warnings"]))
    return 0


def cmd_catalog_recommendation_preview(args: argparse.Namespace) -> int:
    root = Path(args.root).expanduser()
    if args.fixture_case:
        payload = fixture_preview(args.fixture_case)
    else:
        if not args.item_id:
            raise RuntimeError("catalog recommendation-preview requires item_id unless --fixture-case is used.")
        state = load_registration()
        if not state.registered:
            payload = build_policy_aware_preview(
                catalog_item={
                    "item_id": args.item_id,
                    "source_type": "hosted_official",
                    "review_status": "registration_required",
                    "requires_registration": True,
                    "installable": False,
                },
                registered=False,
                signed_metadata=True,
                active_agent=args.agent,
                channel=args.channel or "stable",
                entitlement_status=redacted_plan_summary(state=state),
                policy_status=policy_summary(load_policy()),
            )
        else:
            catalog_payload = _catalog_client(args).preview(args.item_id, channel=args.channel)
            item = catalog_payload.get("item") if isinstance(catalog_payload.get("item"), dict) else {}
            quality_status = None
            improvement_status = None
            for label, loader in (
                ("quality", lambda: _catalog_quality_client(args).quality(args.item_id)),
                ("improvement", lambda: _skill_improvement_client(args).improvement_status(root, args.item_id)),
            ):
                try:
                    if label == "quality":
                        quality_status = loader()
                    else:
                        improvement_status = loader()
                except Exception:
                    if args.strict_supplemental:
                        raise
            payload = build_policy_aware_preview(
                catalog_item=item,
                signed_metadata=True,
                registered=True,
                active_agent=args.agent,
                channel=args.channel or str(item.get("channel") or "stable"),
                quality_status=quality_status,
                improvement_status=improvement_status,
                entitlement_status=redacted_plan_summary(state=state),
                policy_status=policy_summary(load_policy()),
            )
    if args.json:
        print(dumps_preview(payload))
        return 0
    decision = payload["decision"]
    print(f"Item: {payload['item_id']}")
    print("Preview only: yes")
    print(f"Outcome: {decision['outcome']}")
    print(f"Reason: {decision['reason']}")
    print(f"Next: {decision['next_command']}")
    if decision.get("refusal_code"):
        print(f"Refusal: {decision['refusal_code']}")
        print(f"Owner: {decision.get('owner') or '(unknown)'}")
        print(f"Fallback: {decision.get('fallback') or '(none)'}")
    print("No install, update, remove, rewrite, telemetry, or catalog distribution was performed.")
    return 0


def cmd_catalog_install(args: argparse.Namespace) -> int:
    root = Path(args.root).expanduser()
    if not args.dry_run and not args.yes:
        if not sys.stdin.isatty():
            raise RuntimeError("Catalog install requires --yes in non-interactive mode.")
        typed = input("Type INSTALL to install this signed catalog item: ")
        if typed.strip() != "INSTALL":
            raise RuntimeError("Catalog install cancelled.")
    result = _catalog_client(args).install(
        root,
        item_id=args.item_id,
        dry_run=args.dry_run,
        yes=args.yes,
        target_collection=args.collection,
        skip_reindex=args.skip_reindex,
    )
    reindexed = False
    if isinstance(result, dict) and result.get("installed") and not args.skip_reindex:
        cli.save_index(root)
        reindexed = True
        result["reindexed"] = True
    if args.json or args.dry_run:
        payload = asdict(result) if hasattr(result, "__dataclass_fields__") else result
        if isinstance(payload, dict) and "reindexed" not in payload:
            payload["reindexed"] = reindexed
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print(f"Installed catalog item {args.item_id}")
        if reindexed:
            print("Lexical index rebuilt.")
    return 0


def _catalog_feedback_detail_from_args(args: argparse.Namespace) -> dict[str, object]:
    detail: dict[str, object] = {}
    for key, attr in (
        ("agent", "agent"),
        ("client_version", "client_version"),
        ("core_version", "core_version"),
        ("os", "os"),
        ("command", "command"),
        ("error_code", "error_code"),
        ("expected_behavior", "expected_behavior"),
        ("actual_behavior", "actual_behavior"),
        ("reproduction_hint", "reproduction_hint"),
    ):
        value = getattr(args, attr, "")
        if value:
            detail[key] = value
    if args.http_status:
        detail["http_status"] = int(args.http_status)
    return detail


def cmd_catalog_feedback(args: argparse.Namespace) -> int:
    payload = build_feedback_payload(
        item_id=args.item_id,
        feedback_type=args.type,
        severity=args.severity,
        title=args.title,
        detail=_catalog_feedback_detail_from_args(args),
    )
    if args.dry_run:
        print(json.dumps({"dry_run": True, "payload": payload.to_json(), "privacy": {"automatic_telemetry": False}}, ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    if not args.yes:
        if not sys.stdin.isatty():
            raise RuntimeError("Catalog feedback submit requires --yes in non-interactive mode.")
        typed = input("Type SEND to submit this redacted catalog feedback: ")
        if typed.strip() != "SEND":
            raise RuntimeError("Catalog feedback cancelled.")
    response = _catalog_feedback_client(args).submit(payload)
    if args.json:
        print(json.dumps(response, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print(f"Catalog feedback submitted: {response.get('feedback_id', '')}")
    return 0


def cmd_catalog_feedback_status(args: argparse.Namespace) -> int:
    response = _catalog_feedback_client(args).status(args.item_id, limit=args.limit)
    if args.json:
        print(json.dumps(response, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print(f"Feedback count: {response.get('feedback_count', 0)}")
        for key, value in sorted((response.get("counts_by_status") or {}).items()):
            print(f"{key}: {value}")
    return 0


def cmd_catalog_quality(args: argparse.Namespace) -> int:
    status = _catalog_quality_client(args).quality(args.item_id)
    if args.json:
        print(dumps_status(status))
        return 0
    print(f"Item: {status.item_id}")
    print(f"Quality: {status.quality_grade.upper()} ({status.score_band})")
    print(f"Last eval: {status.last_eval_at or '(unknown)'}")
    print(f"Install risk: {status.install_risk}")
    print(f"Deprecation: {status.deprecation_status}")
    if status.blockers:
        print("Blockers: " + ", ".join(status.blockers))
    if status.warnings:
        print("Warnings: " + ", ".join(status.warnings))
    if status.compatibility_notes:
        print("Compatibility: " + ", ".join(status.compatibility_notes))
    if status.feedback_issue_categories:
        print("Feedback issues: " + ", ".join(status.feedback_issue_categories))
    return 0


def cmd_catalog_eval_status(args: argparse.Namespace) -> int:
    status = _catalog_quality_client(args).eval_status(args.item_id)
    if args.json:
        print(dumps_status(status))
        return 0
    print(f"Item: {status.item_id}")
    print(f"Evaluation: {status.evaluation_status}")
    print(f"Quality: {status.quality_grade.upper()} ({status.score_band})")
    print(f"Last eval: {status.last_eval_at or '(unknown)'}")
    if status.next_eval_at:
        print(f"Next eval: {status.next_eval_at}")
    if status.blockers:
        print("Blockers: " + ", ".join(status.blockers))
    if status.warnings:
        print("Warnings: " + ", ".join(status.warnings))
    if status.compatibility_notes:
        print("Compatibility: " + ", ".join(status.compatibility_notes))
    if status.feedback_issue_categories:
        print("Feedback issues: " + ", ".join(status.feedback_issue_categories))
    return 0


def cmd_catalog_explain_risk(args: argparse.Namespace) -> int:
    payload = _catalog_quality_client(args).explain_risk(args.item_id)
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    status = payload["quality_status"]
    print(f"Item: {payload['item_id']}")
    print(f"Quality: {str(status.get('quality_grade') or 'unknown').upper()} ({status.get('score_band') or 'unknown'})")
    print("Blocked: " + ("yes" if payload["blocked"] else "no"))
    print("Warning: " + ("yes" if payload["warning"] else "no"))
    print(payload["message"])
    blockers = status.get("blockers") or []
    warnings = status.get("warnings") or []
    if blockers:
        print("Blockers: " + ", ".join(str(item) for item in blockers))
    if warnings:
        print("Warnings: " + ", ".join(str(item) for item in warnings))
    return 0


def cmd_catalog_improvement_status(args: argparse.Namespace) -> int:
    root = Path(args.root).expanduser()
    status = _skill_improvement_client(args).improvement_status(root, args.item_id)
    queue_status = _maintainer_queue_client(args).status(root, args.item_id) if getattr(args, "include_queue", False) else None
    if args.json:
        payload = status.to_json()
        if queue_status is not None:
            payload["maintainer_queue"] = queue_status.to_json()
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    print(f"Item: {status.item_id}")
    print(f"Installed version: {status.installed_version or '(unknown)'}")
    print(f"Recommended: {status.recommended_version or '(none)'} on {status.recommended_channel}")
    print(f"Open issues: {status.open_issue_count}")
    if status.severity_summary:
        print("Severity: " + ", ".join(f"{key}={value}" for key, value in sorted(status.severity_summary.items())))
    print(f"Fix status: {status.fix_status}")
    print("Stale installed version: " + ("yes" if status.stale_installed_version else "no"))
    print(f"Recommended action: {status.recommended_action}")
    print("Deprecated: " + ("yes" if status.deprecated else "no"))
    print("Retired: " + ("yes" if status.retired else "no"))
    if status.deprecation_reason:
        print(f"Deprecation reason: {status.deprecation_reason}")
    if status.retirement_reason:
        print(f"Retirement reason: {status.retirement_reason}")
    if status.compatibility_notes:
        print("Compatibility: " + ", ".join(status.compatibility_notes))
    if queue_status is not None:
        print(f"Queue status: {queue_status.queue_status}")
        print(f"Maintainer state: {queue_status.maintainer_state}")
        if queue_status.severity_summary:
            print("Queue severity: " + ", ".join(f"{key}={value}" for key, value in sorted(queue_status.severity_summary.items())))
        if queue_status.fixed_pending_eval_evidence_ref:
            print(f"Fixed pending eval evidence: {queue_status.fixed_pending_eval_evidence_ref}")
        if queue_status.eval_gate_ref:
            print(f"Eval gate: {queue_status.eval_gate_ref}")
        print(f"Queue recommended action: {queue_status.recommended_user_action}")
    return 0


def cmd_catalog_maintainer_status(args: argparse.Namespace) -> int:
    root = Path(args.root).expanduser()
    status = _maintainer_queue_client(args).status(root, args.item_id)
    if args.json:
        print(dumps_queue(status))
        return 0
    print(f"Item: {status.item_id}")
    print(f"Queue status: {status.queue_status}")
    print(f"Maintainer state: {status.maintainer_state}")
    if status.severity_summary:
        print("Severity: " + ", ".join(f"{key}={value}" for key, value in sorted(status.severity_summary.items())))
    if status.issue_categories:
        print("Issue categories: " + ", ".join(status.issue_categories))
    if status.fixed_pending_eval_evidence_ref:
        print(f"Fixed pending eval evidence: {status.fixed_pending_eval_evidence_ref}")
    if status.eval_gate_ref:
        print(f"Eval gate: {status.eval_gate_ref}")
    print(f"Recommended action: {status.recommended_user_action}")
    if status.updated_at:
        print(f"Updated: {status.updated_at}")
    return 0


def cmd_catalog_maintainer_queue_summary(args: argparse.Namespace) -> int:
    root = Path(args.root).expanduser()
    summary = _maintainer_queue_client(args).summary(root)
    if args.json:
        print(dumps_queue(summary))
        return 0
    print("Maintainer queue summary")
    print(f"Total: {summary.total_count}")
    if summary.queue_status_counts:
        print("Queue statuses: " + ", ".join(f"{key}={value}" for key, value in sorted(summary.queue_status_counts.items())))
    if summary.severity_summary:
        print("Severity: " + ", ".join(f"{key}={value}" for key, value in sorted(summary.severity_summary.items())))
    if summary.maintainer_state_counts:
        print("Maintainer states: " + ", ".join(f"{key}={value}" for key, value in sorted(summary.maintainer_state_counts.items())))
    if summary.issue_categories:
        print("Issue categories: " + ", ".join(summary.issue_categories))
    print(f"Fixed pending eval: {summary.fixed_pending_eval_count}")
    print(f"Blocked eval gates: {summary.blocked_eval_gate_count}")
    return 0


def cmd_catalog_fixed_pending_eval(args: argparse.Namespace) -> int:
    root = Path(args.root).expanduser()
    status = _maintainer_queue_client(args).fixed_pending_eval(root, args.item_id)
    if args.json:
        print(dumps_queue(status))
        return 0
    print(f"Item: {status.item_id}")
    print("Fixed pending eval: " + ("yes" if status.fixed_pending_eval else "no"))
    print(f"Queue status: {status.queue_status}")
    print(f"Maintainer state: {status.maintainer_state}")
    if status.severity_summary:
        print("Severity: " + ", ".join(f"{key}={value}" for key, value in sorted(status.severity_summary.items())))
    if status.issue_categories:
        print("Issue categories: " + ", ".join(status.issue_categories))
    if status.evidence_ref:
        print(f"Evidence: {status.evidence_ref}")
    if status.eval_gate_ref:
        print(f"Eval gate: {status.eval_gate_ref}")
    print(f"Recommended action: {status.recommended_user_action}")
    return 0


def cmd_catalog_known_issues(args: argparse.Namespace) -> int:
    root = Path(args.root).expanduser()
    status = _skill_improvement_client(args).known_issues(root, args.item_id)
    if args.json:
        print(dumps_improvement(status))
        return 0
    print(f"Item: {status.item_id}")
    print(f"Open issues: {status.open_issue_count}")
    if status.severity_summary:
        print("Severity: " + ", ".join(f"{key}={value}" for key, value in sorted(status.severity_summary.items())))
    print(f"Fix status: {status.fix_status}")
    for issue in status.issues:
        label = issue.issue_id or "(issue)"
        title = f": {issue.title}" if issue.title else ""
        print(f"- {label} [{issue.severity}/{issue.status}/{issue.fix_status}]{title}")
        if issue.fixed_in_version:
            print(f"  fixed in: {issue.fixed_in_version}")
        if issue.compatibility_notes:
            print("  compatibility: " + ", ".join(issue.compatibility_notes))
    if status.compatibility_notes:
        print("Compatibility: " + ", ".join(status.compatibility_notes))
    return 0


def cmd_catalog_update_recommendations(args: argparse.Namespace) -> int:
    root = Path(args.root).expanduser()
    recommendations = _skill_improvement_client(args).update_recommendations(root)
    queue_summary = _maintainer_queue_client(args).summary(root) if getattr(args, "include_queue", False) else None
    queue_by_item = {}
    if getattr(args, "include_queue", False):
        queue_client = _maintainer_queue_client(args)
        for recommendation in recommendations:
            queue_by_item[recommendation.item_id] = queue_client.status(root, recommendation.item_id).to_json()
    recommendation_payloads = []
    for item in recommendations:
        item_payload = item.to_json()
        if item.item_id in queue_by_item:
            item_payload["maintainer_queue_status"] = queue_by_item[item.item_id]
        recommendation_payloads.append(item_payload)
    payload = {
        "schema_version": 1,
        "count": len(recommendations),
        "preview_only": True,
        "automatic_update": False,
        "automatic_install": False,
        "automatic_remove": False,
        "include_queue": bool(getattr(args, "include_queue", False)),
        "recommendations": recommendation_payloads,
    }
    if queue_summary is not None:
        payload["maintainer_queue_summary"] = queue_summary.to_json()
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    if not recommendations:
        print("No skill update recommendations.")
        return 0
    print("Skill update recommendations (preview only):")
    for item in recommendations:
        print(
            f"{item.item_id}: {item.recommended_action} "
            f"{item.installed_version or '(unknown)'} -> {item.recommended_version or '(none)'} "
            f"on {item.recommended_channel}"
        )
        print(f"  stale: {'yes' if item.stale_installed_version else 'no'}; open issues: {item.open_issue_count}; fix status: {item.fix_status}")
        if item.reason:
            print(f"  reason: {item.reason}")
        if item.compatibility_notes:
            print("  compatibility: " + ", ".join(item.compatibility_notes))
        if item.item_id in queue_by_item:
            queue = queue_by_item[item.item_id]
            print(
                "  queue: "
                f"{queue.get('queue_status', 'unknown')}; "
                f"maintainer state: {queue.get('maintainer_state', 'unknown')}; "
                f"recommended action: {queue.get('recommended_user_action', 'none')}"
            )
    if queue_summary is not None:
        print(f"Maintainer queue total: {queue_summary.total_count}")
    return 0


def cmd_catalog_update_preview(args: argparse.Namespace) -> int:
    root = Path(args.root).expanduser()
    recommendation = _skill_improvement_client(args).update_preview(root, args.item_id)
    if args.json:
        print(dumps_improvement(recommendation))
        return 0
    print(f"Item: {recommendation.item_id}")
    print("Preview only: yes")
    print(f"Recommended action: {recommendation.recommended_action}")
    print(f"Installed version: {recommendation.installed_version or '(unknown)'}")
    print(f"Recommended: {recommendation.recommended_version or '(none)'} on {recommendation.recommended_channel}")
    print("Stale installed version: " + ("yes" if recommendation.stale_installed_version else "no"))
    print(f"Open issues: {recommendation.open_issue_count}")
    if recommendation.severity_summary:
        print("Severity: " + ", ".join(f"{key}={value}" for key, value in sorted(recommendation.severity_summary.items())))
    print(f"Fix status: {recommendation.fix_status}")
    if recommendation.reason:
        print(f"Reason: {recommendation.reason}")
    if recommendation.compatibility_notes:
        print("Compatibility: " + ", ".join(recommendation.compatibility_notes))
    print("No update, install, or remove operation was performed.")
    return 0


def cmd_catalog_deprecation_status(args: argparse.Namespace) -> int:
    root = Path(args.root).expanduser()
    status = _skill_improvement_client(args).deprecation_status(root, args.item_id)
    if args.json:
        print(dumps_improvement(status))
        return 0
    print(f"Item: {status.item_id}")
    print("Deprecated: " + ("yes" if status.deprecated else "no"))
    print("Retired: " + ("yes" if status.retired else "no"))
    if status.deprecation_reason:
        print(f"Deprecation reason: {status.deprecation_reason}")
    if status.retirement_reason:
        print(f"Retirement reason: {status.retirement_reason}")
    if status.replacement_item_id:
        print(f"Replacement: {status.replacement_item_id}")
    print(f"Recommended action: {status.recommended_action}")
    if status.recommended_version:
        print(f"Recommended: {status.recommended_version} on {status.recommended_channel}")
    if status.compatibility_notes:
        print("Compatibility: " + ", ".join(status.compatibility_notes))
    return 0
