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


def cmd_mcp_gateway(args: argparse.Namespace) -> int:
    from ..mcp.audit import AuditLog, default_audit_path
    from ..mcp.gateway import load_gateway_config, run_gateway
    from ..mcp.index_cache import CACHE_FILE_NAME, IndexCache, default_index_cache_path
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
    # Warm tool-index cache: strictly opt-in (docs/mcp-performance.md
    # candidate 1). args.index_cache is None when the flag is absent --
    # default OFF, behavior byte-for-byte unchanged.
    index_cache = None
    cache_note = ""
    index_cache_arg = getattr(args, "index_cache", None)
    if index_cache_arg is not None:
        if str(index_cache_arg).strip():
            cache_path = Path(index_cache_arg).expanduser() / CACHE_FILE_NAME
        else:
            cache_path = default_index_cache_path(root)
        index_cache = IndexCache(cache_path)
        index_cache.load()
        cache_note = ", index cache enabled"
    upstream_count = len(config.get("upstreams", []))
    print(
        f"unlimited-tools MCP gateway: stdio, {upstream_count} upstream(s), lazy spawn, "
        f"audit log enabled, {profile_note}{cache_note}",
        file=sys.stderr,
    )
    run_gateway(config, AuditLog(audit_path), profile=profile, index_cache=index_cache)
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
# E19: local bundle publisher and signing ceremony (`unlimited-skills mcp
# bundle keygen|publish|verify`). DEV/FIXTURE keys only -- production
# signing keys are never generated or handled; everything is offline (no
# network, no registry sync, no hosted calls). Verification is the REAL
# E14 path (resolve_bundle_state), reused by the verify step and by the
# automatic post-package self-check inside publish. Key material is never
# printed: paths, fingerprints, and hashes only.


def cmd_mcp_bundle_keygen(args: argparse.Namespace) -> int:
    import json

    from ..mcp.bundle_publisher import PublisherError, format_keygen, generate_keypair

    try:
        result = generate_keypair(
            Path(args.out).expanduser(),
            key_id=args.key_id or "dev-signing-key",
            display=args.display or "",
            force=bool(getattr(args, "force", False)),
        )
    except PublisherError as exc:
        print(f"bundle keygen refused: {exc}", file=sys.stderr)
        return 1
    if getattr(args, "json", False):
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print(format_keygen(result))
    return 0


def cmd_mcp_bundle_publish(args: argparse.Namespace) -> int:
    import json

    from ..mcp.bundle_publisher import PublisherError, format_publish, publish_bundle

    try:
        result = publish_bundle(
            Path(args.profiles).expanduser(),
            Path(args.signing_key).expanduser(),
            issuer_key_id=args.issuer_key_id or "",
            audience=list(getattr(args, "audience", None) or []),
            expires_days=args.expires_days,
            namespaces=list(getattr(args, "namespaces", None) or []),
            out_dir=args.out or ".",
            name=args.name or "",
            display=args.display or "",
            previous=args.previous or "",
            crl_path=args.crl_path or "",
            dry_run=bool(getattr(args, "dry_run", False)),
            force=bool(getattr(args, "force", False)),
        )
    except PublisherError as exc:
        print(f"bundle publish refused: {exc}", file=sys.stderr)
        return 1
    if getattr(args, "json", False):
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print(format_publish(result))
    return 0


def cmd_mcp_bundle_verify(args: argparse.Namespace) -> int:
    import json

    from ..mcp.bundle_publisher import format_verify, verify_report

    report = verify_report(
        Path(args.bundle).expanduser(),
        Path(args.trusted_keys).expanduser(),
        audience_ids=list(getattr(args, "audience_id", None) or []),
    )
    if getattr(args, "json", False):
        print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print(format_verify(report))
    return 0 if report["ok"] else 1


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


# ---------------------------------------------------------------------------
# E20: local bundle library and activation manager (`unlimited-skills mcp
# profiles library ...`). A LOCAL library of signed profile bundles --
# install, list, status, pin/unpin, activate/deactivate, rollback. No
# registry sync, no hosted calls, no production signing keys. Verification
# is the REAL E14 path (resolve_bundle_state via the E19 verify wrapper),
# run at add time AND re-run at activation/rollback/doctor time; semantics
# are never changed or bypassed here. The gateway reads the activation
# pointer (<library>/active.bundle.json) once at startup -- no hot reload.


def _bundle_library_from_args(args: argparse.Namespace):
    from ..mcp.bundle_library import BundleLibrary, default_library_dir

    library_dir = getattr(args, "library_dir", "") or ""
    if library_dir:
        return BundleLibrary(Path(library_dir).expanduser())
    return BundleLibrary(default_library_dir(Path(args.root).expanduser()))


