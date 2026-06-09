from __future__ import annotations

import argparse
import importlib.util
import json
import os
import socket
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from unlimited_skills.registration import RegistrationState, register_installation, save_registration, with_install_identity


INSTALL_ID = "uls_inst_billing_e2e"


def fail(message: str) -> None:
    raise SystemExit(message)


def import_from_path(module_name: str, path: Path):
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        fail(f"Cannot load module from {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def run_public_cli(args: list[str], *, env: dict[str, str]) -> dict[str, Any]:
    completed = subprocess.run(
        [sys.executable, "-m", "unlimited_skills.cli", *args],
        cwd=Path(__file__).resolve().parents[1],
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        env=env,
        check=False,
    )
    if completed.returncode != 0:
        fail(
            "CLI command failed: "
            + " ".join(args)
            + "\nstdout:\n"
            + completed.stdout
            + "\nstderr:\n"
            + completed.stderr
        )
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        fail(f"CLI command did not return JSON: {' '.join(args)}: {exc}\n{completed.stdout}")
    if not isinstance(payload, dict):
        fail(f"CLI command returned non-object JSON: {' '.join(args)}")
    serialized = json.dumps(payload, sort_keys=True).lower()
    forbidden = [
        "license_token",
        "device_private_key",
        "x-uls-proof",
        '"checkout_url":',
        '"payment_link":',
        '"invoice_url":',
        '"card_number":',
        '"bank_account":',
        "skill.md",
    ]
    for marker in forbidden:
        if marker in serialized:
            fail(f"CLI output leaked forbidden marker: {marker}")
    return payload


def start_registry_server(registry_repo: Path, artifact_root: Path, db_url: str):
    import uvicorn
    from fastapi import HTTPException
    from unlimited_registry.orgs import resolve_entitlement_for_install
    from unlimited_registry.production_api import PUBLIC_KEYS_PATH, ProductionSettings, create_app
    from unlimited_registry.storage import ProductionStorage

    settings = ProductionSettings(
        mode="production",
        db_url=db_url,
        artifact_root=artifact_root,
        public_keys_file=(artifact_root / PUBLIC_KEYS_PATH).resolve(),
        require_device_proof=True,
        audit_log=None,
        rate_limit=1000,
    )
    storage = ProductionStorage(db_url)
    app = create_app(settings=settings)

    @app.post("/v1/hub/billing-status")
    async def billing_status(request: dict[str, Any]) -> dict[str, Any]:
        install_id = str(request.get("install_id") or "").strip()
        if not install_id:
            raise HTTPException(status_code=400, detail="install_id is required")
        with storage.connect() as conn:
            install = conn.execute("SELECT install_id FROM installations WHERE install_id = ?", (install_id,)).fetchone()
            if not install:
                raise HTTPException(status_code=401, detail="registration is required")
            entitlement = resolve_entitlement_for_install(conn, install_id)
            customer = conn.execute(
                """
                SELECT customer_id
                FROM billing_customers
                WHERE scope_type = 'install' AND scope_id = ? AND active = 1
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (install_id,),
            ).fetchone()
            subscription = None
            if customer:
                subscription = conn.execute(
                    """
                    SELECT plan, status, current_period_end, updated_at
                    FROM billing_subscriptions
                    WHERE customer_id = ?
                    ORDER BY updated_at DESC
                    LIMIT 1
                    """,
                    (customer["customer_id"],),
                ).fetchone()
        status = str(subscription["status"]) if subscription else "none"
        denial_reason = {"past_due": "past_due", "canceled": "suspended", "expired": "expired"}.get(status, "")
        denied_features = []
        if denial_reason:
            denied_features.append({"feature": "private_team_packs", "denial_reason": denial_reason})
        return {
            "schema_version": 1,
            "plan": str(subscription["plan"] if subscription else entitlement.get("plan") or "registered-community"),
            "entitlement_source": str(entitlement.get("entitlement_source") or "unknown"),
            "subscription_status": status,
            "billing_mode": "sandbox_only",
            "features_enabled": [str(item) for item in entitlement.get("features_enabled", []) if isinstance(item, str)],
            "denied_features": denied_features,
            "denial_reason": denial_reason,
            "current_period_end": str(subscription["current_period_end"]) if subscription else "",
            "last_refreshed_at": str(subscription["updated_at"]) if subscription else "",
        }

    port = free_port()
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.time() + 10
    while not server.started and time.time() < deadline:
        time.sleep(0.05)
    if not server.started:
        fail("Billing lifecycle registry fixture server did not start")
    return server, thread, f"http://127.0.0.1:{port}", storage


def register_client(server_url: str, *, install_id: str, home: Path) -> RegistrationState:
    state = with_install_identity(RegistrationState(install_id=install_id, server_url=server_url))
    registered = register_installation(state, server_url=server_url, agent="codex", timeout=10)
    save_registration(registered, home=home / ".unlimited-skills")
    return registered


def assert_active_plan(payload: dict[str, Any]) -> None:
    status = payload.get("plan_status", payload)
    if status.get("plan") != "business":
        fail(f"Expected business plan, got: {status.get('plan')}")
    if "private_team_packs" not in set(status.get("features_enabled") or []):
        fail("Expected active business entitlement to include private_team_packs")


def run_fixture_e2e(registry_repo: Path, *, temp_home: bool = False) -> dict[str, Any]:
    registry_repo = registry_repo.resolve()
    if not (registry_repo / "unlimited_registry" / "production_api.py").is_file():
        fail(f"Registry repo does not look valid: {registry_repo}")
    sys.path.insert(0, str(registry_repo))
    registry_tests = import_from_path("uls_registry_billing_helpers", registry_repo / "tests" / "test_production_registry_api.py")

    from unlimited_registry.billing_sandbox import SandboxBillingProvider

    with tempfile.TemporaryDirectory(prefix="uls-billing-e2e-", ignore_cleanup_errors=True) as tmp:
        tmp_root = Path(tmp)
        artifact_root = registry_tests.create_signed_artifact_root(tmp_root)
        home = tmp_root / "home" if temp_home else Path(os.environ.get("UNLIMITED_SKILLS_HOME", tmp_root / "home")).parent
        library = tmp_root / "library"
        env = os.environ.copy()
        env["UNLIMITED_SKILLS_HOME"] = str(home / ".unlimited-skills")
        os.environ["UNLIMITED_SKILLS_HOME"] = env["UNLIMITED_SKILLS_HOME"]

        db_url = f"sqlite:///{tmp_root / 'registry.sqlite3'}"
        server, thread, server_url, storage = start_registry_server(registry_repo, artifact_root, db_url)
        try:
            state = register_client(server_url, install_id=INSTALL_ID, home=home)
            provider = SandboxBillingProvider(storage)

            no_subscription = run_public_cli(["--root", str(library), "billing", "refresh", "--json"], env=env)
            if no_subscription["billing_status"]["subscription_status"] != "none":
                fail("Expected initial billing status to be none")

            active = provider.simulate_event(event_type="subscription_active", scope_type="install", scope_id=state.install_id, plan="business")
            active_plan = run_public_cli(["--root", str(library), "plan", "refresh", "--json"], env=env)
            assert_active_plan(active_plan)
            active_billing = run_public_cli(["--root", str(library), "billing", "refresh", "--json"], env=env)
            if active_billing["billing_status"]["subscription_status"] != "active":
                fail("Expected active billing status after sandbox subscription_active")

            failed = provider.simulate_event(
                event_type="payment_failed",
                scope_type="install",
                scope_id=state.install_id,
                plan="business",
                subscription_id=str(active["subscription"]["subscription_id"]),
            )
            past_due_billing = run_public_cli(["--root", str(library), "billing", "refresh", "--json"], env=env)
            if past_due_billing["billing_status"]["denial_reason"] != "past_due":
                fail("Expected payment_failed to normalize to past_due")
            past_due_doctor = run_public_cli(["--root", str(library), "billing", "doctor", "--json"], env=env)
            if past_due_doctor["ok"] is not False:
                fail("Expected billing doctor to report attention for past_due")
            still_business = run_public_cli(["--root", str(library), "plan", "refresh", "--json"], env=env)
            assert_active_plan(still_business)

            canceled = provider.simulate_event(
                event_type="subscription_canceled",
                scope_type="install",
                scope_id=state.install_id,
                plan="business",
                subscription_id=str(failed["subscription"]["subscription_id"]),
            )
            canceled_billing = run_public_cli(["--root", str(library), "billing", "refresh", "--json"], env=env)
            if canceled_billing["billing_status"]["denial_reason"] != "suspended":
                fail("Expected subscription_canceled to normalize to suspended")

            return {
                "schema_version": 1,
                "status": "passed",
                "mode": "fixture",
                "server_url": server_url,
                "registry_repo": str(registry_repo),
                "initial_status_none": True,
                "subscription_active": active["subscription"]["status"],
                "payment_failed_status": failed["subscription"]["status"],
                "canceled_status": canceled["subscription"]["status"],
                "billing_active_cli": active_billing["billing_status"]["subscription_status"],
                "billing_past_due_cli": past_due_billing["billing_status"]["denial_reason"],
                "billing_suspended_cli": canceled_billing["billing_status"]["denial_reason"],
                "entitlement_reconciled_to_business": True,
                "payment_failed_preserved_business_entitlement": True,
                "production_hosted_calls": False,
            }
        finally:
            server.should_exit = True
            thread.join(timeout=5)


def is_local_registry_url(url: str) -> bool:
    parsed = urlparse(url)
    return parsed.scheme in {"http", "https"} and parsed.hostname in {"127.0.0.1", "localhost", "::1"}


def run_external_local_e2e(registry_url: str, *, temp_home: bool = False) -> dict[str, Any]:
    if not is_local_registry_url(registry_url):
        fail("--registry-url must point to localhost/127.0.0.1/::1; production hosted calls are blocked")
    with tempfile.TemporaryDirectory(prefix="uls-billing-local-registry-", ignore_cleanup_errors=True) as tmp:
        tmp_root = Path(tmp)
        home = tmp_root / "home" if temp_home else Path(os.environ.get("UNLIMITED_SKILLS_HOME", tmp_root / "home")).parent
        library = tmp_root / "library"
        env = os.environ.copy()
        env["UNLIMITED_SKILLS_HOME"] = str(home / ".unlimited-skills")
        os.environ["UNLIMITED_SKILLS_HOME"] = env["UNLIMITED_SKILLS_HOME"]
        register_client(registry_url.rstrip("/"), install_id=INSTALL_ID, home=home)
        plan = run_public_cli(["--root", str(library), "plan", "refresh", "--json"], env=env)
        billing = run_public_cli(["--root", str(library), "billing", "refresh", "--json"], env=env)
        return {
            "schema_version": 1,
            "status": "passed",
            "mode": "external-local",
            "registry_url": registry_url,
            "plan": plan["plan_status"]["plan"],
            "billing_subscription_status": billing["billing_status"]["subscription_status"],
            "production_hosted_calls": False,
        }


def main() -> int:
    parser = argparse.ArgumentParser(description="Run billing lifecycle cross-repo E2E against the private registry checkout or a local registry URL.")
    parser.add_argument("--registry-repo", default=os.environ.get("UNLIMITED_SKILLS_REGISTRY_REPO", r"D:\git\unlimited-skills-registry"))
    parser.add_argument("--registry-url", default="", help="Optional already-running local registry URL. Must be localhost/127.0.0.1/::1.")
    parser.add_argument("--fixture-mode", action="store_true", help="Run against the private registry fixture and never call production hosted services.")
    parser.add_argument("--temp-home", action="store_true", help="Use an isolated temporary Unlimited Skills home.")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    if args.registry_url and args.fixture_mode:
        raise SystemExit("--registry-url and --fixture-mode are mutually exclusive")
    if args.registry_url:
        payload = run_external_local_e2e(args.registry_url, temp_home=args.temp_home)
    else:
        payload = run_fixture_e2e(Path(args.registry_repo), temp_home=args.temp_home)
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print("billing lifecycle cross-repo E2E passed")
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
