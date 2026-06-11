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