def _library_trusted_keys(args: argparse.Namespace) -> str:
    """Explicit --trusted-keys wins; else the E15 managed store's file under
    the library root when it exists; else '' (verification refuses with
    -32019 bundle_key_missing -- never a silent pass)."""
    trusted = getattr(args, "trusted_keys", "") or ""
    if trusted:
        return str(Path(trusted).expanduser())
    from ..mcp.trust_store import managed_trusted_keys_path

    managed = managed_trusted_keys_path(Path(args.root).expanduser())
    return str(managed) if managed.is_file() else ""


def _library_common(args: argparse.Namespace) -> dict:
    return {
        "trusted_keys_path": _library_trusted_keys(args),
        "audience_ids": list(getattr(args, "audience_id", None) or []),
    }


def _print_library_result(args: argparse.Namespace, result: dict, text: str) -> None:
    import json

    if getattr(args, "json", False):
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print(text)


def cmd_mcp_library_status(args: argparse.Namespace) -> int:
    from ..mcp.bundle_library import format_status, status_report

    report = status_report(_bundle_library_from_args(args), **_library_common(args))
    _print_report(args, report, format_status)
    return 0


def cmd_mcp_library_list(args: argparse.Namespace) -> int:
    from ..mcp.bundle_library import format_list, list_report

    report = list_report(_bundle_library_from_args(args), **_library_common(args))
    _print_report(args, report, format_list)
    return 0


def cmd_mcp_library_add(args: argparse.Namespace) -> int:
    from ..mcp.bundle_library import BundleLibraryError, add_bundle

    try:
        result = add_bundle(
            _bundle_library_from_args(args),
            Path(args.file).expanduser(),
            name=getattr(args, "name", "") or "",
            **_library_common(args),
        )
    except BundleLibraryError as exc:
        print(f"bundle library refused: {exc}", file=sys.stderr)
        return 1
    if result["already_present"]:
        text = (
            f"bundle {result['sha256'][:12]} ({result['name']}) is already installed; "
            "nothing changed"
        )
    else:
        text = (
            f"added bundle {result['sha256'][:12]} ({result['name']}) as {result['file']} "
            "(verified through the real E14 path at add time)"
        )
    _print_library_result(args, result, text)
    return 0


def cmd_mcp_library_inspect(args: argparse.Namespace) -> int:
    from ..mcp.bundle_library import BundleLibraryError, format_inspect, inspect_report

    try:
        report = inspect_report(
            _bundle_library_from_args(args), args.ref, **_library_common(args)
        )
    except BundleLibraryError as exc:
        print(f"bundle library refused: {exc}", file=sys.stderr)
        return 1
    _print_report(args, report, format_inspect)
    return 0


def cmd_mcp_library_activate(args: argparse.Namespace) -> int:
    from ..mcp.bundle_library import BundleLibraryError, activate_bundle

    try:
        result = activate_bundle(
            _bundle_library_from_args(args), args.ref, **_library_common(args)
        )
    except BundleLibraryError as exc:
        print(f"bundle library refused: {exc}", file=sys.stderr)
        return 1
    text = (
        f"activated bundle {result['sha256'][:12]} ({result['name']}); {result['note']}"
    )
    _print_library_result(args, result, text)
    return 0


def cmd_mcp_library_deactivate(args: argparse.Namespace) -> int:
    from ..mcp.bundle_library import BundleLibraryError, deactivate_bundle

    try:
        result = deactivate_bundle(_bundle_library_from_args(args))
    except BundleLibraryError as exc:
        print(f"bundle library refused: {exc}", file=sys.stderr)
        return 1
    if result["already_inactive"]:
        text = "no bundle is active; nothing changed"
    else:
        text = f"deactivated bundle {result['sha256'][:12]}; {result['note']}"
    _print_library_result(args, result, text)
    return 0


def cmd_mcp_library_rollback(args: argparse.Namespace) -> int:
    from ..mcp.bundle_library import BundleLibraryError, rollback_bundle

    try:
        result = rollback_bundle(_bundle_library_from_args(args), **_library_common(args))
    except BundleLibraryError as exc:
        print(f"bundle library refused: {exc}", file=sys.stderr)
        return 1
    lines = [
        f"rolled back to bundle {result['sha256'][:12]} ({result['name']}); {result['note']}"
    ]
    for item in result["skipped"]:
        lines.append(
            f"  skipped {item['sha256'][:12]} ({item['name'] or '?'}): {item['refusal']}"
            + (f" ({item['code']})" if item["code"] else "")
        )
    _print_library_result(args, result, "\n".join(lines))
    return 0


