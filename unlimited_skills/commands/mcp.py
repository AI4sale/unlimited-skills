"""Local MCP server commands: skills server and Unlimited Tools gateway."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


def cmd_mcp_serve(args: argparse.Namespace) -> int:
    from .. import cli
    from ..mcp.server import run_skills_server

    root = Path(args.root).expanduser()
    cli.enforce_local_root(root, action="mcp serve library root")
    print(f"unlimited-skills MCP skills server: stdio, library root {root}", file=sys.stderr)
    run_skills_server(root)
    return 0


def cmd_mcp_savings(args: argparse.Namespace) -> int:
    """A1: measure the user's real standing MCP context cost vs the gateway.

    Local-only and read-only against the host config: discovers the user's
    Claude Code MCP servers, measures each server's full ``tools/list``
    payload with the repo's own stdio client, compares the summed standing
    cost against the gateway's live-measured 3 meta-tools, and appends a
    numbers-only snapshot to ``<root>/.learning/events.jsonl``. The output
    contains only server names, tool counts, byte sizes, and status strings.
    """
    import json

    from .. import cli
    from ..mcp.savings import (
        build_savings_report,
        discover_mcp_servers,
        event_snapshot,
        format_savings_text,
    )

    root = Path(args.root).expanduser()
    cli.enforce_local_root(root, action="mcp savings library root")
    claude_config = Path(args.claude_config).expanduser() if args.claude_config else None
    servers = discover_mcp_servers(claude_config)
    report = build_savings_report(servers, timeout=args.timeout)
    try:
        cli.log_event(root, "mcp_savings", event_snapshot(report))
    except OSError:
        pass  # a read-only library root must not break the measurement
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print(format_savings_text(report))
    return 0


def _install_scope(args: argparse.Namespace) -> str:
    return "global" if getattr(args, "global_scope", False) else "project"


def _require_claude_code(args: argparse.Namespace, action: str) -> bool:
    if getattr(args, "claude_code", False):
        return True
    print(
        f"mcp {action}: pass --claude-code (Claude Code is the only supported "
        "host today; the flag keeps the command explicit when more hosts land).",
        file=sys.stderr,
    )
    return False


def _log_install_event(args: argparse.Namespace, report: dict) -> None:
    """Best-effort local learning-log snapshot: status and scope only, no paths."""
    from .. import cli

    try:
        cli.log_event(
            Path(args.root).expanduser(),
            f"mcp_{report['action'].replace('-', '_')}",
            {"status": report.get("status", ""), "scope": report.get("scope", "")},
        )
    except OSError:
        pass


def cmd_mcp_install(args: argparse.Namespace) -> int:
    """A3.1: one-command Claude Code registration of the Unlimited Tools gateway.

    Writes the ``unlimited-tools`` server entry into ``./.mcp.json``
    (``--project``, the default) or the top-level ``mcpServers`` of
    ``~/.claude.json`` (``--global``) -- the same places ``mcp savings``
    reads. Backup before any write, idempotent, never touches other servers,
    refuses an unparseable config, and prints only names and paths (never
    env values). See unlimited_skills/mcp/install.py for the full contract.
    """
    import json

    from ..mcp.install import format_install_text, install_claude_code

    if not _require_claude_code(args, "install"):
        return 2
    report = install_claude_code(
        _install_scope(args),
        force=bool(getattr(args, "force", False)),
        dry_run=bool(getattr(args, "dry_run", False)),
    )
    _log_install_event(args, report)
    if getattr(args, "json", False):
        print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    elif report["status"] == "refused":
        print(format_install_text(report), file=sys.stderr)
    else:
        print(format_install_text(report))
    return int(report["exit_code"])


def cmd_mcp_uninstall(args: argparse.Namespace) -> int:
    import json

    from ..mcp.install import format_uninstall_text, uninstall_claude_code

    if not _require_claude_code(args, "uninstall"):
        return 2
    report = uninstall_claude_code(
        _install_scope(args),
        dry_run=bool(getattr(args, "dry_run", False)),
    )
    _log_install_event(args, report)
    if getattr(args, "json", False):
        print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    elif report["status"] == "refused":
        print(format_uninstall_text(report), file=sys.stderr)
    else:
        print(format_uninstall_text(report))
    return int(report["exit_code"])


def cmd_mcp_install_status(args: argparse.Namespace) -> int:
    import json

    from ..mcp.install import format_status_text, install_status

    if not _require_claude_code(args, "install-status"):
        return 2
    report = install_status()
    if getattr(args, "json", False):
        print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print(format_status_text(report))
    return int(report["exit_code"])


def cmd_mcp_audit_report(args: argparse.Namespace) -> int:
    import json

    from ..mcp import audit_inspector
    from ..mcp.audit import default_audit_path

    root = Path(args.root).expanduser()
    audit_path = Path(args.audit_log).expanduser() if args.audit_log else default_audit_path(root)
    try:
        report = audit_inspector.build_report(audit_path)
    except FileNotFoundError:
        print(
            f"Audit log not found: {audit_path} (no active file, no rotated generations). "
            "Run the gateway first, or pass --audit-log.",
            file=sys.stderr,
        )
        return 1
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print(audit_inspector.render_text(report, section=args.section))
    return 0


def _resolve_gateway_profile_state(args: argparse.Namespace):
    """Resolve the gateway's profile state from CLI flags, exactly once at
    startup (no hot reload). Returns ``(profile_state, note)``.

    Sources (docs/mcp-signed-profile-bundles.md "Local override policy"):

    - ``--profile-bundle`` alone: the verified bundle's selected profile;
    - ``--profile-bundle`` plus ``--profiles``: the narrow-only intersection
      (the local unsigned file can narrow the bundle, never widen it);
    - ``--profiles`` alone: the raw E10 path, byte-for-byte unchanged --
      unless ``--require-signed-profiles`` is set, which refuses unsigned
      profile sources fail-closed with -32015 (decision 6);
    - neither: open no-profiles mode -- unless ``--require-signed-profiles``
      is set, which is equally fail-closed (the policy demands a signed
      bundle and none is configured; no silent downgrade).
    """
    from ..mcp.bundles import require_signed_refusal, resolve_bundle_state
    from ..mcp.gateway import GatewayConfigError
    from ..mcp.profiles import FailClosedProfile, resolve_profile_state

    profiles_path = getattr(args, "profiles", "") or ""
    profile_name = getattr(args, "profile", "") or ""
    bundle_path = getattr(args, "profile_bundle", "") or ""
    trusted_keys = getattr(args, "trusted_keys", "") or ""
    audience_ids = list(getattr(args, "audience_id", None) or [])
    require_signed = bool(getattr(args, "require_signed_profiles", False))
    if bundle_path and not trusted_keys:
        # E15: when --trusted-keys is omitted but the managed trust store
        # (unlimited-skills mcp trust) has a trusted-keys file under the
        # library root, default to it. When no managed store exists, the
        # behavior is byte-for-byte unchanged (the verifier refuses with
        # -32019 bundle_key_missing, exactly as before). Verification
        # semantics are untouched -- this only resolves WHICH file is read.
        from ..mcp.trust_store import managed_trusted_keys_path

        root_value = getattr(args, "root", "") or ""
        if root_value:
            managed = managed_trusted_keys_path(Path(root_value).expanduser())
            if managed.is_file():
                trusted_keys = str(managed)
    if not bundle_path:
        if trusted_keys:
            raise GatewayConfigError(
                "--trusted-keys requires --profile-bundle (the signed bundle path); "
                "see docs/mcp-signed-profile-bundles.md."
            )
        if audience_ids:
            raise GatewayConfigError(
                "--audience-id requires --profile-bundle (the signed bundle path); "
                "see docs/mcp-signed-profile-bundles.md."
            )
    if bundle_path:
        profile = resolve_bundle_state(
            Path(bundle_path).expanduser(),
            trusted_keys_path=Path(trusted_keys).expanduser() if trusted_keys else None,
            cli_name=profile_name,
            audience_ids=audience_ids,
            local_profiles_path=Path(profiles_path).expanduser() if profiles_path else None,
        )
        if isinstance(profile, FailClosedProfile):
            note = "signed profile bundle FAIL-CLOSED (every call refused)"
        elif profiles_path:
            note = f"signed bundle profile '{profile.name}' enforced (narrowed by local file)"
        else:
            note = f"signed bundle profile '{profile.name}' enforced"
        return profile, note
    if profiles_path:
        if require_signed:
            # Decision 6 / threat 16: under the signed-required policy an
            # unsigned profile source refuses with the same -32015 as a
            # corrupted signature -- stripping gains nothing over tampering.
            return (
                require_signed_refusal(
                    "--require-signed-profiles is set but --profiles names an "
                    "unsigned profile file and no --profile-bundle is configured",
                    requested=profile_name,
                ),
                "signed-required policy FAIL-CLOSED (unsigned profile source refused)",
            )
        # The raw E10 path, unchanged by default.
        profile = resolve_profile_state(Path(profiles_path).expanduser(), cli_name=profile_name)
        if isinstance(profile, FailClosedProfile):
            note = "tool profile FAIL-CLOSED (every call refused)"
        else:
            note = f"tool profile '{profile.name}' enforced"
        return profile, note
    if require_signed:
        return (
            require_signed_refusal(
                "--require-signed-profiles is set but no --profile-bundle is configured",
                requested=profile_name,
            ),
            "signed-required policy FAIL-CLOSED (no signed bundle configured)",
        )
    if profile_name:
        raise GatewayConfigError(
            "--profile requires --profiles or --profile-bundle (a profile source); "
            "see docs/mcp-permissioned-tool-profiles.md."
        )
    return None, "no tool profiles (open mode)"


def cmd_mcp_gateway(args: argparse.Namespace) -> int:
    from ..mcp.audit import AuditLog, default_audit_path
    from ..mcp.gateway import load_gateway_config, run_gateway
    from ..mcp.profiles import FailClosedProfile

    root = Path(args.root).expanduser()
    config = load_gateway_config(Path(args.config).expanduser())
    audit_path = Path(args.audit_log).expanduser() if args.audit_log else default_audit_path(root)
    profile, profile_note = _resolve_gateway_profile_state(args)
    if isinstance(profile, FailClosedProfile):
        # Fail-closed refuse-all: the gateway still starts and serves the
        # meta-tools (hosts often swallow startup stderr), refusing every
        # call -- but an interactive start also reports the condition.
        print(f"GatewayConfigError: {profile.message}", file=sys.stderr)
    upstream_count = len(config.get("upstreams", []))
    print(
        f"unlimited-tools MCP gateway: stdio, {upstream_count} upstream(s), lazy spawn, "
        f"audit log enabled, {profile_note}",
        file=sys.stderr,
    )
    run_gateway(config, AuditLog(audit_path), profile=profile)
    return 0


# ---------------------------------------------------------------------------
# E15: managed trust store CLI (`unlimited-skills mcp trust ...`). All
# operations are OFFLINE management of the local E14 trust artifacts
# (trusted-keys file + CRL); verification semantics live in mcp/bundles.py
# and are never changed here.


def _trust_store_from_args(args: argparse.Namespace):
    from ..mcp.trust_store import TrustStore, default_store_dir

    store_dir = getattr(args, "store_dir", "") or ""
    if store_dir:
        return TrustStore(Path(store_dir).expanduser())
    return TrustStore(default_store_dir(Path(args.root).expanduser()))


def _print_report(args: argparse.Namespace, report: dict, render) -> None:
    import json

    if getattr(args, "json", False):
        print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print(render(report))


def cmd_mcp_trust_status(args: argparse.Namespace) -> int:
    from ..mcp.trust_store import format_status, status_report

    store = _trust_store_from_args(args)
    report = status_report(store, expiring_days=args.expiring_days)
    _print_report(args, report, format_status)
    return 0


def cmd_mcp_trust_list(args: argparse.Namespace) -> int:
    from ..mcp.trust_store import format_key_list, list_keys_report

    store = _trust_store_from_args(args)
    report = list_keys_report(store, expiring_days=args.expiring_days)
    _print_report(args, report, format_key_list)
    return 0


def cmd_mcp_trust_import(args: argparse.Namespace) -> int:
    import json

    from ..mcp.trust_store import TrustStoreError, import_key, load_key_file

    store = _trust_store_from_args(args)
    try:
        key_id = args.key_id or ""
        public_key = args.public_key or ""
        display = args.display or ""
        scopes = list(args.scope or [])
        not_before = args.not_before or ""
        not_after = args.not_after or ""
        comment = args.comment or ""
        if args.key_file:
            document = load_key_file(Path(args.key_file).expanduser())
            key_id = key_id or str(document.get("key_id", ""))
            public_key = public_key or str(document.get("public_key", ""))
            display = display or str(document.get("display", ""))
            if not scopes and isinstance(document.get("scopes"), list):
                scopes = [str(scope) for scope in document["scopes"]]
            not_before = not_before or str(document.get("not_before", ""))
            not_after = not_after or str(document.get("not_after", ""))
            comment = comment or str(document.get("comment", ""))
        if not key_id or not public_key:
            raise TrustStoreError(
                "import needs a key_id and a base64 PUBLIC key (inline flags or --key-file)"
            )
        result = import_key(
            store,
            key_id=key_id,
            public_key_b64=public_key,
            display=display,
            scopes=scopes,
            not_before=not_before,
            not_after=not_after,
            comment=comment,
        )
    except TrustStoreError as exc:
        print(f"trust import refused: {exc}", file=sys.stderr)
        return 1
    if getattr(args, "json", False):
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    elif result["already_present"]:
        print(
            f"key '{result['key_id']}' already trusted with the same material "
            f"(fingerprint {result['fingerprint']}); nothing changed"
        )
    else:
        print(f"imported PUBLIC key '{result['key_id']}' (fingerprint {result['fingerprint']})")
    return 0


def cmd_mcp_trust_revoke(args: argparse.Namespace) -> int:
    import json

    from ..mcp.trust_store import TrustStoreError, revoke

    store = _trust_store_from_args(args)
    try:
        result = revoke(
            store,
            key_id=args.key_id or "",
            bundle_sha256=args.bundle_sha256 or "",
            reason=args.reason or "",
        )
    except TrustStoreError as exc:
        print(f"trust revoke refused: {exc}", file=sys.stderr)
        return 1
    target = result["key_id"] or result["bundle_sha256"]
    if getattr(args, "json", False):
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    elif result["already_revoked"]:
        print(f"'{target}' is already in the local CRL; nothing changed")
    else:
        print(f"revoked '{target}' in the local CRL ({result['crl_path']})")
    return 0


def cmd_mcp_trust_doctor(args: argparse.Namespace) -> int:
    from ..mcp.trust_store import doctor_report, format_doctor

    store = _trust_store_from_args(args)
    report = doctor_report(store, expiring_days=args.expiring_days)
    _print_report(args, report, format_doctor)
    return int(report["exit_code"])


# ---------------------------------------------------------------------------
# E16: rollout simulator and policy doctor (`unlimited-skills mcp profiles
# rollout-plan|doctor`). A read-only DRY-RUN over the same artifacts the
# gateway loads at startup -- never spawns upstreams, never writes audit
# rows or store files, no network, no telemetry. The real E10/E14/E15
# loading and verification logic runs in unlimited_skills/mcp/
# profile_rollout.py; these wrappers only collect flags and print.


def _rollout_kwargs(args: argparse.Namespace) -> dict:
    return {
        "root": Path(args.root).expanduser(),
        "config_path": getattr(args, "config", "") or "",
        "profiles_path": getattr(args, "profiles", "") or "",
        "bundle_path": getattr(args, "bundle", "") or "",
        "trusted_keys_path": getattr(args, "trusted_keys", "") or "",
        "audience_ids": list(getattr(args, "audience_id", None) or []),
        "profile_name": getattr(args, "profile", "") or "",
        "tools_fixture_path": getattr(args, "tools_fixture", "") or "",
        "require_signed": bool(getattr(args, "require_signed_profiles", False)),
    }


def cmd_mcp_profiles_rollout_plan(args: argparse.Namespace) -> int:
    from ..mcp.profile_rollout import format_rollout_plan, plan_rollout

    plan = plan_rollout(**_rollout_kwargs(args))
    _print_report(args, plan, format_rollout_plan)
    return 0


def cmd_mcp_profiles_doctor(args: argparse.Namespace) -> int:
    from ..mcp.profile_rollout import doctor_rollout, format_rollout_doctor

    report = doctor_rollout(**_rollout_kwargs(args))
    _print_report(args, report, format_rollout_doctor)
    return int(report["exit_code"])


def cmd_mcp_profiles_replay_audit(args: argparse.Namespace) -> int:
    """E17: replay the historical audit log against a PROPOSED policy.

    Read-only and offline like the rest of the `mcp profiles` subgroup: no
    tool execution, no upstream spawn, no profile activation, no audit
    writes. Exit 0 for safe / safe_with_warnings, 1 for blocked or a
    missing audit log.
    """
    from ..mcp.audit import default_audit_path
    from ..mcp.audit_replay import format_replay_report, replay_audit

    root = Path(args.root).expanduser()
    audit_path = (
        Path(args.audit_log).expanduser() if args.audit_log else default_audit_path(root)
    )
    try:
        report = replay_audit(
            audit_path,
            root=root,
            config_path=getattr(args, "config", "") or "",
            profiles_path=getattr(args, "profiles", "") or "",
            bundle_path=getattr(args, "bundle", "") or "",
            trusted_keys_path=getattr(args, "trusted_keys", "") or "",
            trust_store_dir=getattr(args, "trust_store", "") or "",
            audience_ids=list(getattr(args, "audience_id", None) or []),
            profile_name=getattr(args, "profile", "") or "",
            require_signed=bool(getattr(args, "require_signed_profiles", False)),
        )
    except FileNotFoundError:
        print(
            f"Audit log not found: {audit_path} (no active file, no rotated "
            "generations). Run the gateway first, or pass --audit-log.",
            file=sys.stderr,
        )
        return 1
    _print_report(args, report, format_replay_report)
    return 1 if report["recommendation"]["status"] == "blocked" else 0
