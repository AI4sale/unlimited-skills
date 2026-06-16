from __future__ import annotations

import argparse
import json
import math
import os
import re
import sys
import time
import warnings
from dataclasses import asdict, dataclass
from functools import lru_cache
from pathlib import Path
from typing import Iterable

from . import __version__
from .adapters import SKILL_PACKS, adapt_library, apply_agent_adaptation, adaptation_task, import_github_repo, import_skill_dirs, install_pack, next_skill_for_agent
from .catalog_browser import CatalogBrowserClient
from .catalog_feedback import CatalogFeedbackClient, build_feedback_payload
from .catalog_quality import CatalogQualityClient, dumps_status
from .community import (
    CommunityClient,
    build_submission_draft,
    confirm_upload_or_fail,
    list_installed_community_items,
    remove_community_item,
)
from .billing_status import doctor as billing_doctor
from .billing_status import format_billing_status, redacted_billing_summary, refresh_billing_status
from .doctor import build_doctor_report, doctor_json, format_doctor_text
from .search_core import (  # noqa: F401 - re-exported for backwards compatibility
    DEFAULT_ROOT,
    ECOSYSTEM_PENALTY,
    ECOSYSTEM_TOKEN_GROUPS,
    EVENT_LOG,
    IGNORED_SKILL_PATH_PARTS,
    INDEX_NAME,
    QUERY_EXPANSIONS,
    WORD_RE,
    SkillHit,
    build_index,
    collection_for,
    ecosystem_factor,
    expanded_query,
    event_safe_payload,
    find_by_name,
    first_body_line,
    hash_session_id,
    index_path,
    iter_skills,
    lexical_search,
    load_records,
    log_event,
    read_text,
    save_index,
    score_skill,
    session_correlation_id,
    skill_identity,
    skill_priority,
    split_frontmatter,
    tokens,
    write_jsonl,
)
from .hub import (
    HUB_DEFAULT_PORT,
    cmd_hub_clients,
    cmd_hub_doctor,
    cmd_hub_heartbeat,
    cmd_hub_init,
    cmd_hub_license_refresh,
    cmd_hub_license_status,
    cmd_hub_serve,
    cmd_hub_status,
    cmd_hub_sync,
    cmd_hub_token_create,
    cmd_hub_token_list,
    cmd_hub_token_revoke,
    cmd_remote_configure,
    cmd_remote_capabilities,
    cmd_remote_install_plan,
    cmd_remote_resolve,
    cmd_remote_search,
    cmd_remote_status,
    cmd_remote_view,
    cmd_trust_import,
    cmd_trust_keys,
    cmd_trust_revoke,
    cmd_trust_status,
    cmd_trust_verify,
    redacted_runtime_error,
)
from .maintainer_queue_status import MaintainerQueueStatusClient, dumps_queue
from .registration import (
    DEFAULT_SERVICE_URL,
    load_registration,
    registration_path,
    redacted_status,
    register_installation,
    save_registration,
    set_telemetry,
)
from .recommendation_preview import build_policy_aware_preview, dumps_preview, fixture_preview
from .service_diagnostics import (
    configure_service,
    doctor as service_doctor,
    local_status as service_status,
    registration_dry_run,
    test_proof as service_test_proof,
    verify_trust as service_verify_trust,
)
from .setup_wizard import build_setup_report, format_setup_text
from .skill_improvements import SkillImprovementClient, dumps_improvement
from .support_bundle import build_bundle_report, format_bundle_text
from .native import DEFAULT_AGENT_ORDER, sync_native_sources
from .org_status import local_org_status, refresh_org_status
from .plan_status import doctor as plan_doctor
from .plan_status import explain_feature, format_plan_status, redacted_plan_summary, refresh_plan_status
from .policy import explain_policy, install_policy, load_policy, policy_summary, read_policy_file, remove_policy, verify_policy_payload
from .policy_enforcement import enforce_local_root
from .policy_sync import managed_policy_status, sync_managed_policy
from .private_pack_diagnostics import private_pack_doctor
from .private_packs import PrivatePackClient, list_installed_private_packs, remove_private_pack
from .self_update import DEFAULT_PUBLIC_REPO, apply_public_repo_update, check_public_repo_update
from .team import (
    TeamClient,
    TeamError,
    collection_to_json,
    load_team_state,
    member_to_json,
    parse_duration_hours,
    redacted_team_status,
    save_team_state,
    team_state_path,
    team_state_with_mode,
    write_team_audit,
)
from .updates import UpdateClient, load_release_channel, rollback_collection, save_release_channel


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

# When executed as `python -m unlimited_skills.cli` this file runs as
# `__main__`. Register it as `unlimited_skills.cli` too so the command
# submodules (which import this module back) reuse this very module instead
# of re-executing cli.py against partially initialized command modules.
sys.modules.setdefault("unlimited_skills.cli", sys.modules[__name__])

VECTOR_META_NAME = ".unlimited-skills-vector.json"
VECTOR_SIDECAR_NAME = ".unlimited-skills-vectors.json"
CHROMA_DIR_NAME = ".chroma-skills"
CHROMA_COLLECTION = "unlimited_skills_v1"
FEEDBACK_LOG = "feedback.jsonl"
DEFAULT_EMBED_MODEL = os.environ.get(
    "UNLIMITED_SKILLS_EMBED_MODEL",
    "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
)


def vector_text(hit: SkillHit, body: str) -> str:
    lines = []
    running_len = 0
    for line in body.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("```"):
            continue
        lines.append(stripped)
        running_len += len(stripped)
        if running_len > 3500:
            break
    return "\n".join(
        [
            f"Skill: {hit.name}",
            f"Collection: {hit.collection}",
            f"Description: {hit.description}",
            "Body:",
            "\n".join(lines),
        ]
    )[:5000]


def ensure_embedding_deps():
    try:
        from fastembed import TextEmbedding  # type: ignore
    except ImportError as exc:
        raise RuntimeError("Install vector dependencies with: pip install 'unlimited-skills[vector]'") from exc
    return TextEmbedding


def ensure_chroma_deps():
    try:
        import chromadb  # type: ignore
    except ImportError as exc:
        raise RuntimeError("Install vector dependencies with: pip install 'unlimited-skills[vector]'") from exc
    return chromadb


def chroma_client(root: Path):
    chromadb = ensure_chroma_deps()
    return chromadb.PersistentClient(path=str(root / CHROMA_DIR_NAME))


def embed_texts(texts: list[str], model_name: str) -> list[list[float]]:
    model = embedding_model(model_name)
    return [vec.tolist() if hasattr(vec, "tolist") else list(vec) for vec in model.embed(texts)]


@lru_cache(maxsize=4)
def embedding_model(model_name: str):
    TextEmbedding = ensure_embedding_deps()
    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", message=".*now uses mean pooling.*")
        return TextEmbedding(model_name=model_name)


def vector_sidecar_path(root: Path) -> Path:
    return root / VECTOR_SIDECAR_NAME


def vector_meta_path(root: Path) -> Path:
    return root / VECTOR_META_NAME


def cosine_similarity(left: list[float], right: list[float]) -> float:
    if not left or not right or len(left) != len(right):
        return 0.0
    dot = 0.0
    left_norm = 0.0
    right_norm = 0.0
    for l_value, r_value in zip(left, right):
        dot += l_value * r_value
        left_norm += l_value * l_value
        right_norm += r_value * r_value
    if left_norm <= 0.0 or right_norm <= 0.0:
        return 0.0
    return dot / (math.sqrt(left_norm) * math.sqrt(right_norm))


class VectorModelMismatch(RuntimeError):
    """The on-disk vector index was built with a different embedding model."""


def _model_mismatch_error(built_with: str, requested: str, index_path: Path) -> VectorModelMismatch:
    return VectorModelMismatch(
        f"Vector index was built with embedding model '{built_with}' but the current model is '{requested}' "
        f"({index_path}). Run `unlimited-skills vector-reindex` to rebuild the index with the current model."
    )


def load_vector_sidecar(root: Path, model: str) -> list[dict] | None:
    path = vector_sidecar_path(root)
    if not path.is_file():
        return None
    try:
        payload = json.loads(read_text(path))
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Vector sidecar is invalid JSON: {path}") from exc
    built_with = str(payload.get("model") or "")
    if built_with != model:
        # Embeddings from different models are not comparable; falling back to
        # stale vectors would silently return garbage rankings.
        raise _model_mismatch_error(built_with or "<unknown>", model, path)
    records = payload.get("records")
    if not isinstance(records, list):
        raise RuntimeError(f"Vector sidecar has no records list: {path}")
    return records


def vector_search_sidecar(root: Path, query: str, limit: int, model: str, collection_name: str | None = None) -> list[SkillHit] | None:
    records = load_vector_sidecar(root, model)
    if records is None:
        return None
    query_embedding = embed_texts([query], model)[0]
    scored: list[SkillHit] = []
    for record in records:
        if not isinstance(record, dict):
            continue
        collection = str(record.get("collection") or "")
        if collection_name and collection != collection_name:
            continue
        embedding = record.get("embedding")
        if not isinstance(embedding, list):
            continue
        score = cosine_similarity(query_embedding, [float(value) for value in embedding])
        if score <= 0.0:
            continue
        scored.append(
            SkillHit(
                name=str(record.get("name") or ""),
                description=str(record.get("description") or ""),
                collection=collection,
                path=str(record.get("path") or ""),
                score=score,
            )
        )
    scored.sort(key=lambda item: (-item.score, item.collection, item.name))
    return scored[:limit]


def vector_search(root: Path, query: str, limit: int, model: str, collection_name: str | None = None) -> list[SkillHit]:
    sidecar_hits = vector_search_sidecar(root, query, limit, model, collection_name=collection_name)
    if sidecar_hits is not None:
        return sidecar_hits
    meta_path = vector_meta_path(root)
    if meta_path.is_file():
        try:
            meta = json.loads(read_text(meta_path))
        except json.JSONDecodeError:
            meta = {}
        built_with = str(meta.get("model") or "")
        if built_with and built_with != model:
            raise _model_mismatch_error(built_with, model, meta_path)
    try:
        collection = chroma_client(root).get_collection(CHROMA_COLLECTION)
    except Exception as exc:
        raise RuntimeError(
            "Vector index is not ready. Run `unlimited-skills vector-reindex` to build the fast local vector sidecar."
        ) from exc
    embedding = embed_texts([query], model)[0]
    result = collection.query(query_embeddings=[embedding], n_results=limit)
    metas = (result.get("metadatas") or [[]])[0]
    distances = (result.get("distances") or [[]])[0]
    hits = []
    for idx, meta in enumerate(metas):
        if not isinstance(meta, dict):
            continue
        if collection_name and str(meta.get("collection") or "") != collection_name:
            continue
        distance = float(distances[idx]) if idx < len(distances) else 1.0
        hits.append(
            SkillHit(
                name=str(meta.get("name") or ""),
                description=str(meta.get("description") or ""),
                collection=str(meta.get("collection") or ""),
                path=str(meta.get("path") or ""),
                score=max(0.0, 1.0 - distance),
            )
        )
    return hits


def hybrid_search(
    root: Path,
    query: str,
    limit: int,
    model: str,
    collection_name: str | None = None,
    fresh: bool = False,
    require_vector: bool = False,
) -> list[SkillHit]:
    merged = {hit.path: hit for hit in lexical_search(root, query, limit=max(limit * 3, 12), collection=collection_name, fresh=fresh)}
    try:
        for hit in vector_search(root, query, limit=max(limit * 3, 12), model=model, collection_name=collection_name):
            hit.score *= 20.0
            if hit.path in merged:
                merged[hit.path].score += hit.score
            else:
                merged[hit.path] = hit
    except VectorModelMismatch as exc:
        if require_vector:
            raise
        # Degrading to lexical-only must not be silent: results change quality.
        print(f"[unlimited-skills] vector search skipped: {exc}", file=sys.stderr)
    except Exception:
        if require_vector:
            raise
    hits = list(merged.values())
    hits.sort(key=lambda item: (-item.score, item.collection, item.name))
    return hits[:limit]


def emit_hits(hits: list[SkillHit], as_json: bool) -> int:
    if as_json:
        print(json.dumps([asdict(hit) for hit in hits], ensure_ascii=False, indent=2))
        return 0
    if not hits:
        print("No matching skills found.")
        return 0
    for hit in hits:
        score = f" score={hit.score:.2f}" if hit.score else ""
        print(f"{hit.name} [{hit.collection}]{score}")
        if hit.description:
            print(f"  {hit.description}")
        print(f"  {hit.path}")
    return 0


def list_skills(root: Path, collection: str | None = None, filter_text: str = "", fresh: bool = False) -> list[SkillHit]:
    filter_tokens = tokens(filter_text)
    filter_lower = filter_text.lower().strip()
    hits = []
    for hit, body in load_records(root, fresh=fresh):
        if collection and hit.collection != collection:
            continue
        if filter_tokens:
            haystack = f"{hit.name}\n{hit.description}\n{body[:12000]}".lower()
            if filter_lower not in haystack and not (filter_tokens & tokens(haystack)):
                continue
        hits.append(hit)
    hits.sort(key=lambda item: (item.collection, item.name))
    return hits