def cmd_mcp_library_pin(args: argparse.Namespace) -> int:
    from ..mcp.bundle_library import BundleLibraryError, set_pinned

    pinned = args.library_command == "pin"
    try:
        result = set_pinned(_bundle_library_from_args(args), args.ref, pinned)
    except BundleLibraryError as exc:
        print(f"bundle library refused: {exc}", file=sys.stderr)
        return 1
    verb = "pinned" if pinned else "unpinned"
    if result["changed"]:
        text = f"{verb} bundle {result['sha256'][:12]} ({result['name']})"
    else:
        text = f"bundle {result['sha256'][:12]} ({result['name']}) was already {verb}; nothing changed"
    _print_library_result(args, result, text)
    return 0


def cmd_mcp_library_remove(args: argparse.Namespace) -> int:
    from ..mcp.bundle_library import BundleLibraryError, remove_bundle

    try:
        result = remove_bundle(
            _bundle_library_from_args(args), args.ref, force=bool(getattr(args, "force", False))
        )
    except BundleLibraryError as exc:
        print(f"bundle library refused: {exc}", file=sys.stderr)
        return 1
    text = f"removed bundle {result['sha256'][:12]} ({result['name']})"
    if result["deactivated"]:
        text += " (it was ACTIVE and was deactivated first; open-mode note: a gateway restarted without --profile-bundle runs unenforced)"
    _print_library_result(args, result, text)
    return 0


def cmd_mcp_library_doctor(args: argparse.Namespace) -> int:
    from ..mcp.bundle_library import doctor_report, format_doctor

    report = doctor_report(_bundle_library_from_args(args), **_library_common(args))
    _print_report(args, report, format_doctor)
    return int(report["exit_code"])


# ---------------------------------------------------------------------------
# E27: managed profile sync client PROTOTYPE (`unlimited-skills mcp profiles
# managed sync|status|last-good|doctor`). Fixture-ONLY: the source is a local
# directory in the E26 fixture-registry layout; anything URL-shaped refuses
# (hosted sync is not implemented; design gated behind E23/E24). Offline by
# construction -- no network, no hosted calls, no telemetry, no production
# keys. DEFAULT IS DRY-RUN; --apply stages into the E20 library but NEVER
# activates (activation stays the explicit `library activate` step).
# Verification is the REAL E14 path; routing files verify against the E15
# trust store; refusals reuse the E26 reason names and the reserved codes
# -32014..-32019 -- no new numeric codes.


def _managed_crl_path(args: argparse.Namespace) -> str:
    """The member's local CRL for ROUTING-document checks: the E15 managed
    store's crl.json under the library root when it exists, else none."""
    from ..mcp.trust_store import TrustStore, default_store_dir

    store = TrustStore(default_store_dir(Path(args.root).expanduser()))
    return str(store.crl_path) if store.crl_path.is_file() else ""


def cmd_mcp_managed_sync(args: argparse.Namespace) -> int:
    from ..mcp.managed_sync import (
        DistributionRefusal,
        format_sync,
        sync_managed_profile,
    )

    try:
        report = sync_managed_profile(
            _bundle_library_from_args(args),
            args.source,
            crl_path=_managed_crl_path(args),
            apply=bool(getattr(args, "apply", False)),
            **_library_common(args),
        )
    except DistributionRefusal as exc:
        code = f" ({exc.code})" if exc.code else ""
        print(f"managed sync refused [{exc.reason}{code}]: {exc}", file=sys.stderr)
        return 1
    _print_report(args, report, format_sync)
    return 0


def cmd_mcp_managed_status(args: argparse.Namespace) -> int:
    from ..mcp.managed_sync import format_managed_status, managed_status_report

    report = managed_status_report(_bundle_library_from_args(args), **_library_common(args))
    _print_report(args, report, format_managed_status)
    return 0


def cmd_mcp_managed_last_good(args: argparse.Namespace) -> int:
    from ..mcp.managed_sync import (
        DistributionRefusal,
        format_last_good,
        last_good_report,
    )

    try:
        report = last_good_report(
            _bundle_library_from_args(args),
            restore=bool(getattr(args, "restore", False)),
            source=getattr(args, "source", "") or "",
            **_library_common(args),
        )
    except DistributionRefusal as exc:
        code = f" ({exc.code})" if exc.code else ""
        print(f"managed last-good refused [{exc.reason}{code}]: {exc}", file=sys.stderr)
        return 1
    _print_report(args, report, format_last_good)
    return int(report["exit_code"])


def cmd_mcp_managed_doctor(args: argparse.Namespace) -> int:
    from ..mcp.managed_sync import (
        DistributionRefusal,
        format_managed_doctor,
        managed_doctor_report,
    )

    try:
        report = managed_doctor_report(
            _bundle_library_from_args(args),
            source=getattr(args, "source", "") or "",
            **_library_common(args),
        )
    except DistributionRefusal as exc:
        print(f"managed doctor refused [{exc.reason}]: {exc}", file=sys.stderr)
        return 1
    _print_report(args, report, format_managed_doctor)
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
