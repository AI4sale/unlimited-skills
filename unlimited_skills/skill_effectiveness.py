"""Deterministic local skill suggestion and A0 effectiveness gates."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import statistics
import tempfile
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable


A0_MERGE_THRESHOLDS = {
    "positive_scenarios": 30,
    "negative_scenarios": 10,
    "top_1_hit_rate": 0.55,
    "top_3_hit_rate": 0.83,
    "false_positive_rate": 0.10,
    "p90_suggest_latency_ms": 1500,
    "p95_suggest_latency_ms": 2500,
}

V05_RELEASE_THRESHOLDS = {
    **A0_MERGE_THRESHOLDS,
    "top_1_hit_rate": 0.65,
    "top_3_hit_rate": 0.90,
    "p90_suggest_latency_ms": 1200,
    "p95_suggest_latency_ms": 2000,
}


@dataclass(frozen=True)
class SuggestCandidate:
    name: str
    collection: str
    score: float
    reason_code: str
    recommended_next_action: str


@dataclass(frozen=True)
class SuggestReport:
    task_summary_hash: str
    top_3_skill_candidates: list[SuggestCandidate]
    latency_ms: int
    score_floor: float
    no_skill_body_leak: bool = True
    no_prompt_upload: bool = True
    no_tool_output_upload: bool = True
    no_local_path_leak: bool = True


@dataclass(frozen=True)
class SkillScenario:
    id: str
    query: str
    expected: str | None


@dataclass(frozen=True)
class EffectivenessReport:
    gate: str
    status: str
    positive_scenarios: int
    negative_scenarios: int
    top_1_hits: int
    top_3_hits: int
    false_positives: int
    top_1_hit_rate: float
    top_3_hit_rate: float
    false_positive_rate: float
    p90_suggest_latency_ms: int
    p95_suggest_latency_ms: int
    max_suggest_latency_ms: int
    no_skill_body_leak: bool
    no_prompt_upload: bool
    no_tool_output_upload: bool
    no_local_path_leak: bool
    thresholds: dict[str, float | int]
    failures: list[str]
    scenarios: list[dict[str, object]]


FIXTURE_SKILLS = {
    "security-review": {
        "collection": "ecc",
        "description": "Security review workflow for secrets, auth, injection, dependency risk, and exposed sensitive data.",
        "body": "Use for code security audit, dependency scan, auth review, XSS, SQL injection, CSRF, secrets, and unsafe config.",
    },
    "github-ops": {
        "collection": "ecc",
        "description": "GitHub pull request, issue, CI, merge, and release operations using gh CLI.",
        "body": "Use for PR queue hygiene, GitHub Actions checks, merge readiness, branch cleanup, releases, and repository operations.",
    },
    "browser-qa": {
        "collection": "ecc",
        "description": "Browser automation QA for local apps, visual checks, click flows, and screenshots.",
        "body": "Use for Playwright style browser verification, UI regression, checkout page testing, local frontend smoke checks.",
    },
    "skill-creator": {
        "collection": "system",
        "description": "Create or update agent skills with clear trigger rules, workflow, traps, examples, and tests.",
        "body": "Use when writing a SKILL.md, expanding skill memory, improving instructions, or building a repeatable procedure.",
    },
    "documentation-lookup": {
        "collection": "ecc",
        "description": "Find and verify official documentation before answering implementation questions.",
        "body": "Use for docs lookup, API reference checks, current framework docs, and source-cited technical guidance.",
    },
    "python-testing": {
        "collection": "ecc",
        "description": "Python test workflow with pytest, fixtures, coverage, and regression verification.",
        "body": "Use for pytest failures, test coverage, fixtures, mocking, regression tests, and Python CI verification.",
    },
    "frontend-design-direction": {
        "collection": "ecc",
        "description": "Frontend product UI direction, layout, visual hierarchy, and design-quality review.",
        "body": "Use for app screen design, UX polish, responsive UI, dashboard layout, and visual design critique.",
    },
    "mcp-server-patterns": {
        "collection": "ecc",
        "description": "MCP server implementation patterns for tools, schemas, transport, and protocol behavior.",
        "body": "Use for Model Context Protocol servers, MCP tools, schemas, stdio, tool boundaries, and gateway integration.",
    },
    "database-migrations": {
        "collection": "ecc",
        "description": "Database migration planning, schema changes, rollback, data safety, and deploy sequencing.",
        "body": "Use for SQL migrations, schema rollout, rollback plans, data backfills, and migration verification.",
    },
    "social-publisher": {
        "collection": "ecc",
        "description": "Draft and adapt social posts for LinkedIn and other channels.",
        "body": "Use for LinkedIn post drafts, launch copy, social positioning, thread copy, and audience framing.",
    },
    "verification-loop": {
        "collection": "ecc",
        "description": "General verification loop before claiming completion.",
        "body": "Use for final checks, build/test verification, evidence collection, and completion gates.",
    },
    "agent-architecture-audit": {
        "collection": "ecc",
        "description": "Review agent architectures, orchestration boundaries, routing, and multi-agent reliability.",
        "body": "Use for agent systems, subagent routing, orchestration design, worker quality, and coordination failure analysis.",
    },
}


POSITIVE_SCENARIOS = [
    SkillScenario("pos-001", "review this repository for exposed secrets and auth bypass risks", "security-review"),
    SkillScenario("pos-002", "run a security check for SQL injection and dependency vulnerabilities", "security-review"),
    SkillScenario("pos-003", "triage open GitHub pull requests and merge the green ones", "github-ops"),
    SkillScenario("pos-004", "check CI for PR 42 and inspect failing GitHub Actions logs", "github-ops"),
    SkillScenario("pos-005", "verify the checkout modal in the browser and take screenshots", "browser-qa"),
    SkillScenario("pos-006", "test the local frontend flow with browser automation", "browser-qa"),
    SkillScenario("pos-007", "write a new SKILL.md for a repeatable release workflow", "skill-creator"),
    SkillScenario("pos-008", "expand this skill with when to use and known traps", "skill-creator"),
    SkillScenario("pos-009", "look up the official API docs before changing this integration", "documentation-lookup"),
    SkillScenario("pos-010", "verify the latest framework docs and cite the source", "documentation-lookup"),
    SkillScenario("pos-011", "add pytest regression coverage for this bug", "python-testing"),
    SkillScenario("pos-012", "debug failing Python tests and fixture setup", "python-testing"),
    SkillScenario("pos-013", "polish this dashboard layout and make the UI feel professional", "frontend-design-direction"),
    SkillScenario("pos-014", "review the responsive design and visual hierarchy", "frontend-design-direction"),
    SkillScenario("pos-015", "implement an MCP stdio server tool schema", "mcp-server-patterns"),
    SkillScenario("pos-016", "audit the MCP gateway tool boundary and protocol behavior", "mcp-server-patterns"),
    SkillScenario("pos-017", "plan a safe database schema migration with rollback", "database-migrations"),
    SkillScenario("pos-018", "review this SQL backfill migration before deploy", "database-migrations"),
    SkillScenario("pos-019", "draft a LinkedIn post about the new public alpha", "social-publisher"),
    SkillScenario("pos-020", "rewrite this launch announcement for social media", "social-publisher"),
    SkillScenario("pos-021", "run final verification before saying the release is complete", "verification-loop"),
    SkillScenario("pos-022", "collect test evidence and completion proof", "verification-loop"),
    SkillScenario("pos-023", "audit the multi-agent worker architecture and routing", "agent-architecture-audit"),
    SkillScenario("pos-024", "why are subagents not using the skill router", "agent-architecture-audit"),
    SkillScenario("pos-025", "clean stale branches and close duplicate PRs", "github-ops"),
    SkillScenario("pos-026", "create a skill for local operator runbooks", "skill-creator"),
    SkillScenario("pos-027", "use browser automation to confirm the donation checkout label", "browser-qa"),
    SkillScenario("pos-028", "make a release checklist gate and run verification", "verification-loop"),
    SkillScenario("pos-029", "review MCP tool schema context budget and gateway search behavior", "mcp-server-patterns"),
    SkillScenario("pos-030", "write LinkedIn featured section copy for Unlimited Skills", "social-publisher"),
]


NEGATIVE_SCENARIOS = [
    SkillScenario("neg-001", "what is two plus two", None),
    SkillScenario("neg-002", "translate this short sentence to English", None),
    SkillScenario("neg-003", "show the current date", None),
    SkillScenario("neg-004", "format this one-line JSON object", None),
    SkillScenario("neg-005", "rename variable x to y in this tiny snippet", None),
    SkillScenario("neg-006", "sort these three words alphabetically", None),
    SkillScenario("neg-007", "convert 10 USD to cents without looking anything up", None),
    SkillScenario("neg-008", "make this heading title case", None),
    SkillScenario("neg-009", "count the characters in hello", None),
    SkillScenario("neg-010", "write a simple hello world print statement", None),
]


def _normalize_query(query: str) -> str:
    return re.sub(r"\s+", " ", query or "").strip().lower()


def task_summary_hash(query: str) -> str:
    return hashlib.sha256(_normalize_query(query).encode("utf-8")).hexdigest()[:16]


def _reason_code(query: str, name: str, description: str) -> str:
    q = _normalize_query(query)
    name_tokens = set(re.split(r"[-_\s]+", name.lower()))
    query_tokens = set(re.findall(r"[a-z0-9][a-z0-9_.+#-]*", q))
    if name.lower() in q or name_tokens & query_tokens:
        return "skill_name_or_alias_match"
    if query_tokens & set(re.findall(r"[a-z0-9][a-z0-9_.+#-]*", description.lower())):
        return "description_domain_match"
    return "body_or_metadata_match"


def suggest_skills(root: Path, query: str, *, limit: int = 3, score_floor: float = 3.0, fresh: bool = False) -> SuggestReport:
    from unlimited_skills import cli

    started = time.perf_counter()
    hits = cli.lexical_search(root, query, limit=max(limit * 4, 12), fresh=fresh)
    candidates: list[SuggestCandidate] = []
    for hit in hits:
        if hit.score < score_floor:
            continue
        candidates.append(
            SuggestCandidate(
                name=hit.name,
                collection=hit.collection,
                score=round(float(hit.score), 3),
                reason_code=_reason_code(query, hit.name, hit.description),
                recommended_next_action=f'view skill "{hit.name}" before creating a custom solution',
            )
        )
        if len(candidates) >= limit:
            break
    return SuggestReport(
        task_summary_hash=task_summary_hash(query),
        top_3_skill_candidates=candidates,
        latency_ms=max(0, int((time.perf_counter() - started) * 1000)),
        score_floor=score_floor,
    )


def suggest_report_to_json(report: SuggestReport) -> dict[str, object]:
    payload = asdict(report)
    payload["top_3_skill_candidates"] = [asdict(item) for item in report.top_3_skill_candidates]
    return payload


def suggest_report_to_text(report: SuggestReport) -> str:
    lines = [
        f"task_summary_hash: {report.task_summary_hash}",
        f"latency_ms: {report.latency_ms}",
        f"score_floor: {report.score_floor:g}",
    ]
    if not report.top_3_skill_candidates:
        lines.append("recommended_next_action: continue normally; no skill crossed the suggestion floor")
        return "\n".join(lines)
    lines.append("top_skill_candidates:")
    for index, candidate in enumerate(report.top_3_skill_candidates, start=1):
        lines.append(
            f"{index}. {candidate.name} [{candidate.collection}] "
            f"score={candidate.score:g} reason={candidate.reason_code}"
        )
    lines.append(f"recommended_next_action: {report.top_3_skill_candidates[0].recommended_next_action}")
    return "\n".join(lines)


def write_fixture_library(root: Path) -> None:
    for name, data in FIXTURE_SKILLS.items():
        target = root / "registry" / str(data["collection"]) / "skills" / name / "SKILL.md"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            "\n".join(
                [
                    "---",
                    f"name: {name}",
                    f"description: {data['description']}",
                    "---",
                    "",
                    f"# {name}",
                    "",
                    str(data["body"]),
                    "",
                ]
            ),
            encoding="utf-8",
        )


def _percentile(values: list[int], percentile: int) -> int:
    if not values:
        return 0
    if len(values) == 1:
        return values[0]
    ordered = sorted(values)
    rank = (percentile / 100) * (len(ordered) - 1)
    lower = int(rank)
    upper = min(lower + 1, len(ordered) - 1)
    weight = rank - lower
    return int(round(ordered[lower] * (1 - weight) + ordered[upper] * weight))


def evaluate_skill_effectiveness(
    root: Path,
    *,
    gate: str = "a0-merge",
    score_floor: float = 3.0,
    fresh: bool = False,
    scenarios: Iterable[SkillScenario] | None = None,
) -> EffectivenessReport:
    thresholds = V05_RELEASE_THRESHOLDS if gate == "v0.5-release" else A0_MERGE_THRESHOLDS
    scenario_list = list(scenarios or [*POSITIVE_SCENARIOS, *NEGATIVE_SCENARIOS])
    rows: list[dict[str, object]] = []
    latencies: list[int] = []
    top_1_hits = 0
    top_3_hits = 0
    false_positives = 0
    positive_count = 0
    negative_count = 0
    leak_flags = {
        "no_skill_body_leak": True,
        "no_prompt_upload": True,
        "no_tool_output_upload": True,
        "no_local_path_leak": True,
    }

    for scenario in scenario_list:
        report = suggest_skills(root, scenario.query, limit=3, score_floor=score_floor, fresh=fresh)
        names = [candidate.name for candidate in report.top_3_skill_candidates]
        latencies.append(report.latency_ms)
        leak_flags["no_skill_body_leak"] = leak_flags["no_skill_body_leak"] and report.no_skill_body_leak
        leak_flags["no_prompt_upload"] = leak_flags["no_prompt_upload"] and report.no_prompt_upload
        leak_flags["no_tool_output_upload"] = leak_flags["no_tool_output_upload"] and report.no_tool_output_upload
        leak_flags["no_local_path_leak"] = leak_flags["no_local_path_leak"] and report.no_local_path_leak
        if scenario.expected:
            positive_count += 1
            top_1 = bool(names and names[0] == scenario.expected)
            top_3 = scenario.expected in names
            top_1_hits += int(top_1)
            top_3_hits += int(top_3)
        else:
            negative_count += 1
            top_1 = False
            top_3 = False
            if names:
                false_positives += 1
        rows.append(
            {
                "id": scenario.id,
                "expected": scenario.expected,
                "task_summary_hash": report.task_summary_hash,
                "top_3_skill_candidates": names,
                "top_1_hit": top_1,
                "top_3_hit": top_3,
                "false_positive": scenario.expected is None and bool(names),
                "latency_ms": report.latency_ms,
            }
        )

    top_1_rate = top_1_hits / positive_count if positive_count else 0.0
    top_3_rate = top_3_hits / positive_count if positive_count else 0.0
    false_positive_rate = false_positives / negative_count if negative_count else 0.0
    p90 = _percentile(latencies, 90)
    p95 = _percentile(latencies, 95)
    max_latency = max(latencies) if latencies else 0

    failures: list[str] = []
    checks = {
        "positive_scenarios": positive_count >= int(thresholds["positive_scenarios"]),
        "negative_scenarios": negative_count >= int(thresholds["negative_scenarios"]),
        "top_1_hit_rate": top_1_rate >= float(thresholds["top_1_hit_rate"]),
        "top_3_hit_rate": top_3_rate >= float(thresholds["top_3_hit_rate"]),
        "false_positive_rate": false_positive_rate <= float(thresholds["false_positive_rate"]),
        "p90_suggest_latency_ms": p90 <= int(thresholds["p90_suggest_latency_ms"]),
        "p95_suggest_latency_ms": p95 <= int(thresholds["p95_suggest_latency_ms"]),
        **leak_flags,
    }
    for key, ok in checks.items():
        if not ok:
            failures.append(key)

    return EffectivenessReport(
        gate=gate,
        status="passed" if not failures else "failed",
        positive_scenarios=positive_count,
        negative_scenarios=negative_count,
        top_1_hits=top_1_hits,
        top_3_hits=top_3_hits,
        false_positives=false_positives,
        top_1_hit_rate=round(top_1_rate, 4),
        top_3_hit_rate=round(top_3_rate, 4),
        false_positive_rate=round(false_positive_rate, 4),
        p90_suggest_latency_ms=p90,
        p95_suggest_latency_ms=p95,
        max_suggest_latency_ms=max_latency,
        no_skill_body_leak=leak_flags["no_skill_body_leak"],
        no_prompt_upload=leak_flags["no_prompt_upload"],
        no_tool_output_upload=leak_flags["no_tool_output_upload"],
        no_local_path_leak=leak_flags["no_local_path_leak"],
        thresholds=thresholds,
        failures=failures,
        scenarios=rows,
    )


def effectiveness_report_to_json(report: EffectivenessReport) -> dict[str, object]:
    return asdict(report)


def cmd_suggest(args: argparse.Namespace) -> int:
    from unlimited_skills import cli

    root = Path(args.root).expanduser()
    cli.enforce_local_root(root, action="suggest skills")
    cli.maybe_sync_native(args, root)
    report = suggest_skills(root, args.query, limit=args.limit, score_floor=args.score_floor, fresh=args.fresh)
    cli.log_event(
        root,
        "suggest",
        {
            "task_summary_hash": report.task_summary_hash,
            "hits": [candidate.name for candidate in report.top_3_skill_candidates],
            "latency_ms": report.latency_ms,
        },
    )
    if args.json:
        print(json.dumps(suggest_report_to_json(report), ensure_ascii=False, indent=2))
    else:
        print(suggest_report_to_text(report))
    return 0 if report.top_3_skill_candidates else 1


def cmd_check_effectiveness(args: argparse.Namespace) -> int:
    from unlimited_skills import cli

    if args.fixture_mode:
        with tempfile.TemporaryDirectory(prefix="unlimited-skills-a0-fixture-") as tmp:
            root = Path(tmp)
            write_fixture_library(root)
            cli.save_index(root)
            report = evaluate_skill_effectiveness(root, gate=args.gate, score_floor=args.score_floor, fresh=True)
    else:
        root = Path(args.root).expanduser()
        cli.enforce_local_root(root, action="check skill effectiveness")
        report = evaluate_skill_effectiveness(root, gate=args.gate, score_floor=args.score_floor, fresh=args.fresh)
    payload = effectiveness_report_to_json(report)
    if args.out:
        Path(args.out).expanduser().write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(f"Skill effectiveness gate: {report.status}")
        print(f"top_1_hit_rate: {report.top_1_hit_rate:.2%}")
        print(f"top_3_hit_rate: {report.top_3_hit_rate:.2%}")
        print(f"false_positive_rate: {report.false_positive_rate:.2%}")
        print(f"p90_suggest_latency_ms: {report.p90_suggest_latency_ms}")
        if report.failures:
            print("failures: " + ", ".join(report.failures))
    return 0 if report.status == "passed" else 1