def collection_counts(hits: list[SkillHit]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for hit in hits:
        counts[hit.collection] = counts.get(hit.collection, 0) + 1
    return dict(sorted(counts.items()))


def _native_sync_disabled(args: argparse.Namespace) -> bool:
    env_value = os.environ.get("UNLIMITED_SKILLS_DISABLE_NATIVE_SYNC", "").strip().lower()
    return bool(getattr(args, "no_native_sync", False) or env_value in {"1", "true", "yes", "on"})


def maybe_sync_native(args: argparse.Namespace, root: Path) -> list[dict]:
    if _native_sync_disabled(args):
        return []
    agents = getattr(args, "native_agent", None) or None
    results = sync_native_sources(root, agents=agents, apply=True, refresh_collection=True)
    if any(item.imported_count for item in results):
        save_index(root)
    return [asdict(item) for item in results]


def resolve_skill_path(root: Path, name_or_path: str) -> Path | None:
    candidate = Path(name_or_path).expanduser()
    if candidate.is_file():
        return candidate
    if candidate.is_dir() and (candidate / "SKILL.md").is_file():
        return candidate / "SKILL.md"
    return find_by_name(root, name_or_path)


def build_parser() -> argparse.ArgumentParser:
    from .commands import accounts as accounts_cmds
    from .commands import catalog as catalog_cmds
    from .commands import community as community_cmds
    from .commands import feedback as feedback_cmds
    from .commands import learning as learning_cmds
    from .commands import library as library_cmds
    from .commands import money_saved as money_saved_cmds
    from .commands import router_health as router_health_cmds
    from .commands import mcp as mcp_cmds
    from .commands import policy as policy_cmds
    from .commands import private_packs as private_packs_cmds
    from .commands import roi as roi_cmds
    from .commands import service as service_cmds
    from .commands import skillops as skillops_cmds
    from .commands import team as team_cmds
    from .commands import updates as updates_cmds

    parser = argparse.ArgumentParser(description="Search, load, and learn from large local skill libraries.")
    parser.add_argument("--root", default=str(DEFAULT_ROOT), help="Skill library root.")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    def add_native_sync_options(command: argparse.ArgumentParser) -> None:
        command.add_argument(
            "--native-agent",
            action="append",
            choices=list(DEFAULT_AGENT_ORDER),
            help="Native agent skill root to sync before this command. Repeat for multiple agents. Defaults to all known agents.",
        )
        command.add_argument("--no-native-sync", action="store_true", help="Skip automatic sync from native agent skill roots.")

    reindex = sub.add_parser("reindex", help="Rebuild the lexical JSON index.")
    add_native_sync_options(reindex)
    reindex.add_argument("--json", action="store_true")
    reindex.set_defaults(func=library_cmds.cmd_reindex)

    vector_reindex = sub.add_parser("vector-reindex", help="Rebuild the Chroma vector index.")
    vector_reindex.add_argument("--model", default=DEFAULT_EMBED_MODEL)
    vector_reindex.add_argument("--batch-size", type=int, default=32)
    vector_reindex.add_argument("--fresh", action="store_true")
    vector_reindex.add_argument("--verbose", action="store_true")
    add_native_sync_options(vector_reindex)
    vector_reindex.set_defaults(func=library_cmds.cmd_vector_reindex)

    search = sub.add_parser("search", help="Search skills.")
    search.add_argument("query")
    search.add_argument("--mode", choices=["hybrid", "lexical", "vector"], default="hybrid")
    search.add_argument("--model", default=DEFAULT_EMBED_MODEL)
    search.add_argument("--collection")
    search.add_argument("--limit", type=int, default=10)
    search.add_argument("--json", action="store_true")
    search.add_argument("--fresh", action="store_true")
    search.add_argument("--require-vector", action="store_true")
    add_native_sync_options(search)
    search.set_defaults(func=library_cmds.cmd_search)

    suggest = sub.add_parser("suggest", help="Fast lexical skill probe: top-3 one-liners or silence.")
    suggest.add_argument("query")
    suggest.add_argument("--limit", type=int, default=3)
    suggest.add_argument("--floor", type=float, default=None, help="Suppress hits scoring below this floor.")
    suggest.add_argument("--collection")
    suggest.add_argument("--json", action="store_true")
    suggest.set_defaults(func=library_cmds.cmd_suggest)

    skills_parser = sub.add_parser("skills", help="Skill-quality operations (effectiveness regression check).")
    skills_sub = skills_parser.add_subparsers(dest="skills_command", required=True)
    skills_check = skills_sub.add_parser(
        "check-effectiveness",
        help="Run the skill-suggestion effectiveness regression check (wraps scripts/check-skill-effectiveness.py; the script remains the CI entry point).",
    )
    skills_check.add_argument("--json", action="store_true")
    skills_check.add_argument("--cadence-check", action="store_true", help="Only verify the release-gap cadence; do not replay scenarios.")
    skills_check.add_argument("--no-record", action="store_true", help="Do not write evals/last-effectiveness-run.json.")
    skills_check.set_defaults(func=library_cmds.cmd_skills_check_effectiveness)

    list_parser = sub.add_parser("list", help="List available skills in the library.")
    list_parser.add_argument("--collection", help="Only list one collection.")
    list_parser.add_argument("--filter", default="", help="Filter by name, description, or body text.")
    list_parser.add_argument("--limit", type=int, default=80, help="Maximum skills to print. Use 0 for all.")
    list_parser.add_argument("--names-only", action="store_true", help="Print only skill names.")
    list_parser.add_argument("--paths", action="store_true", help="Include SKILL.md paths in text output.")
    list_parser.add_argument("--json", action="store_true")
    list_parser.add_argument("--fresh", action="store_true")
    add_native_sync_options(list_parser)
    list_parser.set_defaults(func=library_cmds.cmd_list)

    view = sub.add_parser("view", help="Print full SKILL.md for a skill.")
    view.add_argument("name")
    add_native_sync_options(view)
    view.set_defaults(func=library_cmds.cmd_view)

    where = sub.add_parser("where", help="Print a SKILL.md path.")
    where.add_argument("name")
    add_native_sync_options(where)
    where.set_defaults(func=library_cmds.cmd_where)

    use = sub.add_parser("use", help="Record that the agent used a skill.")
    use.add_argument("name")
    use.add_argument("--query", default="")
    use.add_argument("--task", default="")
    add_native_sync_options(use)
    use.set_defaults(func=library_cmds.cmd_use)

    feedback = sub.add_parser("feedback", help="Prepare privacy-safe GitHub feedback or record local learning-loop feedback.")
    feedback.add_argument(
        "feedback_args",
        nargs="*",
        help="Action: prepare, doctor, record <skill>, or legacy <skill>.",
    )
    feedback.add_argument("--query", default="")
    feedback.add_argument("--verdict", choices=["accepted", "rejected", "neutral", "missed", "wrong"])
    feedback.add_argument("--notes", default="")
    feedback.add_argument("--include-usage-snapshot", action="store_true", help="Include local redacted usage and MCP savings counts.")
    feedback.add_argument("--format", choices=["json", "markdown"], default="json", help="Output format for feedback prepare.")
    feedback.add_argument("--out", default="", help="Write the prepared report to this file instead of stdout.")
    feedback.add_argument("--json", action="store_true", help="Machine-readable doctor/write status output where supported.")
    feedback.set_defaults(func=feedback_cmds.cmd_feedback)

    roi = sub.add_parser("roi", help="Generate local-only value receipts.")
    roi_sub = roi.add_subparsers(dest="roi_command", required=True)
    roi_receipt = roi_sub.add_parser("receipt", help="Print a privacy-safe local ROI receipt.")
    roi_receipt.add_argument("--format", choices=["markdown", "json"], default="markdown")
    roi_receipt.add_argument("--since", default="all", help="Local aggregation window: all, <hours>h, <days>d, or <weeks>w.")
    roi_receipt.add_argument("--out", default="", help="Write the receipt to this local file instead of stdout.")
    roi_receipt.add_argument("--json", action="store_true", help="Machine-readable write status when --out is used.")
    roi_receipt.set_defaults(func=roi_cmds.cmd_roi_receipt)

    money_saved = sub.add_parser("money-saved", help="Measure local Money Saved Meter value surfaces.")
    money_saved_sub = money_saved.add_subparsers(dest="money_saved_command", required=True)
    money_saved_meter = money_saved_sub.add_parser("meter", help="Print a local-only before/after install measurement report.")
    money_saved_meter.add_argument("--json", action="store_true", help="Emit the safe aggregate JSON report.")
    money_saved_meter.add_argument("--out", default="", help="Write the report to this local file instead of stdout.")
    money_saved_meter.add_argument("--json-status", action="store_true", help="Machine-readable write status when --out is used.")
    money_saved_meter.add_argument("--mode", choices=["before", "after", "current"], default="current", help="Label this local measurement run.")
    money_saved_meter.add_argument("--mcp-savings-json", default="", help="Read an existing `mcp savings --json` file instead of the latest local event snapshot.")
    money_saved_meter.add_argument("--audit-log", default="", help="Read gateway call counts from this audit log instead of the default local audit log.")
    money_saved_meter.add_argument("--compare", default="", help="Compare this report with a previous Money Saved Meter JSON report.")
    money_saved_meter.add_argument("--target-calls", type=int, default=100, help="Local reporting cadence target. This is not billing math.")
    money_saved_meter.add_argument("--fixture-100-call", action="store_true", help="Emit the deterministic 100-call value report fixture.")
    money_saved_meter.set_defaults(func=money_saved_cmds.cmd_money_saved_meter)

    money_saved_registered = money_saved_sub.add_parser(
        "registered-export",
        help="Registered tier: write a schema-versioned local savings export (produced locally, stays local; no upload).",
    )
    money_saved_registered.add_argument("--out", default="", help="Write the export to this local file instead of stdout.")
    money_saved_registered.add_argument("--json-status", action="store_true", help="Machine-readable write status when --out is used.")
    money_saved_registered.add_argument("--mode", choices=["before", "after", "current"], default="current", help="Label this local measurement run.")
    money_saved_registered.add_argument("--mcp-savings-json", default="", help="Read an existing `mcp savings --json` file instead of the latest local event snapshot.")
    money_saved_registered.add_argument("--audit-log", default="", help="Read gateway call counts from this audit log instead of the default local audit log.")
    money_saved_registered.add_argument("--target-calls", type=int, default=100, help="Local reporting cadence target. This is not billing math.")
    money_saved_registered.set_defaults(func=money_saved_cmds.cmd_money_saved_registered_export)

    router_health = sub.add_parser("router-health", help="Local router-health readiness surfaces (per tier).")
    router_health_sub = router_health.add_subparsers(dest="router_health_command", required=True)
    router_health_export = router_health_sub.add_parser(
        "export",
        help="Registered tier: write a schema-versioned local router-health export (produced locally, stays local; no upload).",
    )
    router_health_export.add_argument("--json", action="store_true", help="Emit the export JSON (output is JSON regardless).")
    router_health_export.add_argument("--out", default="", help="Write the export to this local file instead of stdout.")
    router_health_export.add_argument("--json-status", action="store_true", help="Machine-readable write status when --out is used.")
    router_health_export.set_defaults(func=router_health_cmds.cmd_router_health_export)

    router_health_team = router_health_sub.add_parser(
        "team-rollup",
        help="Team tier: locally aggregate multiple Registered router-health exports (no network fetch).",
    )
    router_health_team.add_argument("--input", action="append", default=[], help="A Registered router-health export file. Repeat for each member.")
    router_health_team.add_argument("--alias", action="append", default=[], help="Optional local member alias, positionally matched to --input (defaults to the file stem).")
    router_health_team.add_argument("--json", action="store_true", help="Emit the rollup JSON (output is JSON regardless).")
    router_health_team.add_argument("--out", default="", help="Write the rollup to this local file instead of stdout.")
    router_health_team.add_argument("--json-status", action="store_true", help="Machine-readable write status when --out is used.")
    router_health_team.set_defaults(func=router_health_cmds.cmd_router_health_team_rollup)

    router_health_admin = router_health_sub.add_parser(
        "admin-export",
        help="Business tier: local admin CSV + JSON export over a Team rollup (no hosted dashboard).",
    )
    router_health_admin.add_argument("--input", default="", help="A Team router-health rollup file.")
    router_health_admin.add_argument("--labels", default="", help="Optional local JSON map: alias -> {team, workspace, agent_class}.")
    router_health_admin.add_argument("--csv", default="", help="Write the CSV export to this local file.")
    router_health_admin.add_argument("--json", default="", help="Write the JSON export to this local file.")
    router_health_admin.set_defaults(func=router_health_cmds.cmd_router_health_admin_export)

    router_health_evidence = router_health_sub.add_parser(
        "evidence-pack",
        help="Enterprise tier: write a local, reproducible router-health evidence pack (no egress).",
    )
    router_health_evidence.add_argument("--input", default="", help="A Business admin export file.")
    router_health_evidence.add_argument("--out", default="", help="Output directory for the evidence pack.")
    router_health_evidence.set_defaults(func=router_health_cmds.cmd_router_health_evidence_pack)

    summary = sub.add_parser("learning-summary", help="Summarize learning-loop feedback.")
    summary.add_argument(
        "--events",
        action="store_true",
        help="Also report local effectiveness metrics from events.jsonl (tier distribution, injection rate, suggest->view->use funnel). Local-only aggregates; no query text or paths.",
    )
    summary.add_argument("--json", action="store_true", help="Accepted for explicit machine-readable output; learning-summary output is JSON.")
    summary.set_defaults(func=library_cmds.cmd_learning_summary)

    learning = sub.add_parser("learning", help="Inspect local Learning Loop state.")
    learning_sub = learning.add_subparsers(dest="learning_command", required=True)
    learning_doctor = learning_sub.add_parser("doctor", help="Diagnose local Learning Loop state without hosted calls.")
    learning_doctor.set_defaults(func=learning_cmds.cmd_learning_doctor)

    improvement_candidates = sub.add_parser(
        "improvement-candidates",
        help="List local privacy-safe Learning Loop improvement candidates.",
    )
    improvement_candidates.set_defaults(func=learning_cmds.cmd_improvement_candidates)

    apply_candidate = sub.add_parser(
        "apply-candidate",
        help="Preview a local Learning Loop improvement candidate. Currently dry-run only.",
    )
    apply_candidate.add_argument("--dry-run", action="store_true", required=True, help="Required: preview only and do not modify skill files.")
    apply_candidate.add_argument("candidate_id")
    apply_candidate.set_defaults(func=learning_cmds.cmd_apply_candidate)

    draft = sub.add_parser("draft-skill", help="Draft a new SKILL.md from task evidence.")
    draft.add_argument("name")
    draft.add_argument("--description", required=True)
    draft.add_argument("--evidence", default="")
    draft.add_argument("--write", action="store_true")
    draft.set_defaults(func=library_cmds.cmd_draft_skill)

    adapt = sub.add_parser("adapt", help="Adapt existing SKILL.md files for Unlimited Skills retrieval and learning.")
    adapt.add_argument("--collection", help="Only adapt one collection under the library root.")
    adapt.add_argument("--source-pack", default="", help="Set or override the source_pack metadata.")
    adapt.add_argument("--source-repo", default="", help="Set or override the source_repo metadata.")
    adapt.add_argument("--force", action="store_true", help="Rewrite skills even when already adapted.")
    adapt.add_argument("--dry-run", action="store_true", help="Print what would change without writing files.")
    adapt.add_argument("--limit", type=int, default=20, help="Maximum changed items to include in JSON output.")
    adapt.set_defaults(func=library_cmds.cmd_adapt)

    packs = sub.add_parser("packs", help="List known upstream skill packs.")
    packs.set_defaults(func=library_cmds.cmd_packs)

    install_pack_parser = sub.add_parser("install-pack", help="Clone, import, and adapt a known upstream skill pack.")
    install_pack_parser.add_argument("pack", choices=sorted(SKILL_PACKS))
    install_pack_parser.add_argument("--ref", default="", help="Optional git ref to import.")
    install_pack_parser.add_argument("--keep-clone", default="", help="Optional path where the upstream clone should be kept.")
    install_pack_parser.add_argument("--limit", type=int, default=20, help="Maximum imported items to include in JSON output.")
    install_pack_parser.set_defaults(func=library_cmds.cmd_install_pack)

    sync_native = sub.add_parser("sync-native", help="Mirror native agent skill roots into the Unlimited Skills library.")
    sync_native.add_argument("--agent", action="append", choices=list(DEFAULT_AGENT_ORDER), help="Agent to sync. Repeat for multiple agents. Defaults to all.")
    sync_native.add_argument("--dry-run", action="store_true", help="Report what would be imported without writing files.")
    sync_native.add_argument("--no-refresh", action="store_true", help="Keep existing mirrored skill files untouched; native sync is overlay-only by default.")
    sync_native.add_argument("--skip-reindex", action="store_true", help="Do not rebuild the lexical index after syncing.")
    sync_native.add_argument("--json", action="store_true")
    sync_native.set_defaults(func=library_cmds.cmd_sync_native)

    adapt_one = sub.add_parser("adapt-one", help="Print an agent adaptation task for one skill.")
    adapt_one.add_argument("name_or_path", help="Skill name, SKILL.md path, or skill directory path.")
    adapt_one.add_argument("--source-pack", default="", help="Source pack metadata override.")
    adapt_one.add_argument("--source-repo", default="", help="Source repository metadata override.")
    adapt_one.set_defaults(func=library_cmds.cmd_adapt_one)

    adapt_next = sub.add_parser("adapt-next", help="Print an agent adaptation task for the next unprocessed skill.")
    adapt_next.add_argument("--collection", help="Only process one collection.")
    adapt_next.add_argument("--source-pack", default="", help="Source pack metadata override.")
    adapt_next.add_argument("--source-repo", default="", help="Source repository metadata override.")
    adapt_next.set_defaults(func=library_cmds.cmd_adapt_next)

    apply_adaptation = sub.add_parser("apply-adaptation", help="Apply one agent-produced action-memory JSON adaptation.")
    apply_adaptation.add_argument("input", help="JSON file produced by the current agent for one source skill.")
    apply_adaptation.add_argument("--path", default="", help="Override source skill path/name.")
    apply_adaptation.add_argument("--source-pack", default="", help="Source pack metadata override.")
    apply_adaptation.add_argument("--source-repo", default="", help="Source repository metadata override.")
    apply_adaptation.add_argument("--dry-run", action="store_true", help="Validate and print result without writing.")
    apply_adaptation.set_defaults(func=library_cmds.cmd_apply_adaptation)

    import_dir = sub.add_parser("import-dir", help="Import skills from a local directory into the library with sha256 dedup and conflict reporting.")
    import_dir.add_argument("path", help="Directory to scan recursively for SKILL.md files.")
    import_dir.add_argument("--collection", required=True, help="Library collection name (stored under local/<collection>).")
    import_dir.add_argument("--dry-run", action="store_true", help="Report what would be imported without writing files.")
    import_dir.add_argument("--skip-reindex", action="store_true", help="Do not rebuild the lexical index after importing.")
    import_dir.add_argument("--json", action="store_true")
    import_dir.set_defaults(func=library_cmds.cmd_import_dir)

    import_github = sub.add_parser("import-github", help="Shallow-clone a GitHub repo and import its skills into the library.")
    import_github.add_argument("repo", help="Repository as 'org/name' or a full git URL.")
    import_github.add_argument("--collection", default="", help="Library collection name. Defaults to the repo name.")
    import_github.add_argument("--ref", default="", help="Git ref (branch, tag, or commit) to check out.")
    import_github.add_argument("--subdir", default="", help="Only import skills under this subdirectory of the repo.")
    import_github.add_argument("--dry-run", action="store_true", help="Report what would be imported without writing files.")
    import_github.add_argument("--skip-reindex", action="store_true", help="Do not rebuild the lexical index after importing.")
    import_github.add_argument("--json", action="store_true")
    import_github.set_defaults(func=library_cmds.cmd_import_github)

    serve = sub.add_parser("serve", help="Run the experimental warm search daemon.")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8765)
    serve.add_argument("--model", default=DEFAULT_EMBED_MODEL)
    serve.add_argument("--log-level", default="info")
    serve.set_defaults(func=library_cmds.cmd_serve)

    hub = sub.add_parser("hub", help="Registered Local Skill Hub contract and alpha commands.")
    hub_sub = hub.add_subparsers(dest="hub_command", required=True)
    hub_init = hub_sub.add_parser("init", help="Initialize local Local Skill Hub contract state.")
    hub_init.add_argument("--allowlist", default="", help="Validate and cache a local hub allowlist fixture.")
    hub_init.add_argument("--json", action="store_true")
    hub_init.set_defaults(func=cmd_hub_init)
    hub_status = hub_sub.add_parser("status", help="Show Local Skill Hub status without hosted calls.")
    hub_status.add_argument("--json", action="store_true")
    hub_status.set_defaults(func=cmd_hub_status)
    hub_serve = hub_sub.add_parser("serve", help="Run the registered Local Skill Hub alpha service.")
    hub_serve.add_argument("--host", default="127.0.0.1")
    hub_serve.add_argument("--port", type=int, default=HUB_DEFAULT_PORT)
    hub_serve.add_argument("--log-level", default="info")
    hub_serve.add_argument("--allowlist", default="", help="Path to allowlist.v1.json. Defaults to cached ~/.unlimited-skills/hub/allowlist.v1.json.")
    hub_serve.add_argument("--allow-lan", action="store_true", help="Allow binding Local Skill Hub to a non-localhost address when an active hub token exists.")
    hub_serve.set_defaults(func=cmd_hub_serve)
    hub_clients = hub_sub.add_parser("clients", help="List Local Skill Hub clients.")
    hub_clients.set_defaults(func=cmd_hub_clients)
    hub_sync = hub_sub.add_parser("sync", help="Refresh registered Local Skill Hub allowlist/catalog metadata.")
    hub_sync.add_argument("--dry-run", action="store_true")
    hub_sync.add_argument("--json", action="store_true")
    hub_sync.add_argument("--timeout", type=float, default=30.0)
    hub_sync.set_defaults(func=cmd_hub_sync)
    hub_heartbeat = hub_sub.add_parser("heartbeat", help="Send or preview a privacy-safe Local Skill Hub heartbeat.")
    hub_heartbeat.add_argument("--dry-run", action="store_true", help="Print the exact heartbeat payload without contacting the hosted service.")
    hub_heartbeat.add_argument("--json", action="store_true")
    hub_heartbeat.add_argument("--timeout", type=float, default=30.0)
    hub_heartbeat.set_defaults(func=cmd_hub_heartbeat)
    hub_license = hub_sub.add_parser("license", help="Inspect or refresh Local Skill Hub plan entitlements.")
    hub_license_sub = hub_license.add_subparsers(dest="hub_license_command", required=True)
    hub_license_status = hub_license_sub.add_parser("status", help="Show cached Local Skill Hub entitlement status.")
    hub_license_status.add_argument("--json", action="store_true")
    hub_license_status.set_defaults(func=cmd_hub_license_status)
    hub_license_refresh = hub_license_sub.add_parser("refresh", help="Refresh Local Skill Hub plan entitlements from the registration service.")
    hub_license_refresh.add_argument("--json", action="store_true")
    hub_license_refresh.add_argument("--timeout", type=float, default=30.0)
    hub_license_refresh.set_defaults(func=cmd_hub_license_refresh)
    hub_token = hub_sub.add_parser("token", help="Manage Local Skill Hub client tokens.")
    hub_token_sub = hub_token.add_subparsers(dest="hub_token_command", required=True)
    hub_token_create = hub_token_sub.add_parser("create", help="Create a Local Skill Hub client token.")
    hub_token_create.add_argument("--label", default="default")
    hub_token_create.add_argument("--json", action="store_true")
    hub_token_create.set_defaults(func=cmd_hub_token_create)
    hub_token_list = hub_token_sub.add_parser("list", help="List Local Skill Hub client tokens without showing raw token values.")
    hub_token_list.add_argument("--json", action="store_true")
    hub_token_list.set_defaults(func=cmd_hub_token_list)
    hub_token_revoke = hub_token_sub.add_parser("revoke", help="Revoke a Local Skill Hub client token by token id.")
    hub_token_revoke.add_argument("token_id")
    hub_token_revoke.add_argument("--json", action="store_true")
    hub_token_revoke.set_defaults(func=cmd_hub_token_revoke)
    hub_doctor = hub_sub.add_parser("doctor", help="Inspect Local Skill Hub contract readiness.")
    hub_doctor.set_defaults(func=cmd_hub_doctor)

    trust = sub.add_parser("trust", help="Inspect and verify signed hosted manifest trust configuration.")
    trust_sub = trust.add_subparsers(dest="trust_command", required=True)
    trust_status = trust_sub.add_parser("status", help="Show signed manifest trust status without printing key material.")
    trust_status.add_argument("--json", action="store_true")
    trust_status.set_defaults(func=cmd_trust_status)
    trust_keys = trust_sub.add_parser("keys", help="List trusted manifest public key ids.")
    trust_keys.add_argument("--json", action="store_true")
    trust_keys.set_defaults(func=cmd_trust_keys)
    trust_verify = trust_sub.add_parser("verify", help="Verify a signed hosted manifest JSON file.")
    trust_verify.add_argument("manifest")
    trust_verify.add_argument("--scope", default="", help="Expected manifest scope, such as hub-allowlist or catalog-updates.")
    trust_verify.add_argument("--registry-url", default="", help="Expected registry URL for key origin pinning.")
    trust_verify.add_argument("--json", action="store_true")
    trust_verify.set_defaults(func=cmd_trust_verify)
    trust_import = trust_sub.add_parser("import", help="Import a public key manifest into the local trust store.")
    trust_import.add_argument("manifest")
    trust_import.add_argument("--replace", action="store_true", help="Replace the local trust store instead of merging keys.")
    trust_import.add_argument("--json", action="store_true")
    trust_import.set_defaults(func=cmd_trust_import)
    trust_revoke = trust_sub.add_parser("revoke", help="Mark a manifest signing key id as revoked in the local trust store.")
    trust_revoke.add_argument("key_id")
    trust_revoke.add_argument("--reason", default="")
    trust_revoke.add_argument("--json", action="store_true")
    trust_revoke.set_defaults(func=cmd_trust_revoke)

    remote = sub.add_parser("remote", help="Configure or query a registered Local Skill Hub.")
    remote_sub = remote.add_subparsers(dest="remote_command", required=True)
    remote_configure = remote_sub.add_parser("configure", help="Configure a remote Local Skill Hub endpoint.")
    remote_configure.add_argument("--url", required=True, help="Local/LAN hub URL, for example http://127.0.0.1:8766.")
    remote_configure.add_argument("--token", default="", help="Client token. Stored in remote.json with private permissions; prefer --token-env.")
    remote_configure.add_argument("--token-env", default="", help="Environment variable containing the hub token, for example ULS_HUB_TOKEN.")
    remote_configure.add_argument("--fallback", dest="fallback_mode", choices=["local_allowed", "hub_required"], default="local_allowed")
    remote_configure.add_argument("--fallback-mode", choices=["local_allowed", "hub_required"], default="local_allowed")
    remote_configure.add_argument("--timeout", type=float, default=10)
    remote_configure.set_defaults(func=cmd_remote_configure)
    remote_status = remote_sub.add_parser("status", help="Show remote hub configuration.")
    remote_status.add_argument("--json", action="store_true")
    remote_status.set_defaults(func=cmd_remote_status)
    remote_capabilities = remote_sub.add_parser("capabilities", help="Print local client capabilities sent to remote resolve.")
    remote_capabilities.add_argument("--agent", default="unknown")
    remote_capabilities.add_argument("--capabilities-json", default="")
    remote_capabilities.add_argument("--json", action="store_true")
    remote_capabilities.set_defaults(func=cmd_remote_capabilities)
    remote_search = remote_sub.add_parser("search", help="Search configured remote hub.")
    remote_search.add_argument("query")
    remote_search.add_argument("--mode", choices=["hybrid", "lexical", "vector"], default="hybrid")
    remote_search.add_argument("--collection", default="")
    remote_search.add_argument("--limit", type=int, default=8)
    remote_search.add_argument("--json", action="store_true")
    remote_search.set_defaults(func=cmd_remote_search)
    remote_resolve = remote_sub.add_parser("resolve", help="Resolve task-relevant skill bodies from configured remote hub.")
    remote_resolve.add_argument("query")
    remote_resolve.add_argument("--collection", default="")
    remote_resolve.add_argument("--max-skills", type=int, default=2)
    remote_resolve.add_argument("--max-chars", type=int, default=12000)
    remote_resolve.add_argument("--agent", choices=["codex", "claude-code", "hermes", "openclaw", "vellum-ai", "unknown"], default="unknown")
    remote_resolve.add_argument("--capabilities-json", default="")
    remote_resolve.add_argument("--json", action="store_true")
    remote_resolve.set_defaults(func=cmd_remote_resolve)
    remote_view = remote_sub.add_parser("view", help="View a skill from configured remote hub.")
    remote_view.add_argument("skill_name")
    remote_view.add_argument("--json", action="store_true")
    remote_view.set_defaults(func=cmd_remote_view)
    remote_install_plan = remote_sub.add_parser("install-plan", help="Show a dry-run local install plan for a remote hub skill.")
    remote_install_plan.add_argument("skill_name")
    remote_install_plan.add_argument("--dry-run", action="store_true", default=True)
    remote_install_plan.add_argument("--json", action="store_true")
    remote_install_plan.set_defaults(func=cmd_remote_install_plan)

    doctor = sub.add_parser("doctor", help="Inspect local Unlimited Skills setup without hosted calls or registration.")
    doctor.add_argument("--json", action="store_true", help="Print machine-readable diagnostics.")
    doctor.add_argument("--agent", choices=["codex", "claude-code", "hermes", "openclaw", "all"], default="all", help="Limit agent diagnostics.")
    doctor.set_defaults(func=library_cmds.cmd_doctor)

    setup = sub.add_parser("setup", help="Guided first-run onboarding wizard.")
    setup_modes = setup.add_mutually_exclusive_group()
    setup_modes.add_argument("--local-only", action="store_true", help="Verify local-only Community Core setup without registration.")
    setup_modes.add_argument("--registered", action="store_true", help="Verify registered hosted-service setup boundaries.")
    setup_modes.add_argument("--hub", action="store_true", help="Verify registered Local Skill Hub setup readiness.")
    setup_modes.add_argument("--enterprise", action="store_true", help="Verify Enterprise Skill Lock policy setup status.")
    setup_modes.add_argument("--private-packs", action="store_true", help="Verify hosted private team pack readiness.")
    setup.add_argument("--dry-run", action="store_true", help="Print the setup plan without writing missing local directories.")
    setup.add_argument("--json", action="store_true")
    setup.add_argument("--agent", choices=["codex", "claude-code", "hermes", "openclaw", "all"], default="all", help="Limit embedded doctor diagnostics.")
    setup_sub = setup.add_subparsers(dest="setup_command", required=False)
    setup_doctor = setup_sub.add_parser("doctor", help="Run setup diagnostics in overview mode.")
    setup_doctor.add_argument("--dry-run", action="store_true")
    setup_doctor.add_argument("--json", action="store_true")
    setup_doctor.add_argument("--agent", choices=["codex", "claude-code", "hermes", "openclaw", "all"], default="all", help="Limit embedded doctor diagnostics.")
    setup_doctor.set_defaults(func=library_cmds.cmd_setup, local_only=False, registered=False, hub=False, enterprise=False, private_packs=False)
    setup.set_defaults(func=library_cmds.cmd_setup)

    quickstart = sub.add_parser(
        "quickstart",
        help="One-command golden path: import bundled packs when the library is empty, run a first search, and show your measured MCP context savings. Idempotent and local-only.",
    )
    quickstart.add_argument("query", nargs="?", default="", help="Optional search query for the first-search step. Defaults to a demo query.")
    quickstart.add_argument("--json", action="store_true", help="Print the machine-readable quickstart report.")
    quickstart.add_argument("--timeout", type=float, default=None, help="Per-MCP-server measurement timeout in seconds for the savings step (default 12).")
    quickstart.add_argument("--claude-config", default="", help="Override the Claude Code config path read by the savings step (default ~/.claude.json).")
    quickstart.add_argument("--skip-mcp-check", action="store_true", help="Skip the MCP savings step.")
    quickstart.set_defaults(func=library_cmds.cmd_quickstart)

    support = sub.add_parser("support", help="Create redacted support diagnostics.")
    support_sub = support.add_subparsers(dest="support_command", required=True)
    support_bundle = support_sub.add_parser("bundle", help="Create a redacted support diagnostic bundle.")
    support_bundle.add_argument("--out", default="", help="Output zip path. Defaults to a timestamped bundle in the current directory.")
    support_bundle.add_argument("--json", action="store_true", help="Print the redacted manifest as JSON.")
    support_bundle.add_argument("--dry-run", action="store_true", help="Build diagnostics without writing a zip file.")
    support_bundle.add_argument("--include-paths", action="store_true", help="Include local paths in diagnostics. Off by default.")
    support_bundle.add_argument("--include-private-pack-refs", action="store_true", help="Include hashed private pack references. Skill names and bodies are still excluded.")
    support_bundle.set_defaults(func=library_cmds.cmd_support_bundle)

    register = sub.add_parser("register", help="Self-register this installation for hosted catalog and adapted collection updates.")
    register.add_argument("--server-url", default=DEFAULT_SERVICE_URL, help="Registration and update service URL.")
    register.add_argument("--agent", default="", help="Optional agent surface label, for example codex, claude-code, hermes, or openclaw.")
    register.add_argument("--telemetry", action="store_true", help="Opt in to minimal operational telemetry.")
    register.add_argument("--timeout", type=float, default=30.0)
    register.set_defaults(func=service_cmds.cmd_register)

    license_parser = sub.add_parser("license", help="Inspect registration and hosted service access.")
    license_sub = license_parser.add_subparsers(dest="license_command", required=True)
    license_status = license_sub.add_parser("status", help="Show current license and registration status.")
    license_status.add_argument("--json", action="store_true")
    license_status.set_defaults(func=service_cmds.cmd_license_status)

    telemetry = sub.add_parser("telemetry", help="Inspect or change minimal telemetry preference.")
    telemetry_sub = telemetry.add_subparsers(dest="telemetry_command", required=True)
    for name in ("status", "on", "off"):
        telemetry_item = telemetry_sub.add_parser(name)
        telemetry_item.set_defaults(func=service_cmds.cmd_telemetry)

    service = sub.add_parser("service", help="Configure and diagnose the registered Unlimited Skills service.")
    service_sub = service.add_subparsers(dest="service_command", required=True)
    service_configure = service_sub.add_parser("configure", help="Store the hosted service URL for onboarding diagnostics.")
    service_configure.add_argument("--url", required=True, help="Service base URL, for example https://unlimited.ai4.sale.")
    service_configure.add_argument("--allow-insecure-localhost", action="store_true", help="Allow http://localhost URLs for local fixture diagnostics only.")
    service_configure.set_defaults(func=service_cmds.cmd_service_configure)
    service_status_parser = service_sub.add_parser("status", help="Show local service configuration and registration state.")
    service_status_parser.add_argument("--refresh", action="store_true", help="Contact health/public-key endpoints; local-only without this flag.")
    service_status_parser.add_argument("--timeout", type=float, default=10.0)
    service_status_parser.set_defaults(func=service_cmds.cmd_service_status)
    service_doctor_parser = service_sub.add_parser("doctor", help="Run privacy-safe service health and trust diagnostics.")
    service_doctor_parser.add_argument("--url", default="", help="Temporarily diagnose this service URL without changing config.")
    service_doctor_parser.add_argument("--timeout", type=float, default=10.0)
    service_doctor_parser.set_defaults(func=service_cmds.cmd_service_doctor)
    service_verify = service_sub.add_parser("verify-trust", help="Fetch public keys and compare them with local trust records.")
    service_verify.add_argument("--url", default="", help="Temporarily verify this service URL without changing config.")
    service_verify.add_argument("--timeout", type=float, default=10.0)
    service_verify.set_defaults(func=service_cmds.cmd_service_verify_trust)
    service_registration = service_sub.add_parser("test-registration", help="Build a redacted registration request without sending it.")
    service_registration.add_argument("--dry-run", action="store_true", required=True, help="Required: print the redacted payload and send nothing.")
    service_registration.add_argument("--url", default="", help="Temporarily use this service URL without changing config.")
    service_registration.add_argument("--agent", default="", help="Optional agent surface label.")
    service_registration.add_argument("--telemetry", action="store_true", help="Preview telemetry opt-in flag in the dry-run payload.")
    service_registration.set_defaults(func=service_cmds.cmd_service_test_registration)
    service_proof = service_sub.add_parser("test-proof", help="Generate a local redacted device-proof header using registration state.")
    service_proof.add_argument("--url", default="", help="Temporarily use this service URL without changing config.")
    service_proof.set_defaults(func=service_cmds.cmd_service_test_proof)

    policy = sub.add_parser("policy", help="Inspect and manage Enterprise Skill Lock local policy.")
    policy_sub = policy.add_subparsers(dest="policy_command", required=True)
    policy_status = policy_sub.add_parser("status", help="Show installed Enterprise Skill Lock policy status.")
    policy_status.set_defaults(func=policy_cmds.cmd_policy_status)
    policy_verify = policy_sub.add_parser("verify", help="Verify a signed or hash-pinned Enterprise Skill Lock policy file.")
    policy_verify.add_argument("policy_json")
    policy_verify.set_defaults(func=policy_cmds.cmd_policy_verify)
    policy_install = policy_sub.add_parser("install", help="Install a signed or hash-pinned Enterprise Skill Lock policy file.")
    policy_install.add_argument("policy_json")
    policy_install.set_defaults(func=policy_cmds.cmd_policy_install)
    policy_remove = policy_sub.add_parser("remove", help="Remove the installed Enterprise Skill Lock policy.")
    policy_remove.add_argument("--yes", action="store_true", help="Confirm policy removal.")
    policy_remove.set_defaults(func=policy_cmds.cmd_policy_remove)
    policy_explain = policy_sub.add_parser("explain", help="Explain effective Enterprise Skill Lock behavior.")
    policy_explain.set_defaults(func=policy_cmds.cmd_policy_explain)
    policy_sync = policy_sub.add_parser("sync", help="Fetch and apply managed Enterprise Skill Lock policy from the registered registry.")
    policy_sync.add_argument("--dry-run", action="store_true", help="Verify the server assignment without writing local policy state.")
    policy_sync.add_argument("--json", action="store_true", help="Emit JSON output.")
    policy_sync.add_argument("--timeout", type=float, default=30.0)
    policy_sync.set_defaults(func=policy_cmds.cmd_policy_sync)
    policy_managed_status = policy_sub.add_parser("managed-status", help="Show last managed Enterprise Skill Lock sync state.")
    policy_managed_status.add_argument("--json", action="store_true", help="Emit JSON output.")
    policy_managed_status.set_defaults(func=policy_cmds.cmd_policy_managed_status)

    updates = sub.add_parser("updates", help="Check or apply hosted adapted collection updates.")
    updates_sub = updates.add_subparsers(dest="updates_command", required=True)
    updates_check = updates_sub.add_parser("check", help="Check registered hosted collection updates.")
    updates_check.add_argument("--collection", default="", help="Only check one collection.")
    updates_check.add_argument("--channel", default="", help="Override the pinned release channel for this check.")
    updates_check.add_argument("--json", action="store_true")
    updates_check.add_argument("--timeout", type=float, default=30.0)
    updates_check.set_defaults(func=updates_cmds.cmd_updates_check)
    updates_apply = updates_sub.add_parser("apply", help="Download, verify, and install registered hosted collection updates.")
    updates_apply.add_argument("--collection", default="", help="Only apply one collection.")
    updates_apply.add_argument("--channel", default="", help="Override the pinned release channel for this apply.")
    updates_apply.add_argument("--dry-run", action="store_true", help="Show available updates without downloading archives.")
    updates_apply.add_argument("--yes", action="store_true", help="Reserved for non-interactive compatibility.")
    updates_apply.add_argument("--skip-reindex", action="store_true", help="Do not rebuild the lexical index after applying updates.")
    updates_apply.add_argument("--timeout", type=float, default=30.0)
    updates_apply.set_defaults(func=updates_cmds.cmd_updates_apply)
    updates_rollback = updates_sub.add_parser("rollback", help="Rollback a collection to the latest saved pre-update snapshot.")
    updates_rollback.add_argument("collection", help="Collection name to rollback.")
    updates_rollback.add_argument("--dry-run", action="store_true")
    updates_rollback.add_argument("--yes", action="store_true", help="Confirm rollback in non-interactive mode.")
    updates_rollback.add_argument("--skip-reindex", action="store_true")
    updates_rollback.set_defaults(func=updates_cmds.cmd_updates_rollback)

    skillops = sub.add_parser("skillops", help="Run local SkillOps diagnostics and previews.")
    skillops_sub = skillops.add_subparsers(dest="skillops_command", required=True)
    usage_snapshot = skillops_sub.add_parser("usage-snapshot", help="Build a local-only privacy-preserving usage snapshot.")
    usage_snapshot.add_argument("usage_snapshot_command", nargs="?", choices=["explain"], default=None)
    usage_snapshot.add_argument("--json", action="store_true")
    usage_snapshot.add_argument("--out", default="", help="Write the snapshot JSON to a local file. Ignored with --dry-run.")
    usage_snapshot.add_argument("--dry-run", action="store_true", help="Build and print the snapshot without writing --out.")
    usage_snapshot.set_defaults(func=skillops_cmds.cmd_skillops_usage_snapshot)

    mcp = sub.add_parser("mcp", help="Run local stdio MCP servers: the skills server and the Unlimited Tools gateway.")
    mcp_sub = mcp.add_subparsers(dest="mcp_command", required=True)
    mcp_serve = mcp_sub.add_parser(
        "serve",
        help="Run the skills MCP server over stdio: skills_search, skills_view, skills_use on the --root library.",
    )
    mcp_serve.set_defaults(func=mcp_cmds.cmd_mcp_serve)
    mcp_gateway = mcp_sub.add_parser(
        "gateway",
        help="Run the Unlimited Tools MCP gateway over stdio: tools_search, tools_schema, tools_call over configured upstream MCP servers.",
    )
    mcp_gateway.add_argument("--config", required=True, help="Path to a gateway JSON config listing upstream stdio MCP servers.")
    mcp_gateway.add_argument("--audit-log", default="", help="Override the redacted JSONL audit log path. Defaults to <root>/.learning/mcp-audit.jsonl.")
    mcp_gateway.add_argument("--profiles", default="", help="Path to a permissioned tool-profile JSON file (schemas/mcp-tool-profile.schema.json). Absent = open no-profiles mode; configured = default-deny enforcement that fails closed on errors.")
    mcp_gateway.add_argument("--profile", default="", help="Profile name to enforce from --profiles or --profile-bundle. Precedence: this flag > UNLIMITED_SKILLS_MCP_PROFILE > the source's default_profile.")
    mcp_gateway.add_argument("--profile-bundle", default="", help="Path to a SIGNED profile bundle JSON file (schemas/mcp-profile-bundle.schema.json), verified at startup against --trusted-keys; any verification failure is fail-closed refuse-all (-32014..-32019). May be combined with --profiles: the local file can only narrow the bundle, never widen it.")
    mcp_gateway.add_argument("--trusted-keys", default="", help="Path to the local trusted-keys JSON file (key_id -> base64 Ed25519 public key, optional not_after) used to verify --profile-bundle. No PKI, no network fetch.")
    mcp_gateway.add_argument("--audience-id", action="append", default=None, metavar="ID", help="This consumer's audience identifier ('team:NAME', 'org:NAME', or 'host:NAME') matched against the bundle's audience. Repeatable; beats the comma-separated UNLIMITED_SKILLS_MCP_AUDIENCE env var.")
    mcp_gateway.add_argument("--require-signed-profiles", action="store_true", help="Signed-required policy: refuse unsigned profile sources fail-closed with -32015 bundle_signature_invalid (a raw --profiles file alone, or no bundle at all). Default off pre-v0.6.")
    mcp_gateway.set_defaults(func=mcp_cmds.cmd_mcp_gateway)
    mcp_savings = mcp_sub.add_parser(
        "savings",
        help="Measure your real standing MCP context cost: reads your Claude Code MCP config, runs each stdio server's tools/list locally, and compares the summed schema bytes/tokens against the gateway's 3 meta-tools. Local-only; the output carries only server names, tool counts, sizes, and statuses -- never schema contents, commands, or env.",
    )
    mcp_savings.add_argument("--json", action="store_true", help="Print the machine-readable savings report.")
    mcp_savings.add_argument("--timeout", type=float, default=12.0, help="Per-server measurement timeout in seconds (default 12). An unreachable server becomes a skipped row, never a failure.")
    mcp_savings.add_argument("--claude-config", default="", help="Override the Claude Code config path (default ~/.claude.json).")
    mcp_savings.set_defaults(func=mcp_cmds.cmd_mcp_savings)
    mcp_install = mcp_sub.add_parser(
        "install",
        help="Install host integrations for the Unlimited Tools MCP gateway. Claude Code support edits .mcp.json/.claude.json safely with backups.",
    )
    mcp_install.add_argument("install_action", nargs="?", choices=["status"], default=None, help="Use `status` to inspect Claude Code MCP gateway installation state.")
    mcp_install.add_argument("--claude-code", action="store_true", help="Install the Unlimited Tools gateway into Claude Code MCP config.")
    mcp_install.add_argument("--project", action="store_true", help="Use the current project's .mcp.json (default).")
    mcp_install.add_argument("--global", dest="global_scope", action="store_true", help="Use the global ~/.claude.json mcpServers section.")
    mcp_install.add_argument("--dry-run", action="store_true", help="Show a redacted diff without writing files.")
    mcp_install.add_argument("--force", action="store_true", help="Replace an existing unlimited-tools server entry if it differs.")
    mcp_install.add_argument("--json", action="store_true", help="Print a machine-readable report.")
    mcp_install.add_argument("--project-root", default="", help=argparse.SUPPRESS)
    mcp_install.add_argument("--claude-config", default="", help=argparse.SUPPRESS)
    mcp_install.add_argument("--gateway-config", default="", help=argparse.SUPPRESS)
    mcp_install.set_defaults(func=mcp_cmds.cmd_mcp_install)
    mcp_uninstall = mcp_sub.add_parser(
        "uninstall",
        help="Remove host integrations installed by `unlimited-skills mcp install`.",
    )
    mcp_uninstall.add_argument("--claude-code", action="store_true", help="Remove the Unlimited Tools gateway from Claude Code MCP config.")
    mcp_uninstall.add_argument("--project", action="store_true", help="Use the current project's .mcp.json (default).")
    mcp_uninstall.add_argument("--global", dest="global_scope", action="store_true", help="Use the global ~/.claude.json mcpServers section.")
    mcp_uninstall.add_argument("--dry-run", action="store_true", help="Show a redacted diff without writing files.")
    mcp_uninstall.add_argument("--json", action="store_true", help="Print a machine-readable report.")
    mcp_uninstall.add_argument("--project-root", default="", help=argparse.SUPPRESS)
    mcp_uninstall.add_argument("--claude-config", default="", help=argparse.SUPPRESS)
    mcp_uninstall.add_argument("--gateway-config", default="", help=argparse.SUPPRESS)
    mcp_uninstall.set_defaults(func=mcp_cmds.cmd_mcp_uninstall)
    mcp_trust = mcp_sub.add_parser(
        "trust",
        help="Manage the local trust store for signed MCP profile bundles: PUBLIC keys and the local CRL. Offline only -- no registry sync, no hosted calls, never private keys.",
    )
    mcp_trust_sub = mcp_trust.add_subparsers(dest="trust_command", required=True)

    def add_trust_common(command: argparse.ArgumentParser) -> None:
        command.add_argument("--store-dir", default="", help="Trust store directory. Defaults to <root>/.unlimited-skills-trust.")
        command.add_argument("--json", action="store_true", help="Print a machine-readable JSON report.")

    trust_status = mcp_trust_sub.add_parser("status", help="Show the store location, key counts by state (active/expiring/expired/revoked), CRL presence, and problems.")
    add_trust_common(trust_status)
    trust_status.add_argument("--expiring-days", type=int, default=30, help="Days before not_after at which a key counts as 'expiring soon'. Default 30.")
    trust_status.set_defaults(func=mcp_cmds.cmd_mcp_trust_status)
    trust_list = mcp_trust_sub.add_parser("list", help="List trusted keys: key_id, display, scopes, validity window, state, abbreviated fingerprint (never full key bytes).")
    add_trust_common(trust_list)
    trust_list.add_argument("--expiring-days", type=int, default=30, help="Days before not_after at which a key counts as 'expiring soon'. Default 30.")
    trust_list.set_defaults(func=mcp_cmds.cmd_mcp_trust_list)
    trust_import = mcp_trust_sub.add_parser("import", help="Add one PUBLIC Ed25519 key to the managed trusted-keys file. Refuses private key material and key_id collisions with different material.")
    add_trust_common(trust_import)
    trust_import.add_argument("--key-file", default="", help="JSON key file with key_id/public_key and optional display/scopes/not_before/not_after/comment. Inline flags win over file fields.")
    trust_import.add_argument("--key-id", default="", help="The key identifier (E09 key_id grammar).")
    trust_import.add_argument("--public-key", default="", help="Base64 raw 32-byte Ed25519 PUBLIC key. Anything that looks private (PEM PRIVATE markers, 48/64-byte material) is refused.")
    trust_import.add_argument("--display", default="", help="Human-readable key owner name (metadata sidecar only; max 128 chars).")
    trust_import.add_argument("--scope", action="append", default=None, metavar="SCOPE", help="Informational key scope label (repeatable). Default: profile-bundles. Never parsed by verification.")
    trust_import.add_argument("--not-before", default="", help="Informational RFC 3339 UTC validity start (metadata sidecar only; not enforced by verification).")
    trust_import.add_argument("--not-after", default="", help="RFC 3339 UTC per-key trust deadline written into the trusted-keys file (enforced by E14 verification).")
    trust_import.add_argument("--comment", default="", help="Free-text comment stored on the trusted-keys entry.")
    trust_import.set_defaults(func=mcp_cmds.cmd_mcp_trust_import)
    trust_revoke = mcp_trust_sub.add_parser("revoke", help="Add a key_id or bundle SHA-256 to the managed local CRL. Idempotent; append-only -- revocation history is never deleted.")
    add_trust_common(trust_revoke)
    trust_revoke.add_argument("--key-id", default="", help="Revoke a signing key: kills every bundle the key ever signed (E14 semantics).")
    trust_revoke.add_argument("--bundle-sha256", default="", help="Revoke one specific bundle by the SHA-256 hex of its file bytes.")
    trust_revoke.add_argument("--reason", default="", help="Optional reason recorded in the metadata sidecar (the E14 CRL format has no reason field).")
    trust_revoke.set_defaults(func=mcp_cmds.cmd_mcp_trust_revoke)
    trust_doctor = mcp_trust_sub.add_parser("doctor", help="Offline store self-check: file shapes, duplicate key_ids, rotation/expiry, CRL readability, revocation explanations, permissions (best-effort). Exit 0 ok / 1 problems.")
    add_trust_common(trust_doctor)
    trust_doctor.add_argument("--expiring-days", type=int, default=30, help="Days before not_after at which a key warns as 'expiring soon'. Default 30.")
    trust_doctor.set_defaults(func=mcp_cmds.cmd_mcp_trust_doctor)
    mcp_audit_report = mcp_sub.add_parser(
        "audit-report",
        help="Inspect the local redacted MCP audit JSONL log (including rotated generations): summary, refusals, upstream health, profile usage, redaction self-check.",
    )
    mcp_audit_report.add_argument("--audit-log", default="", help="Audit log path to inspect. Defaults to <root>/.learning/mcp-audit.jsonl.")
    mcp_audit_report.add_argument("--json", action="store_true", help="Print the full report as one JSON document (schemas/mcp-audit-report.schema.json).")
    mcp_audit_report.add_argument(
        "--section",
        choices=["summary", "refusals", "upstreams", "profiles", "redaction", "all"],
        default="all",
        help="Limit the plain-text report to one section. JSON output is always the full document.",
    )
    mcp_audit_report.set_defaults(func=mcp_cmds.cmd_mcp_audit_report)
    mcp_profiles = mcp_sub.add_parser(
        "profiles",
        help="Dry-run rollout simulator and policy doctor for MCP tool profiles and signed bundles: shows what WOULD happen before applying. Read-only -- never spawns upstreams, no runtime state changes, no network, no telemetry.",
    )
    mcp_profiles_sub = mcp_profiles.add_subparsers(dest="profiles_command", required=True)

    def add_rollout_common(command: argparse.ArgumentParser) -> None:
        command.add_argument("--config", default="", help="Gateway JSON config (schemas/mcp-upstream-config.schema.json); its pre-declared 'tools' entries are the default tool list. Never spawned here.")
        command.add_argument("--profiles", default="", help="Raw permissioned tool-profile JSON file (E09/E10). Alongside --bundle it is the narrow-only local override.")
        command.add_argument("--bundle", default="", help="SIGNED profile bundle JSON file (schemas/mcp-profile-bundle.schema.json); the REAL E14 verification runs in dry-run.")
        command.add_argument("--trusted-keys", default="", help="Trusted-keys JSON file for bundle verification. Omitted: defaults to the managed trust store's trusted-keys.json under <root>/.unlimited-skills-trust when it exists (E15).")
        command.add_argument("--audience-id", action="append", default=None, metavar="ID", help="This consumer's audience identifier ('team:NAME', 'org:NAME', or 'host:NAME'). Repeatable; beats UNLIMITED_SKILLS_MCP_AUDIENCE.")
        command.add_argument("--profile", default="", help="Profile name to simulate. Precedence: this flag > UNLIMITED_SKILLS_MCP_PROFILE > the source's default_profile.")
        command.add_argument("--tools-fixture", default="", help="What-if tool list: a JSON list of {upstream, name, description} objects, replacing the config's pre-declared tools.")
        command.add_argument("--require-signed-profiles", action="store_true", help="Simulate the signed-required policy: unsigned profile sources fail closed with -32015.")
        command.add_argument("--json", action="store_true")

    rollout_plan = mcp_profiles_sub.add_parser(
        "rollout-plan",
        help="Build the dry-run rollout plan: visible/hidden/callable tool counts and lists, upstreams that would never spawn, the inheritance chain and its narrowing, what E14 verification WOULD say, and the audit impact. JSON validates against schemas/mcp-profile-rollout-plan.schema.json.",
    )
    add_rollout_common(rollout_plan)
    rollout_plan.set_defaults(func=mcp_cmds.cmd_mcp_profiles_rollout_plan)
    profiles_doctor = mcp_profiles_sub.add_parser(
        "doctor",
        help="Policy doctor over the same dry-run inputs: distinct findings (missing/corrupt trust store, expired/revoked/unknown keys, wrong audience, namespace-ceiling violations, hides-all profiles, inert callable rules, shadowed tool names, over-deep chains, unsigned-under-signed-policy). Exit 0 clean / 1 problems.",
    )
    add_rollout_common(profiles_doctor)
    profiles_doctor.set_defaults(func=mcp_cmds.cmd_mcp_profiles_doctor)
    replay_audit = mcp_profiles_sub.add_parser(
        "replay-audit",
        help="Replay the HISTORICAL redacted audit log against a PROPOSED policy (profile/bundle/trust store/config): which calls would still pass, which would be refused with which would-be code, which workflows break, and a safe/safe_with_warnings/blocked recommendation. Read-only -- no tool execution, no upstream spawn, no profile activation. JSON validates against schemas/mcp-audit-replay-report.schema.json.",
    )
    replay_audit.add_argument("--audit-log", default="", help="Audit log to replay (plus rotated generations). Defaults to <root>/.learning/mcp-audit.jsonl.")
    replay_audit.add_argument("--config", default="", help="Proposed gateway JSON config (schemas/mcp-upstream-config.schema.json); adds the upstream trust gates (-32005/-32010) to the replay. Never spawned here.")
    replay_audit.add_argument("--profiles", default="", help="Proposed raw permissioned tool-profile JSON file (E09/E10). Alongside --bundle it is the narrow-only local override.")
    replay_audit.add_argument("--bundle", default="", help="Proposed SIGNED profile bundle JSON file (schemas/mcp-profile-bundle.schema.json); the REAL E14 verification runs in dry-run.")
    replay_audit.add_argument("--trusted-keys", default="", help="Trusted-keys JSON file for bundle verification (wins over --trust-store).")
    replay_audit.add_argument("--trust-store", default="", help="Trust store DIRECTORY whose trusted-keys.json verifies --bundle. Omitted: defaults to the managed store under <root>/.unlimited-skills-trust when it exists (E15).")
    replay_audit.add_argument("--audience-id", action="append", default=None, metavar="ID", help="This consumer's audience identifier ('team:NAME', 'org:NAME', or 'host:NAME'). Repeatable; beats UNLIMITED_SKILLS_MCP_AUDIENCE.")
    replay_audit.add_argument("--profile", default="", help="Profile name to simulate. Precedence: this flag > UNLIMITED_SKILLS_MCP_PROFILE > the source's default_profile.")
    replay_audit.add_argument("--require-signed-profiles", action="store_true", help="Simulate the signed-required policy: unsigned profile sources fail closed with -32015.")
    replay_audit.add_argument("--json", action="store_true", help="Print the full report as one JSON document (schemas/mcp-audit-replay-report.schema.json).")
    replay_audit.set_defaults(func=mcp_cmds.cmd_mcp_profiles_replay_audit)
    mcp_bundle = mcp_sub.add_parser(
        "bundle",
        help="Local signing/publishing ceremony for MCP profile bundles: DEV/FIXTURE keygen, validate-sign-package-verify publish, and a verify wrapper over the real E14 verification. Offline only -- no production keys, no hosted calls, no registry sync; private key material is never printed.",
    )
    mcp_bundle_sub = mcp_bundle.add_subparsers(dest="bundle_command", required=True)
    bundle_keygen = mcp_bundle_sub.add_parser(
        "keygen",
        help="Generate a DEV/FIXTURE Ed25519 keypair (requires the optional 'cryptography' package). The PRIVATE key is written ONLY to --out with a loud 'DEV KEY -- do not use in production' header; the PUBLIC key is emitted in the 'mcp trust import --key-file' format. Production signing keys are out of scope and never generated.",
    )
    bundle_keygen.add_argument("--out", required=True, help="Directory to write the keypair into -- the ONLY place the private key will exist.")
    bundle_keygen.add_argument("--key-id", default="dev-signing-key", help="Key identifier (E09 key_id grammar). Default: dev-signing-key.")
    bundle_keygen.add_argument("--display", default="", help="Human-readable owner name stored on the PUBLIC key file (max 128 chars).")
    bundle_keygen.add_argument("--force", action="store_true", help="Overwrite existing key files in --out.")
    bundle_keygen.add_argument("--json", action="store_true", help="Print the result as JSON (paths and fingerprint only -- never key material).")
    bundle_keygen.set_defaults(func=mcp_cmds.cmd_mcp_bundle_keygen)
    bundle_publish = mcp_bundle_sub.add_parser(
        "publish",
        help="Run the local ceremony: validate the raw profile (real E09/E10 loader), build and sign the bundle (canonical JSON, detached Ed25519), package <out>/<name>.bundle.json + MANIFEST + VALIDATION-REPORT + ROLLBACK atomically, and self-check through the REAL E14 verification -- any failure leaves no signed bundle behind.",
    )
    bundle_publish.add_argument("--profiles", required=True, help="Raw permissioned tool-profile JSON file (schemas/mcp-tool-profile.schema.json) to embed.")
    bundle_publish.add_argument("--signing-key", required=True, help="PRIVATE dev signing-key file from 'mcp bundle keygen'. PUBLIC-only files are refused.")
    bundle_publish.add_argument("--issuer-key-id", default="", help="Issuer key_id; must match the signing key file's key_id (defaults to it).")
    bundle_publish.add_argument("--audience", action="append", default=None, metavar="ID", help="Bundle audience identifier ('team:NAME', 'org:NAME', or 'host:NAME'). Repeatable; REQUIRED non-empty.")
    bundle_publish.add_argument("--expires-days", type=int, default=30, help="Validity window length in days from now (>= 1). Default 30.")
    bundle_publish.add_argument("--namespaces", action="append", default=None, metavar="NS", help="allowed_upstream_namespaces rule (E09 rule grammar). Repeatable. Omitted: derived whole-upstream rules from the profile map. Every profile rule must stay inside the ceiling.")
    bundle_publish.add_argument("--out", default=".", help="Output directory for the bundle package. Default: current directory.")
    bundle_publish.add_argument("--name", default="", help="Package name (<name>.bundle.json). Default: the profiles file stem.")
    bundle_publish.add_argument("--display", default="", help="Issuer display name embedded in the bundle (max 128 chars).")
    bundle_publish.add_argument("--previous", default="", help="Previous bundle: a 64-hex SHA-256 or a path to the previous bundle file. Recorded in the ROLLBACK metadata.")
    bundle_publish.add_argument("--crl-path", default="", help="Optional absolute local CRL path embedded as the bundle's revocation pointer (revocation.crl_path).")
    bundle_publish.add_argument("--dry-run", action="store_true", help="Run every step including the E14 self-check against a private temp copy, but write NOTHING to --out; report what WOULD be produced.")
    bundle_publish.add_argument("--force", action="store_true", help="Overwrite existing package files in --out.")
    bundle_publish.add_argument("--json", action="store_true", help="Print the ceremony result as JSON.")
    bundle_publish.set_defaults(func=mcp_cmds.cmd_mcp_bundle_publish)
    bundle_verify = mcp_bundle_sub.add_parser(
        "verify",
        help="Verify a bundle through the REAL E14 verification (resolve_bundle_state) and report ok or the exact refusal code/name. Exit 0 verified / 1 refused. This is the ceremony's self-check step, also run automatically by publish.",
    )
    bundle_verify.add_argument("--bundle", required=True, help="Signed bundle JSON file to verify.")
    bundle_verify.add_argument("--trusted-keys", required=True, help="Trusted-keys JSON file (E14 format; e.g. the managed store's trusted-keys.json).")
    bundle_verify.add_argument("--audience-id", action="append", default=None, metavar="ID", help="This consumer's audience identifier. Repeatable; beats UNLIMITED_SKILLS_MCP_AUDIENCE.")
    bundle_verify.add_argument("--json", action="store_true", help="Print the verification report as JSON.")
    bundle_verify.set_defaults(func=mcp_cmds.cmd_mcp_bundle_verify)

    catalog = sub.add_parser("catalog", help="Query the registered hosted adapted-skill catalog and browser.")
    catalog_sub = catalog.add_subparsers(dest="catalog_command", required=True)
    catalog_list = catalog_sub.add_parser("list", help="List the hosted adapted-skill catalog for this registered installation.")
    catalog_list.add_argument("--channel", default="", help="Override the pinned release channel for this catalog request.")
    catalog_list.add_argument("--timeout", type=float, default=30.0)
    catalog_list.set_defaults(func=catalog_cmds.cmd_catalog_list)
    catalog_browse = catalog_sub.add_parser("browse", help="Browse signed reviewed catalog metadata.")
    catalog_browse.add_argument("--channel", default="", choices=["", "stable", "beta", "canary"])
    catalog_browse.add_argument("--source", default="", choices=["", "official", "community", "private-visible"])
    catalog_browse.add_argument("--compatible-agent", default="", choices=["", "codex", "claude-code", "hermes", "openclaw", "vellum-ai"])
    catalog_browse.add_argument("--skill-kind", default="")
    catalog_browse.add_argument("--category", default="")
    catalog_browse.add_argument("--include-deprecated", action="store_true")
    catalog_browse.add_argument("--show-quality", action="store_true", help="Include signed quality/evaluation summary fields in browser results.")
    catalog_browse.add_argument("--limit", type=int, default=50)
    catalog_browse.add_argument("--json", action="store_true")
    catalog_browse.add_argument("--timeout", type=float, default=30.0)
    catalog_browse.set_defaults(func=catalog_cmds.cmd_catalog_browse)
    catalog_search = catalog_sub.add_parser("search", help="Search signed reviewed catalog metadata.")
    catalog_search.add_argument("query")
    catalog_search.add_argument("--channel", default="", choices=["", "stable", "beta", "canary"])
    catalog_search.add_argument("--source", default="", choices=["", "official", "community", "private-visible"])
    catalog_search.add_argument("--compatible-agent", default="", choices=["", "codex", "claude-code", "hermes", "openclaw", "vellum-ai"])
    catalog_search.add_argument("--skill-kind", default="")
    catalog_search.add_argument("--category", default="")
    catalog_search.add_argument("--include-deprecated", action="store_true")
    catalog_search.add_argument("--show-quality", action="store_true", help="Include signed quality/evaluation summary fields in search results.")
    catalog_search.add_argument("--limit", type=int, default=20)
    catalog_search.add_argument("--json", action="store_true")
    catalog_search.add_argument("--timeout", type=float, default=30.0)
    catalog_search.set_defaults(func=catalog_cmds.cmd_catalog_search)
    catalog_filters = catalog_sub.add_parser("filters", help="Show signed catalog browser filter options.")
    catalog_filters.add_argument("--channel", default="", choices=["", "stable", "beta", "canary"])
    catalog_filters.add_argument("--timeout", type=float, default=30.0)
    catalog_filters.set_defaults(func=catalog_cmds.cmd_catalog_filters)
    catalog_preview = catalog_sub.add_parser("preview", help="Preview signed catalog metadata without skill bodies.")
    catalog_preview.add_argument("item_id")
    catalog_preview.add_argument("--channel", default="", choices=["", "stable", "beta", "canary"])
    catalog_preview.add_argument("--json", action="store_true")
    catalog_preview.add_argument("--timeout", type=float, default=30.0)
    catalog_preview.set_defaults(func=catalog_cmds.cmd_catalog_preview)
    catalog_recommendation_preview = catalog_sub.add_parser(
        "recommendation-preview",
        help="Build a policy-aware recommendation preview without applying changes.",
    )
    catalog_recommendation_preview.add_argument("item_id", nargs="?", default="")
    catalog_recommendation_preview.add_argument("--fixture-case", default="", help="Use a deterministic recommendation-policy fixture case instead of hosted metadata.")
    catalog_recommendation_preview.add_argument("--agent", default="", choices=["", "codex", "claude-code", "hermes", "openclaw", "vellum-ai"])
    catalog_recommendation_preview.add_argument("--channel", default="", choices=["", "stable", "beta", "canary"])
    catalog_recommendation_preview.add_argument(
        "--strict-supplemental",
        action="store_true",
        help="Fail if supplemental signed quality or improvement metadata cannot be loaded.",
    )
    catalog_recommendation_preview.add_argument("--json", action="store_true")
    catalog_recommendation_preview.add_argument("--timeout", type=float, default=30.0)
    catalog_recommendation_preview.set_defaults(func=catalog_cmds.cmd_catalog_recommendation_preview)
    catalog_install = catalog_sub.add_parser("install", help="Verify and install a signed approved catalog item.")
    catalog_install.add_argument("item_id")
    catalog_install.add_argument("--collection", default="", help="Override local target collection for delegated community installs.")
    catalog_install.add_argument("--dry-run", action="store_true", help="Verify signed approved metadata without downloading or writing.")
    catalog_install.add_argument("--yes", action="store_true", help="Confirm install in non-interactive mode.")
    catalog_install.add_argument("--skip-reindex", action="store_true")
    catalog_install.add_argument("--json", action="store_true")
    catalog_install.add_argument("--timeout", type=float, default=30.0)
    catalog_install.set_defaults(func=catalog_cmds.cmd_catalog_install)
    catalog_feedback = catalog_sub.add_parser("feedback", help="Submit explicit redacted feedback for a catalog item.")
    catalog_feedback.add_argument("item_id")
    catalog_feedback.add_argument("--type", required=True, choices=["install_failure", "compatibility_issue", "missing_capability", "documentation_issue", "security_concern"])
    catalog_feedback.add_argument("--severity", default="medium", choices=["low", "medium", "high", "critical"])
    catalog_feedback.add_argument("--title", default="")
    catalog_feedback.add_argument("--agent", default="")
    catalog_feedback.add_argument("--client-version", default="")
    catalog_feedback.add_argument("--core-version", default="")
    catalog_feedback.add_argument("--os", default="")
    catalog_feedback.add_argument("--command", default="")
    catalog_feedback.add_argument("--error-code", default="")
    catalog_feedback.add_argument("--http-status", type=int, default=0)
    catalog_feedback.add_argument("--expected-behavior", default="")
    catalog_feedback.add_argument("--actual-behavior", default="")
    catalog_feedback.add_argument("--reproduction-hint", default="")
    catalog_feedback.add_argument("--dry-run", action="store_true", help="Print the redacted payload without sending it.")
    catalog_feedback.add_argument("--yes", action="store_true", help="Confirm feedback submit in non-interactive mode.")
    catalog_feedback.add_argument("--json", action="store_true")
    catalog_feedback.add_argument("--timeout", type=float, default=30.0)
    catalog_feedback.set_defaults(func=catalog_cmds.cmd_catalog_feedback)
    catalog_feedback_status = catalog_sub.add_parser("feedback-status", help="Show aggregate feedback status for a catalog item.")
    catalog_feedback_status.add_argument("item_id")
    catalog_feedback_status.add_argument("--limit", type=int, default=100)
    catalog_feedback_status.add_argument("--json", action="store_true")
    catalog_feedback_status.add_argument("--timeout", type=float, default=30.0)
    catalog_feedback_status.set_defaults(func=catalog_cmds.cmd_catalog_feedback_status)
    catalog_quality = catalog_sub.add_parser("quality", help="Show signed quality status for one catalog item.")
    catalog_quality.add_argument("item_id")
    catalog_quality.add_argument("--json", action="store_true")
    catalog_quality.add_argument("--timeout", type=float, default=30.0)
    catalog_quality.set_defaults(func=catalog_cmds.cmd_catalog_quality)
    catalog_eval_status = catalog_sub.add_parser("eval-status", help="Show signed evaluation status for one catalog item.")
    catalog_eval_status.add_argument("item_id")
    catalog_eval_status.add_argument("--json", action="store_true")
    catalog_eval_status.add_argument("--timeout", type=float, default=30.0)
    catalog_eval_status.set_defaults(func=catalog_cmds.cmd_catalog_eval_status)
    catalog_explain_risk = catalog_sub.add_parser("explain-risk", help="Explain signed install-risk warnings for one catalog item.")
    catalog_explain_risk.add_argument("item_id")
    catalog_explain_risk.add_argument("--json", action="store_true")
    catalog_explain_risk.add_argument("--timeout", type=float, default=30.0)
    catalog_explain_risk.set_defaults(func=catalog_cmds.cmd_catalog_explain_risk)
    catalog_improvement_status = catalog_sub.add_parser("improvement-status", help="Show signed skill improvement and remediation status.")
    catalog_improvement_status.add_argument("item_id")
    catalog_improvement_status.add_argument("--include-queue", action="store_true", help="Include signed maintainer queue status context.")
    catalog_improvement_status.add_argument("--json", action="store_true")
    catalog_improvement_status.add_argument("--timeout", type=float, default=30.0)
    catalog_improvement_status.set_defaults(func=catalog_cmds.cmd_catalog_improvement_status)
    catalog_maintainer_status = catalog_sub.add_parser("maintainer-status", help="Show signed maintainer queue status for one catalog item.")
    catalog_maintainer_status.add_argument("item_id")
    catalog_maintainer_status.add_argument("--json", action="store_true")
    catalog_maintainer_status.add_argument("--timeout", type=float, default=30.0)
    catalog_maintainer_status.set_defaults(func=catalog_cmds.cmd_catalog_maintainer_status)
    catalog_maintainer_queue_summary = catalog_sub.add_parser("maintainer-queue-summary", help="Show signed maintainer queue summary counts.")
    catalog_maintainer_queue_summary.add_argument("--json", action="store_true")
    catalog_maintainer_queue_summary.add_argument("--timeout", type=float, default=30.0)
    catalog_maintainer_queue_summary.set_defaults(func=catalog_cmds.cmd_catalog_maintainer_queue_summary)
    catalog_fixed_pending_eval = catalog_sub.add_parser("fixed-pending-eval", help="Show signed fixed-pending-eval evidence status for one catalog item.")
    catalog_fixed_pending_eval.add_argument("item_id")
    catalog_fixed_pending_eval.add_argument("--json", action="store_true")
    catalog_fixed_pending_eval.add_argument("--timeout", type=float, default=30.0)
    catalog_fixed_pending_eval.set_defaults(func=catalog_cmds.cmd_catalog_fixed_pending_eval)
    catalog_known_issues = catalog_sub.add_parser("known-issues", help="Show signed known-issue metadata for one catalog item.")
    catalog_known_issues.add_argument("item_id")
    catalog_known_issues.add_argument("--json", action="store_true")
    catalog_known_issues.add_argument("--timeout", type=float, default=30.0)
    catalog_known_issues.set_defaults(func=catalog_cmds.cmd_catalog_known_issues)
    catalog_update_recommendations = catalog_sub.add_parser("update-recommendations", help="Show preview-only signed update/remove recommendations.")
    catalog_update_recommendations.add_argument("--include-queue", action="store_true", help="Include signed maintainer queue summary and per-item queue status.")
    catalog_update_recommendations.add_argument("--json", action="store_true")
    catalog_update_recommendations.add_argument("--timeout", type=float, default=30.0)
    catalog_update_recommendations.set_defaults(func=catalog_cmds.cmd_catalog_update_recommendations)
    catalog_update_preview = catalog_sub.add_parser("update-preview", help="Preview a signed update/remove recommendation without applying it.")
    catalog_update_preview.add_argument("item_id")
    catalog_update_preview.add_argument("--json", action="store_true")
    catalog_update_preview.add_argument("--timeout", type=float, default=30.0)
    catalog_update_preview.set_defaults(func=catalog_cmds.cmd_catalog_update_preview)
    catalog_deprecation_status = catalog_sub.add_parser("deprecation-status", help="Show signed deprecation or retirement status for one catalog item.")
    catalog_deprecation_status.add_argument("item_id")
    catalog_deprecation_status.add_argument("--json", action="store_true")
    catalog_deprecation_status.add_argument("--timeout", type=float, default=30.0)
    catalog_deprecation_status.set_defaults(func=catalog_cmds.cmd_catalog_deprecation_status)

    release = sub.add_parser("release", help="Inspect and pin hosted registry release channels.")
    release_sub = release.add_subparsers(dest="release_command", required=True)
    release_status = release_sub.add_parser("status", help="Fetch signed release channel status.")
    release_status.add_argument("--channel", default="", help="Temporarily inspect one channel.")
    release_status.add_argument("--json", action="store_true")
    release_status.add_argument("--timeout", type=float, default=30.0)
    release_status.set_defaults(func=updates_cmds.cmd_release_status)
    release_pin = release_sub.add_parser("pin", help="Pin this installation to a release channel.")
    release_pin.add_argument("channel", choices=["stable", "beta", "canary"])
    release_pin.set_defaults(func=updates_cmds.cmd_release_pin)

    community = sub.add_parser("community", help="Browse, install, submit, and manage registered community skills.")
    community_sub = community.add_subparsers(dest="community_command", required=True)
    community_list = community_sub.add_parser("list", help="List registered community catalog skills.")
    community_list.add_argument("--limit", type=int, default=50)
    community_list.add_argument("--tags", default="", help="Comma-separated tag filter.")
    community_list.add_argument("--channel", default="", choices=["", "canary", "beta", "stable"], help="Filter approved signed community items by release channel.")
    community_list.add_argument("--compatible-agent", default="", choices=["", "codex", "claude-code", "hermes", "openclaw", "vellum-ai"])
    community_list.add_argument("--json", action="store_true")
    community_list.add_argument("--timeout", type=float, default=30.0)
    community_list.set_defaults(func=community_cmds.cmd_community_list)
    community_search = community_sub.add_parser("search", help="Search registered community skills.")
    community_search.add_argument("query")
    community_search.add_argument("--limit", type=int, default=20)
    community_search.add_argument("--tags", default="", help="Comma-separated tag filter.")
    community_search.add_argument("--compatible-agent", default="", choices=["", "codex", "claude-code", "hermes", "openclaw", "vellum-ai"])
    community_search.add_argument("--json", action="store_true")
    community_search.add_argument("--timeout", type=float, default=30.0)
    community_search.set_defaults(func=community_cmds.cmd_community_search)
    community_preview = community_sub.add_parser("preview", help="Preview sanitized community skill metadata and install warnings.")
    community_preview.add_argument("catalog_item_id")
    community_preview.add_argument("--json", action="store_true")
    community_preview.add_argument("--timeout", type=float, default=30.0)
    community_preview.set_defaults(func=community_cmds.cmd_community_preview)
    community_install = community_sub.add_parser("install", help="Install a registered community skill or pack.")
    community_install.add_argument("catalog_item_id")
    community_install.add_argument("--collection", default="", help="Override local target collection.")
    community_install.add_argument("--dry-run", action="store_true", help="Show server install plan without downloading or writing.")
    community_install.add_argument("--force", action="store_true", help="Allow overwriting the target collection when the service plan permits it.")
    community_install.add_argument("--yes", action="store_true", help="Confirm install in non-interactive mode.")
    community_install.add_argument("--skip-reindex", action="store_true", help="Do not rebuild the lexical index after install.")
    community_install.add_argument("--json", action="store_true")
    community_install.add_argument("--timeout", type=float, default=30.0)
    community_install.set_defaults(func=community_cmds.cmd_community_install)
    community_submit = community_sub.add_parser("submit", help="Preview and submit a selected local skill or pack for community review.")
    community_submit.add_argument("path")
    community_submit.add_argument("--name", default="")
    community_submit.add_argument("--description", default="")
    community_submit.add_argument("--tags", default="", help="Comma-separated submission tags.")
    community_submit.add_argument("--compatible-agent", action="append", choices=["codex", "claude-code", "hermes", "openclaw", "vellum-ai"])
    community_submit.add_argument("--visibility", default="registered-community", choices=["registered-community", "team-free", "pro", "enterprise"])
    community_submit.add_argument("--dry-run", action="store_true", help="Validate and write preview without uploading.")
    community_submit.add_argument("--yes", action="store_true", help="Confirm upload in non-interactive mode.")
    community_submit.add_argument("--json", action="store_true", help="Accepted for consistency; submit output is JSON.")
    community_submit.add_argument("--timeout", type=float, default=30.0)
    community_submit.set_defaults(func=community_cmds.cmd_community_submit)
    community_status = community_sub.add_parser("submission-status", help="Show one submission status, or recent submissions when no id is provided.")
    community_status.add_argument("submission_id", nargs="?", default="")
    community_status.add_argument("--timeout", type=float, default=30.0)
    community_status.set_defaults(func=community_cmds.cmd_community_submission_status)
    community_withdraw = community_sub.add_parser("withdraw", help="Withdraw a pending community submission.")
    community_withdraw.add_argument("submission_id")
    community_withdraw.add_argument("--timeout", type=float, default=30.0)
    community_withdraw.set_defaults(func=community_cmds.cmd_community_withdraw)
    community_review_notes = community_sub.add_parser("review-notes", help="Show maintainer review notes for a community submission.")
    community_review_notes.add_argument("submission_id")
    community_review_notes.add_argument("--timeout", type=float, default=30.0)
    community_review_notes.set_defaults(func=community_cmds.cmd_community_review_notes)
    community_installed = community_sub.add_parser("installed", help="List locally installed community skills without hosted calls by default.")
    community_installed.add_argument("--refresh", action="store_true", help="Check hosted service for refresh metadata; requires registration.")
    community_installed.add_argument("--json", action="store_true")
    community_installed.add_argument("--timeout", type=float, default=30.0)
    community_installed.set_defaults(func=community_cmds.cmd_community_installed)
    community_remove = community_sub.add_parser("remove", help="Remove a locally installed community item.")
    community_remove.add_argument("collection_or_skill_name")
    community_remove.add_argument("--dry-run", action="store_true", help="Show what would be removed.")
    community_remove.add_argument("--force", action="store_true", help="Allow removal when the item is not marked as community-installed.")
    community_remove.add_argument("--yes", action="store_true", help="Actually remove without interactive confirmation.")
    community_remove.add_argument("--skip-reindex", action="store_true", help="Do not rebuild the lexical index after removal.")
    community_remove.add_argument("--json", action="store_true")
    community_remove.set_defaults(func=community_cmds.cmd_community_remove)

    org = sub.add_parser("org", help="Show registered organization and entitlement status.")
    org_sub = org.add_subparsers(dest="org_command", required=True)
    org_status = org_sub.add_parser("status", help="Show cached organization status, or refresh it from the hosted service.")
    org_status.add_argument("--refresh", action="store_true", help="Refresh hosted organization status; requires registration.")
    org_status.add_argument("--json", action="store_true")
    org_status.add_argument("--timeout", type=float, default=30.0)
    org_status.set_defaults(func=accounts_cmds.cmd_org_status)

    plan = sub.add_parser("plan", help="Inspect registered plan and entitlement status.")
    plan_sub = plan.add_subparsers(dest="plan_command", required=True)
    plan_status = plan_sub.add_parser("status", help="Show cached plan status without hosted calls.")
    plan_status.add_argument("--json", action="store_true")
    plan_status.set_defaults(func=accounts_cmds.cmd_plan_status)
    plan_refresh = plan_sub.add_parser("refresh", help="Refresh plan status from the registered service.")
    plan_refresh.add_argument("--json", action="store_true")
    plan_refresh.add_argument("--timeout", type=float, default=30.0)
    plan_refresh.set_defaults(func=accounts_cmds.cmd_plan_refresh)
    plan_explain = plan_sub.add_parser("explain", help="Explain whether the current plan allows a feature.")
    plan_explain.add_argument("feature")
    plan_explain.add_argument("--json", action="store_true")
    plan_explain.set_defaults(func=accounts_cmds.cmd_plan_explain)
    plan_doctor_parser = plan_sub.add_parser("doctor", help="Run local plan and entitlement diagnostics.")
    plan_doctor_parser.add_argument("--json", action="store_true")
    plan_doctor_parser.set_defaults(func=accounts_cmds.cmd_plan_doctor)

    billing = sub.add_parser("billing", help="Inspect sandbox billing lifecycle diagnostics.")
    billing_sub = billing.add_subparsers(dest="billing_command", required=True)
    billing_status = billing_sub.add_parser("status", help="Show cached billing lifecycle status without hosted calls.")
    billing_status.add_argument("--json", action="store_true")
    billing_status.set_defaults(func=accounts_cmds.cmd_billing_status)
    billing_refresh = billing_sub.add_parser("refresh", help="Refresh billing lifecycle status from the registered service.")
    billing_refresh.add_argument("--json", action="store_true")
    billing_refresh.add_argument("--timeout", type=float, default=30.0)
    billing_refresh.set_defaults(func=accounts_cmds.cmd_billing_refresh)
    billing_doctor_parser = billing_sub.add_parser("doctor", help="Run local billing lifecycle diagnostics.")
    billing_doctor_parser.add_argument("--json", action="store_true")
    billing_doctor_parser.set_defaults(func=accounts_cmds.cmd_billing_doctor)

    private_packs = sub.add_parser("private-packs", help="Preview, install, sync, and remove registered private team packs.")
    private_packs_sub = private_packs.add_subparsers(dest="private_packs_command", required=True)
    private_packs_list = private_packs_sub.add_parser("list", help="List private team packs authorized for this installation.")
    private_packs_list.add_argument("--json", action="store_true")
    private_packs_list.add_argument("--timeout", type=float, default=30.0)
    private_packs_list.set_defaults(func=private_packs_cmds.cmd_private_packs_list)
    private_packs_preview = private_packs_sub.add_parser("preview", help="Preview redacted private team pack metadata.")
    private_packs_preview.add_argument("pack_id")
    private_packs_preview.add_argument("--json", action="store_true")
    private_packs_preview.add_argument("--timeout", type=float, default=30.0)
    private_packs_preview.set_defaults(func=private_packs_cmds.cmd_private_packs_preview)
    private_packs_install = private_packs_sub.add_parser("install", help="Install one authorized private team pack under registry/private.")
    private_packs_install.add_argument("pack_id")
    private_packs_install.add_argument("--dry-run", action="store_true", help="Verify manifest and show target without downloading or writing.")
    private_packs_install.add_argument("--yes", action="store_true", help="Confirm install in non-interactive mode.")
    private_packs_install.add_argument("--skip-reindex", action="store_true", help="Do not rebuild the lexical index after install.")
    private_packs_install.add_argument("--json", action="store_true")
    private_packs_install.add_argument("--timeout", type=float, default=30.0)
    private_packs_install.set_defaults(func=private_packs_cmds.cmd_private_packs_install)
    private_packs_sync = private_packs_sub.add_parser("sync", help="Install or update all authorized private team packs.")
    private_packs_sync.add_argument("--dry-run", action="store_true", help="Show planned changes without downloading or writing. This is the default unless --yes is passed.")
    private_packs_sync.add_argument("--yes", action="store_true", help="Apply planned private pack installs and updates.")
    private_packs_sync.add_argument("--skip-reindex", action="store_true", help="Do not rebuild the lexical index after syncing.")
    private_packs_sync.add_argument("--json", action="store_true")
    private_packs_sync.add_argument("--timeout", type=float, default=30.0)
    private_packs_sync.set_defaults(func=private_packs_cmds.cmd_private_packs_sync)
    private_packs_installed = private_packs_sub.add_parser("installed", help="List locally installed private team packs without hosted calls.")
    private_packs_installed.add_argument("--json", action="store_true")
    private_packs_installed.set_defaults(func=private_packs_cmds.cmd_private_packs_installed)
    private_packs_remove = private_packs_sub.add_parser("remove", help="Remove a locally installed registry-owned private team pack.")
    private_packs_remove.add_argument("pack_id")
    private_packs_remove.add_argument("--dry-run", action="store_true", help="Show what would be removed.")
    private_packs_remove.add_argument("--yes", action="store_true", help="Actually remove without interactive confirmation.")
    private_packs_remove.add_argument("--skip-reindex", action="store_true", help="Do not rebuild the lexical index after removal.")
    private_packs_remove.add_argument("--json", action="store_true")
    private_packs_remove.set_defaults(func=private_packs_cmds.cmd_private_packs_remove)
    private_packs_access_check = private_packs_sub.add_parser("access-check", help="Check this installation's private pack entitlement without downloading the pack.")
    private_packs_access_check.add_argument("pack_id")
    private_packs_access_check.add_argument("--json", action="store_true")
    private_packs_access_check.add_argument("--timeout", type=float, default=30.0)
    private_packs_access_check.set_defaults(func=private_packs_cmds.cmd_private_packs_access_check)
    private_packs_doctor_parser = private_packs_sub.add_parser("doctor", help="Diagnose local private pack setup without downloading skill bodies.")
    private_packs_doctor_parser.add_argument("--json", action="store_true")
    private_packs_doctor_parser.set_defaults(func=private_packs_cmds.cmd_private_packs_doctor)

    enhance = sub.add_parser("enhance", help="Download or run the registered local skill enhancement script.")
    enhance_sub = enhance.add_subparsers(dest="enhance_command", required=True)
    enhance_download = enhance_sub.add_parser("download", help="Download the registered local enhancement script without running it.")
    enhance_download.add_argument("--target-dir", default="", help="Optional script cache directory.")
    enhance_download.add_argument("--json", action="store_true")
    enhance_download.add_argument("--timeout", type=float, default=30.0)
    enhance_download.set_defaults(func=accounts_cmds.cmd_enhance_download)
    enhance_run = enhance_sub.add_parser("run", help="Download and run the registered local enhancement script. Dry-run unless --apply is passed.")
    enhance_run.add_argument("--target-dir", default="", help="Optional script cache directory.")
    enhance_run.add_argument("--apply", action="store_true", help="Write enhanced SKILL.md files. Without this flag the enhancer is a dry run.")
    enhance_run.add_argument("--limit", type=int, default=0, help="Maximum skills to inspect. Use 0 for all.")
    enhance_run.add_argument("--timeout", type=float, default=30.0)
    enhance_run.set_defaults(func=accounts_cmds.cmd_enhance_run)

    team = sub.add_parser("team", help="Register and synchronize team skill collections.")
    team_sub = team.add_subparsers(dest="team_command", required=True)
    team_status = team_sub.add_parser("status", help="Show local team registration state.")
    team_status.add_argument("--refresh", action="store_true", help="Refresh hosted team status; requires registration.")
    team_status.add_argument("--json", action="store_true")
    team_status.add_argument("--timeout", type=float, default=30.0)
    team_status.set_defaults(func=team_cmds.cmd_team_status)
    team_create = team_sub.add_parser("create", help="Create a registered team and join this installation as owner.")
    team_create.add_argument("name", nargs="?", default="", help="Team name.")
    team_create.add_argument("--name", dest="name_option", default="", help="Team name.")
    team_create.add_argument("--timeout", type=float, default=30.0)
    team_create.set_defaults(func=team_cmds.cmd_team_create)
    team_join = team_sub.add_parser("join", help="Join an existing registered team with a join code.")
    team_join.add_argument("join_code", help="Team join code from the owner/admin.")
    team_join.add_argument("--display-name", default="", help="Display name for this instance.")
    team_join.add_argument("--agent-surface", action="append", choices=["codex", "claude-code", "hermes", "openclaw", "vellum-ai"], help="Agent surface on this instance. Repeat for multiple.")
    team_join.add_argument("--timeout", type=float, default=30.0)
    team_join.set_defaults(func=team_cmds.cmd_team_join)
    team_members = team_sub.add_parser("members", help="List approved team members.")
    team_members.add_argument("--all", action="store_true", help="Include all member statuses.")
    team_members.add_argument("--pending", action="store_true", help="Show pending members only.")
    team_members.add_argument("--full-id", action="store_true", help="Show full install ids.")
    team_members.add_argument("--json", action="store_true")
    team_members.add_argument("--timeout", type=float, default=30.0)
    team_members.set_defaults(func=team_cmds.cmd_team_members)
    team_sync = team_sub.add_parser("sync", help="Download and install skill collections assigned to this team.")
    team_sync.add_argument("--collection", default="", help="Only sync one assigned collection.")
    team_sync.add_argument("--dry-run", action="store_true", help="Show assigned updates without downloading archives.")
    team_sync.add_argument("--force", action="store_true", help="Reserved for server-side install policy compatibility.")
    team_sync.add_argument("--yes", action="store_true", help="Confirm local collection changes in non-interactive mode.")
    team_sync.add_argument("--json", action="store_true")
    team_sync.add_argument("--skip-reindex", action="store_true", help="Do not rebuild the lexical index after syncing.")
    team_sync.add_argument("--timeout", type=float, default=30.0)
    team_sync.set_defaults(func=team_cmds.cmd_team_sync)
    team_pending = team_sub.add_parser("pending", help="List pending join requests for the master instance.")
    team_pending.add_argument("--full-id", action="store_true", help="Show full install ids.")
    team_pending.add_argument("--json", action="store_true")
    team_pending.add_argument("--timeout", type=float, default=30.0)
    team_pending.set_defaults(func=team_cmds.cmd_team_pending)
    team_approve = team_sub.add_parser("approve", help="Approve a pending team instance by install_id.")
    team_approve.add_argument("install_id", help="Pending installation id to approve.")
    team_approve.add_argument("--json", action="store_true")
    team_approve.add_argument("--timeout", type=float, default=30.0)
    team_approve.set_defaults(func=team_cmds.cmd_team_approve)
    team_reject = team_sub.add_parser("reject", help="Reject a pending team instance by install_id.")
    team_reject.add_argument("install_id", help="Pending installation id to reject.")
    team_reject.add_argument("--reason", default="", help="Reason for rejection. Required in non-interactive mode.")
    team_reject.add_argument("--json", action="store_true")
    team_reject.add_argument("--timeout", type=float, default=30.0)
    team_reject.set_defaults(func=team_cmds.cmd_team_reject)
    team_revoke = team_sub.add_parser("revoke", help="Revoke hosted team access for an approved instance.")
    team_revoke.add_argument("install_id", help="Approved installation id to revoke.")
    team_revoke.add_argument("--reason", default="", help="Reason for revocation.")
    team_revoke.add_argument("--yes", action="store_true", help="Confirm revocation in non-interactive mode.")
    team_revoke.add_argument("--json", action="store_true")
    team_revoke.add_argument("--timeout", type=float, default=30.0)
    team_revoke.set_defaults(func=team_cmds.cmd_team_revoke)
    team_mode = team_sub.add_parser("mode", help="Set team join approval mode. Default mode is manual.")
    team_mode.add_argument("mode", choices=["manual", "auto"])
    team_mode.add_argument("--duration", default="24h", help="Auto-approval duration, for example 1h, 6h, or 24h.")
    team_mode.add_argument("--hours", type=int, default=0, help="Legacy alias for --duration in hours.")
    team_mode.add_argument("--json", action="store_true")
    team_mode.add_argument("--timeout", type=float, default=30.0)
    team_mode.set_defaults(func=team_cmds.cmd_team_mode)
    team_collections = team_sub.add_parser("collections", help="List team-assigned collections.")
    team_collections.add_argument("--json", action="store_true")
    team_collections.add_argument("--timeout", type=float, default=30.0)
    team_collections.set_defaults(func=team_cmds.cmd_team_collections)
    team_leave = team_sub.add_parser("leave", help="Leave the current team. Does not delete local skills.")
    team_leave.add_argument("--yes", action="store_true", help="Confirm leave in non-interactive mode.")
    team_leave.add_argument("--json", action="store_true")
    team_leave.add_argument("--timeout", type=float, default=30.0)
    team_leave.set_defaults(func=team_cmds.cmd_team_leave)

    self_update = sub.add_parser("self-update", help="Check or apply public repo releases for the local Unlimited Skills core.")
    self_update_sub = self_update.add_subparsers(dest="self_update_command", required=True)
    self_update_check = self_update_sub.add_parser("check", help="Check the latest public Unlimited Skills release.")
    self_update_check.add_argument("--repo", default=DEFAULT_PUBLIC_REPO, help="GitHub repo in owner/name form.")
    self_update_check.add_argument("--install-root", default="", help="Override the detected Unlimited Skills source checkout.")
    self_update_check.add_argument("--json", action="store_true")
    self_update_check.add_argument("--timeout", type=float, default=30.0)
    self_update_check.set_defaults(func=updates_cmds.cmd_self_update_check)
    self_update_apply = self_update_sub.add_parser("apply", help="Update the local Unlimited Skills core to the latest public release.")
    self_update_apply.add_argument("--repo", default=DEFAULT_PUBLIC_REPO, help="GitHub repo in owner/name form.")
    self_update_apply.add_argument("--install-root", default="", help="Override the detected Unlimited Skills source checkout.")
    self_update_apply.add_argument("--method", choices=["auto", "git", "archive"], default="auto", help="Use git checkout when possible, or source archive fallback.")
    self_update_apply.add_argument("--allow-dirty", action="store_true", help="Allow updating a dirty git checkout.")
    self_update_apply.add_argument("--dry-run", action="store_true", help="Show the planned update without changing files.")
    self_update_apply.add_argument("--skip-router-refresh", action="store_true", help="Do not refresh the installed Codex router SKILL.md after updating.")
    self_update_apply.add_argument("--skip-reindex", action="store_true", help="Do not rebuild the local skill index after updating.")
    self_update_apply.add_argument("--timeout", type=float, default=30.0)
    self_update_apply.set_defaults(func=updates_cmds.cmd_self_update_apply)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except RuntimeError as exc:
        print(redacted_runtime_error(exc), file=sys.stderr)
        return 2



