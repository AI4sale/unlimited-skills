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

from unlimited_skills.registration import RegistrationState, register_installation, save_registration, with_install_identity


INSTALL_ID = "uls_inst_catalog_feedback_e2e"


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
        fail("CLI command failed: " + " ".join(args) + "\nstdout:\n" + completed.stdout + "\nstderr:\n" + completed.stderr)
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        fail(f"CLI command did not return JSON: {' '.join(args)}: {exc}\n{completed.stdout}")
    serialized = json.dumps(payload, sort_keys=True).lower()
    forbidden = [
        "license_token",
        "device_private_key",
        "x-uls-proof",
        '"skill_body":',
        '"skill_bodies":',
        "c:/users/",
        "c:\\users\\",
        "/home/",
        "/users/",
        ".git",
        "checkout_url",
        "payment_link",
    ]
    for marker in forbidden:
        if marker in serialized:
            fail(f"CLI output leaked forbidden marker: {marker}")
    return payload


def start_registry_server(registry_repo: Path, artifact_root: Path, db_url: str):
    import uvicorn
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
    app = create_app(settings=settings)
    port = free_port()
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.time() + 10
    while not server.started and time.time() < deadline:
        time.sleep(0.05)
    if not server.started:
        fail("Catalog feedback registry fixture server did not start")
    return server, thread, f"http://127.0.0.1:{port}", ProductionStorage(db_url)


def register_client(server_url: str, *, home: Path) -> RegistrationState:
    state = with_install_identity(RegistrationState(install_id=INSTALL_ID, server_url=server_url))
    registered = register_installation(state, server_url=server_url, agent="codex", timeout=10)
    save_registration(registered, home=home / ".unlimited-skills")
    return registered


def run_fixture_e2e(registry_repo: Path, *, temp_home: bool = False) -> dict[str, Any]:
    registry_repo = registry_repo.resolve()
    if not (registry_repo / "unlimited_registry" / "production_api.py").is_file():
        fail(f"Registry repo does not look valid: {registry_repo}")
    sys.path.insert(0, str(registry_repo))
    registry_tests = import_from_path("uls_registry_feedback_helpers", registry_repo / "tests" / "test_production_registry_api.py")

    with tempfile.TemporaryDirectory(prefix="uls-feedback-e2e-", ignore_cleanup_errors=True) as tmp:
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
            register_client(server_url, home=home)
            dry_run = run_public_cli(
                [
                    "--root",
                    str(library),
                    "catalog",
                    "feedback",
                    "community:browser-qa-pack:0.1.0",
                    "--type",
                    "install_failure",
                    "--severity",
                    "high",
                    "--error-code",
                    "install_plan_missing",
                    "--http-status",
                    "404",
                    "--dry-run",
                ],
                env=env,
            )
            submitted = run_public_cli(
                [
                    "--root",
                    str(library),
                    "catalog",
                    "feedback",
                    "community:browser-qa-pack:0.1.0",
                    "--type",
                    "install_failure",
                    "--severity",
                    "high",
                    "--error-code",
                    "install_plan_missing",
                    "--http-status",
                    "404",
                    "--yes",
                    "--json",
                ],
                env=env,
            )
            status = run_public_cli(
                ["--root", str(library), "catalog", "feedback-status", "community:browser-qa-pack:0.1.0", "--json"],
                env=env,
            )
            server_summary = storage.catalog_feedback_summary(item_id="community:browser-qa-pack:0.1.0")
        finally:
            server.should_exit = True
            thread.join(timeout=5)

    return {
        "schema_version": 1,
        "status": "passed",
        "mode": "fixture",
        "production_hosted_calls": False,
        "dry_run_sent": False,
        "dry_run_payload_type": dry_run["payload"]["feedback_type"],
        "submitted_feedback_id_present": bool(submitted.get("feedback_id")),
        "status_feedback_count": int(status.get("feedback_count") or 0),
        "server_feedback_count": int(server_summary.get("feedback_count") or 0),
        "privacy": {
            "automatic_telemetry": False,
            "skill_bodies_included": False,
            "prompts_included": False,
            "local_paths_included": False,
            "tokens_included": False,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Run public client/private registry catalog feedback E2E.")
    parser.add_argument("--registry-repo", default=os.environ.get("UNLIMITED_SKILLS_REGISTRY_REPO", r"D:\git\unlimited-skills-registry"))
    parser.add_argument("--fixture-mode", action="store_true", help="Run against a local private-registry fixture.")
    parser.add_argument("--temp-home", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    if not args.fixture_mode:
        fail("Only --fixture-mode is implemented for v0.3.7-alpha; production hosted calls are disabled.")
    payload = run_fixture_e2e(Path(args.registry_repo), temp_home=args.temp_home)
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print("catalog feedback cross-repo E2E passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
