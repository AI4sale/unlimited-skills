"""Registration, telemetry, and hosted service diagnostic commands."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from unlimited_skills import cli
from unlimited_skills.registration import (
    load_registration,
    registration_path,
    redacted_status,
    register_installation,
    save_registration,
    set_telemetry,
)
from unlimited_skills.service_diagnostics import (
    configure_service,
    doctor as service_doctor,
    local_status as service_status,
    registration_dry_run,
    test_proof as service_test_proof,
    verify_trust as service_verify_trust,
)


def cmd_register(args: argparse.Namespace) -> int:
    root = Path(args.root).expanduser()
    state = load_registration()
    skill_count = sum(1 for _ in cli.iter_skills(root))
    state = register_installation(
        state,
        server_url=args.server_url,
        agent=args.agent,
        skill_count=skill_count,
        telemetry="on" if args.telemetry else "off",
        timeout=args.timeout,
    )
    path = save_registration(state)
    payload = redacted_status(state)
    payload["registration_file"] = str(path)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def cmd_license_status(args: argparse.Namespace) -> int:
    state = load_registration()
    payload = redacted_status(state)
    payload["registration_file"] = str(registration_path())
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0
    print("Registered: " + ("yes" if payload["registered"] else "no"))
    print(f"Plan: {payload['plan']}")
    print(f"Install ID: {payload['install_id'] or '(not created)'}")
    print(f"Server: {payload['server_url']}")
    print(f"Telemetry: {payload['telemetry']}")
    print("Hosted token: " + ("present" if payload["license_token"] else "missing"))
    print(f"Device key: {payload['key_thumbprint'] or '(not created)'}")
    print("Proof required: " + ("yes" if payload["proof_required"] else "no"))
    return 0


def cmd_telemetry(args: argparse.Namespace) -> int:
    state = load_registration()
    if args.telemetry_command in {"on", "off"}:
        state = set_telemetry(state, args.telemetry_command)
        save_registration(state)
    payload = redacted_status(state)
    print(json.dumps({"telemetry": payload["telemetry"], "registered": payload["registered"]}, ensure_ascii=False, indent=2))
    return 0


def cmd_service_configure(args: argparse.Namespace) -> int:
    payload = configure_service(args.url, allow_insecure_localhost=args.allow_insecure_localhost)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def cmd_service_status(args: argparse.Namespace) -> int:
    payload = service_status(refresh=args.refresh, timeout=args.timeout)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def cmd_service_doctor(args: argparse.Namespace) -> int:
    payload = service_doctor(service_url=args.url or None, timeout=args.timeout)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def cmd_service_verify_trust(args: argparse.Namespace) -> int:
    payload = service_verify_trust(service_url=args.url or None, timeout=args.timeout)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def cmd_service_test_registration(args: argparse.Namespace) -> int:
    if not args.dry_run:
        raise RuntimeError("service test-registration currently supports only --dry-run.")
    payload = registration_dry_run(service_url=args.url or None, agent=args.agent, telemetry="on" if args.telemetry else "off")
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def cmd_service_test_proof(args: argparse.Namespace) -> int:
    payload = service_test_proof(service_url=args.url or None)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0