# Backward-compatibility facade: the cmd_* implementations moved to
# unlimited_skills.commands.*, but every moved name keeps being importable
# and patchable as unlimited_skills.cli.<name>.
from .commands.accounts import (
    cmd_billing_doctor,
    cmd_billing_refresh,
    cmd_billing_status,
    cmd_enhance_download,
    cmd_enhance_run,
    cmd_org_status,
    cmd_plan_doctor,
    cmd_plan_explain,
    cmd_plan_refresh,
    cmd_plan_status,
)
from .commands.catalog import (
    _catalog_client,
    _catalog_feedback_client,
    _catalog_feedback_detail_from_args,
    _catalog_quality_client,
    _emit_catalog_browser_items,
    _maintainer_queue_client,
    _skill_improvement_client,
    cmd_catalog_browse,
    cmd_catalog_deprecation_status,
    cmd_catalog_eval_status,
    cmd_catalog_explain_risk,
    cmd_catalog_feedback,
    cmd_catalog_feedback_status,
    cmd_catalog_filters,
    cmd_catalog_fixed_pending_eval,
    cmd_catalog_improvement_status,
    cmd_catalog_install,
    cmd_catalog_known_issues,
    cmd_catalog_list,
    cmd_catalog_maintainer_queue_summary,
    cmd_catalog_maintainer_status,
    cmd_catalog_preview,
    cmd_catalog_quality,
    cmd_catalog_recommendation_preview,
    cmd_catalog_search,
    cmd_catalog_update_preview,
    cmd_catalog_update_recommendations,
)
from .commands.community import (
    _emit_community_items,
    _split_csv,
    cmd_community_install,
    cmd_community_installed,
    cmd_community_list,
    cmd_community_preview,
    cmd_community_remove,
    cmd_community_review_notes,
    cmd_community_search,
    cmd_community_submission_status,
    cmd_community_submit,
    cmd_community_withdraw,
)
from .commands.library import (
    _collection_from_repo,
    _print_import_report,
    cmd_adapt,
    cmd_adapt_next,
    cmd_adapt_one,
    cmd_apply_adaptation,
    cmd_doctor,
    cmd_draft_skill,
    cmd_feedback,
    cmd_import_dir,
    cmd_import_github,
    cmd_install_pack,
    cmd_learning_summary,
    cmd_list,
    cmd_packs,
    cmd_reindex,
    cmd_search,
    cmd_serve,
    cmd_setup,
    cmd_skills_check_effectiveness,
    cmd_support_bundle,
    cmd_sync_native,
    cmd_use,
    cmd_vector_reindex,
    cmd_view,
    cmd_where,
)
from .commands.policy import (
    cmd_policy_explain,
    cmd_policy_install,
    cmd_policy_managed_status,
    cmd_policy_remove,
    cmd_policy_status,
    cmd_policy_sync,
    cmd_policy_verify,
)
from .commands.private_packs import (
    _emit_private_pack_items,
    cmd_private_packs_access_check,
    cmd_private_packs_doctor,
    cmd_private_packs_install,
    cmd_private_packs_installed,
    cmd_private_packs_list,
    cmd_private_packs_preview,
    cmd_private_packs_remove,
    cmd_private_packs_sync,
)
from .commands.service import (
    cmd_license_status,
    cmd_register,
    cmd_service_configure,
    cmd_service_doctor,
    cmd_service_status,
    cmd_service_test_proof,
    cmd_service_test_registration,
    cmd_service_verify_trust,
    cmd_telemetry,
)
from .commands.team import (
    _confirm_or_fail,
    _reason_or_prompt,
    cmd_team_approve,
    cmd_team_collections,
    cmd_team_create,
    cmd_team_join,
    cmd_team_leave,
    cmd_team_members,
    cmd_team_mode,
    cmd_team_pending,
    cmd_team_reject,
    cmd_team_revoke,
    cmd_team_status,
    cmd_team_sync,
)
from .commands.mcp import (
    cmd_mcp_audit_report,
    cmd_mcp_bundle_keygen,
    cmd_mcp_bundle_publish,
    cmd_mcp_bundle_verify,
    cmd_mcp_gateway,
    cmd_mcp_profiles_doctor,
    cmd_mcp_profiles_replay_audit,
    cmd_mcp_profiles_rollout_plan,
    cmd_mcp_serve,
    cmd_mcp_trust_doctor,
    cmd_mcp_trust_import,
    cmd_mcp_trust_list,
    cmd_mcp_trust_revoke,
    cmd_mcp_trust_status,
)
from .commands.skillops import cmd_skillops_usage_snapshot
from .commands.updates import (
    cmd_release_pin,
    cmd_release_status,
    cmd_self_update_apply,
    cmd_self_update_check,
    cmd_updates_apply,
    cmd_updates_check,
    cmd_updates_rollback,
    refresh_codex_router_skill,
)

if __name__ == "__main__":
    raise SystemExit(main())
