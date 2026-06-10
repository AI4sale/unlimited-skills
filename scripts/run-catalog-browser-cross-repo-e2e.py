from __future__ import annotations

import argparse
import contextlib
import importlib.util
import io
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
from unittest.mock import patch

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from unlimited_skills.cli import main as cli_main
from unlimited_skills.registration import RegistrationState, base64_urlsafe_encode, register_installation, save_registration, with_install_identity
from unlimited_skills.signatures import sign_manifest_for_tests


ROOT = Path(__file__).resolve().parents[1]
INSTALL_ID = "uls_inst_catalog_browser_e2e"
FAKE_SERVER_URL = "https://catalog-browser-fixture.example.test"


class FakeResponse:
    def __init__(self, payload: dict[str, Any]) -> None:
        self._stream = io.BytesIO(json.dumps(payload).encode("utf-8"))

    def __enter__(self) -> "FakeResponse":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None

    def read(self, size: int = -1) -> bytes:
        return self._stream.read(size)


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


def catalog_item(pack_id: str = "browser-qa-pack", *, status: str = "published", agent: str = "codex", category: str = "qa", installable: bool = True) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "item_id": f"community:{pack_id}:0.1.0",
        "pack_id": pack_id,
        "collection": "community",
        "version": "0.1.0",
        "channel": "canary",
        "source": "community",
        "skill_kind": "skill-pack",
        "categories": [category],
        "compatible_agents": [agent],
        "plan_requirement": "registered-community",
        "review_status": status,
        "deprecated": status == "deprecated",
        "retired": status == "retired",
        "installable": installable,
        "requires_registration": True,
        "description": f"{pack_id} reviewed metadata",
        "license": "MIT",
        "source_repo": "https://github.com/example/community-skills",
        "skill_count": 2,
        "requirements": ["registered community catalog"],
        "distribution_policy": {
            "signed_metadata_required": True,
            "approved_or_published_required": True,
            "skill_execution": False,
            "body_included": False,
        },
        "warnings": ["deprecated"] if status == "deprecated" else [],
        "body_included": False,
    }


def signed_payload(payload: dict[str, Any], private_key: Ed25519PrivateKey, *, manifest_type: str = "catalog-browser-response") -> dict[str, Any]:
    return sign_manifest_for_tests({"schema_version": 1, "manifest_type": manifest_type, **payload}, private_key, key_id="catalog-browser-e2e-key")


def set_fixture_env(home: Path, public_key: str) -> dict[str, str | None]:
    previous = {
        "UNLIMITED_SKILLS_HOME": os.environ.get("UNLIMITED_SKILLS_HOME"),
        "UNLIMITED_SKILLS_MANIFEST_PUBLIC_KEYS": os.environ.get("UNLIMITED_SKILLS_MANIFEST_PUBLIC_KEYS"),
    }
    os.environ["UNLIMITED_SKILLS_HOME"] = str(home / ".unlimited-skills")
    os.environ["UNLIMITED_SKILLS_MANIFEST_PUBLIC_KEYS"] = f"catalog-browser-e2e-key:{public_key}"
    return previous


def restore_env(previous: dict[str, str | None]) -> None:
    for key, value in previous.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value


def save_fixture_registration(home: Path, server_url: str = FAKE_SERVER_URL) -> None:
    state = with_install_identity(RegistrationState(install_id=INSTALL_ID, server_url=server_url, license_token="tok_catalog_browser_fixture"))
    save_registration(state, home=home / ".unlimited-skills")


def assert_payload_safe(payload: Any) -> None:
    serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True).lower()
    forbidden = [
        "device_private_key",
        "license_token",
        "x-uls-proof",
        "authorization",
        "private key",
        '"skill_body":',
        '"skill_bodies":',
        "c:/users/",
        "d:/git/",
        "maintainer notes",
        "archive_url",
    ]
    for marker in forbidden:
        if marker in serialized:
            fail(f"Catalog browser E2E leaked forbidden marker: {marker}")


def run_cli_in_process(args: list[str]) -> dict[str, Any]:
    stdout = io.StringIO()
    stderr = io.StringIO()
    with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
        code = cli_main(args)
    if code != 0:
        fail(f"CLI command failed ({code}): {' '.join(args)}\nstdout:\n{stdout.getvalue()}\nstderr:\n{stderr.getvalue()}")
    try:
        payload = json.loads(stdout.getvalue())
    except json.JSONDecodeError as exc:
        fail(f"CLI command did not return JSON: {' '.join(args)}: {exc}\n{stdout.getvalue()}")
    assert_payload_safe(payload)
    return payload


def run_public_fixture_e2e(*, temp_home: bool = False) -> dict[str, Any]:
    private_key = Ed25519PrivateKey.generate()
    public_key = base64_urlsafe_encode(private_key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw))
    seen_paths: list[str] = []
    with tempfile.TemporaryDirectory(prefix="uls-catalog-browser-fixture-", ignore_cleanup_errors=True) as tmp:
        tmp_root = Path(tmp)
        home = tmp_root / "home" if temp_home else Path(os.environ.get("UNLIMITED_SKILLS_HOME", tmp_root / "home")).parent
        library = tmp_root / "library"
        save_fixture_registration(home)
        previous = set_fixture_env(home, public_key)

        def fake_urlopen(request, timeout=30.0):
            url = request.full_url if hasattr(request, "full_url") else str(request)
            parsed = urlparse(url)
            if parsed.hostname != "catalog-browser-fixture.example.test":
                fail(f"Fixture attempted non-fixture network call: {url}")
            body = json.loads((request.data or b"{}").decode("utf-8"))
            assert_payload_safe(body)
            seen_paths.append(parsed.path)
            if parsed.path == "/v1/catalog/browser/list":
                return FakeResponse(
                    signed_payload(
                        {
                            "items": [
                                catalog_item("browser-qa-pack", status="published"),
                                catalog_item("pending-pack", status="pending_review", installable=False),
                            ]
                        },
                        private_key,
                    )
                )
            if parsed.path == "/v1/catalog/browser/search":
                return FakeResponse(signed_payload({"items": [catalog_item("browser-qa-pack", status="published")]}, private_key))
            if parsed.path == "/v1/catalog/browser/filters":
                return FakeResponse(
                    signed_payload(
                        {
                            "filters": {
                                "channels": ["canary"],
                                "sources": ["community"],
                                "compatible_agents": ["codex"],
                                "skill_kinds": ["skill-pack"],
                                "categories": ["qa"],
                                "plan_requirements": ["registered-community"],
                                "review_statuses": ["published"],
                            },
                            "privacy": {"metadata_only": True, "skill_bodies_included": False},
                        },
                        private_key,
                        manifest_type="catalog-browser-filters",
                    )
                )
            if parsed.path == "/v1/catalog/browser/preview":
                item = catalog_item("browser-qa-pack", status="published")
                item["preview"] = {"description": item["description"], "requirements": item["requirements"], "body_included": False}
                return FakeResponse(signed_payload({"item": item}, private_key, manifest_type="catalog-browser-preview"))
            if parsed.path == "/v1/catalog/browser/item":
                return FakeResponse(signed_payload({"item": catalog_item("browser-qa-pack", status="published")}, private_key, manifest_type="catalog-browser-item"))
            fail(f"Unexpected fixture endpoint: {parsed.path}")

        try:
            with patch("urllib.request.urlopen", fake_urlopen):
                browse = run_cli_in_process(["--root", str(library), "catalog", "browse", "--source", "community", "--compatible-agent", "codex", "--json"])
                search = run_cli_in_process(["--root", str(library), "catalog", "search", "browser qa", "--source", "community", "--json"])
                filters = run_cli_in_process(["--root", str(library), "catalog", "filters"])
                preview = run_cli_in_process(["--root", str(library), "catalog", "preview", "community:browser-qa-pack:0.1.0", "--json"])
                install = run_cli_in_process(["--root", str(library), "catalog", "install", "community:browser-qa-pack:0.1.0", "--dry-run", "--json"])
        finally:
            restore_env(previous)
    if [item["pack_id"] for item in browse["items"]] != ["browser-qa-pack"]:
        fail("Fixture browse did not hide unapproved catalog items")
    if search["items"][0]["pack_id"] != "browser-qa-pack":
        fail("Fixture search did not return expected approved item")
    if "community" not in filters["filters"]["sources"]:
        fail("Fixture filters did not expose expected source")
    if preview["item"]["preview"]["body_included"] is not False:
        fail("Fixture preview included a skill body")
    if install["dry_run"] is not True or install["installable"] is not True:
        fail("Fixture dry-run install did not verify signed installable metadata")
    return {
        "schema_version": 1,
        "status": "passed",
        "mode": "public-fixture",
        "private_registry_checkout_required": False,
        "approved_only_visibility": True,
        "signed_metadata_verified": True,
        "metadata_only_preview": True,
        "dry_run_install_verified": True,
        "endpoints": sorted(set(seen_paths)),
        "production_hosted_calls": False,
    }


def insert_registry_submission(storage: Any, *, status: str, pack_id: str, agent: str = "codex", category: str = "qa") -> None:
    now = "2026-06-10T00:00:00Z"
    metadata = {
        "description": f"{pack_id} reviewed metadata",
        "license": "MIT",
        "source_repo": "https://github.com/example/community-skills",
        "compatible_agents": [agent],
        "categories": [category],
        "requirements": ["registered community catalog"],
        "skill_kind": "skill-pack",
        "skill_count": 2,
    }
    validation = {"schema_version": 1, "status": "accepted", "accepted": True, "issues": [], "warnings": [], "metadata": metadata}
    with storage.connect() as conn:
        conn.execute(
            """
            INSERT INTO community_submissions (
              submission_id, pack_id, collection, version, channel, status,
              source_path, metadata_json, validation_json, review_notes,
              reviewer, created_at, updated_at, published_artifact_path
            )
            VALUES (?, ?, 'community', '0.1.0', 'canary', ?, 'C:/Users/alice/private-skill',
                    ?, ?, 'maintainer notes stay private', 'maintainer', ?, ?, ?)
            """,
            (
                f"sub_{pack_id}",
                pack_id,
                status,
                json.dumps(metadata, sort_keys=True),
                json.dumps(validation, sort_keys=True),
                now,
                now,
                f"registry/generated/community/canary/sub_{pack_id}.json" if status in {"published", "approved"} else "",
            ),
        )


def start_local_registry(registry_repo: Path, artifact_root: Path, db_url: str):
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
    storage = ProductionStorage(db_url)
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
        fail("Catalog browser registry fixture server did not start")
    return server, thread, f"http://127.0.0.1:{port}", storage


def run_public_cli_subprocess(args: list[str], *, env: dict[str, str]) -> dict[str, Any]:
    completed = subprocess.run(
        [sys.executable, "-m", "unlimited_skills.cli", *args],
        cwd=ROOT,
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
    assert_payload_safe(payload)
    return payload


def public_key_env_from_artifact_root(artifact_root: Path) -> str:
    payload = json.loads((artifact_root / "registry" / "generated" / "public-keys" / "manifest-public-keys.v1.json").read_text(encoding="utf-8"))
    keys = [item for item in payload.get("keys", []) if isinstance(item, dict) and item.get("algorithm") == "ed25519"]
    if not keys:
        fail("Registry fixture did not publish an Ed25519 public key")
    key = keys[0]
    return f"{key['key_id']}:{key['public_key']}"


def run_local_registry_e2e(registry_repo: Path, *, temp_home: bool = False) -> dict[str, Any]:
    registry_repo = registry_repo.resolve()
    if not (registry_repo / "unlimited_registry" / "production_api.py").is_file():
        fail(f"Registry repo does not look valid: {registry_repo}")
    sys.path.insert(0, str(registry_repo))
    registry_tests = import_from_path("uls_registry_catalog_browser_helpers", registry_repo / "tests" / "test_production_registry_api.py")

    with tempfile.TemporaryDirectory(prefix="uls-catalog-browser-registry-", ignore_cleanup_errors=True) as tmp:
        tmp_root = Path(tmp)
        artifact_root = registry_tests.create_signed_artifact_root(tmp_root)
        home = tmp_root / "home" if temp_home else Path(os.environ.get("UNLIMITED_SKILLS_HOME", tmp_root / "home")).parent
        library = tmp_root / "library"
        db_url = f"sqlite:///{tmp_root / 'registry.sqlite3'}"
        server, thread, server_url, storage = start_local_registry(registry_repo, artifact_root, db_url)
        try:
            insert_registry_submission(storage, status="published", pack_id="browser-qa-pack", agent="codex", category="qa")
            insert_registry_submission(storage, status="pending_review", pack_id="pending-pack", agent="codex", category="qa")
            env = os.environ.copy()
            env["UNLIMITED_SKILLS_HOME"] = str(home / ".unlimited-skills")
            env["UNLIMITED_SKILLS_MANIFEST_PUBLIC_KEYS"] = public_key_env_from_artifact_root(artifact_root)
            registered = register_installation(
                with_install_identity(RegistrationState(install_id=INSTALL_ID, server_url=server_url)),
                server_url=server_url,
                agent="codex",
                timeout=10,
            )
            save_registration(registered, home=home / ".unlimited-skills")
            browse = run_public_cli_subprocess(["--root", str(library), "catalog", "browse", "--source", "community", "--channel", "canary", "--json"], env=env)
            search = run_public_cli_subprocess(["--root", str(library), "catalog", "search", "browser", "--source", "community", "--channel", "canary", "--json"], env=env)
            filters = run_public_cli_subprocess(["--root", str(library), "catalog", "filters", "--channel", "canary"], env=env)
            preview = run_public_cli_subprocess(["--root", str(library), "catalog", "preview", "community:browser-qa-pack:0.1.0", "--json"], env=env)
            install = run_public_cli_subprocess(["--root", str(library), "catalog", "install", "community:browser-qa-pack:0.1.0", "--dry-run", "--json"], env=env)
        finally:
            server.should_exit = True
            thread.join(timeout=5)
    if [item["pack_id"] for item in browse["items"]] != ["browser-qa-pack"]:
        fail("Local registry browse did not hide pending catalog item")
    if search["items"][0]["pack_id"] != "browser-qa-pack":
        fail("Local registry search did not return expected catalog item")
    if "community" not in filters["filters"]["sources"]:
        fail("Local registry filters did not return community source")
    if preview["item"]["preview"]["body_included"] is not False:
        fail("Local registry preview included skill body")
    if install["dry_run"] is not True or install["installable"] is not True:
        fail("Local registry dry-run install did not verify signed metadata")
    return {
        "schema_version": 1,
        "status": "passed",
        "mode": "local-registry",
        "registry_repo": str(registry_repo),
        "server_url": server_url,
        "approved_only_visibility": True,
        "signed_metadata_verified": True,
        "metadata_only_preview": True,
        "dry_run_install_verified": True,
        "production_hosted_calls": False,
    }


def is_local_registry_url(url: str) -> bool:
    parsed = urlparse(url)
    return parsed.scheme in {"http", "https"} and parsed.hostname in {"127.0.0.1", "localhost", "::1"}


def main() -> int:
    parser = argparse.ArgumentParser(description="Run catalog browser E2E against public fixtures or a local private registry checkout.")
    parser.add_argument("--registry-repo", default=os.environ.get("UNLIMITED_SKILLS_REGISTRY_REPO", r"D:\git\unlimited-skills-registry"))
    parser.add_argument("--registry-url", default="", help="Reserved for an already-running local registry URL. Must be localhost/127.0.0.1/::1.")
    parser.add_argument("--fixture-mode", action="store_true", help="Run a public-only signed metadata fixture without private registry checkout.")
    parser.add_argument("--local-registry", action="store_true", help="Run against the private registry checkout started on localhost.")
    parser.add_argument("--temp-home", action="store_true", help="Use an isolated temporary Unlimited Skills home.")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    if args.registry_url:
        if not is_local_registry_url(args.registry_url):
            fail("--registry-url must point to localhost/127.0.0.1/::1; production hosted calls are blocked")
        fail("--registry-url mode is reserved for future prepared local registries; use --fixture-mode or --local-registry")
    if args.fixture_mode or not args.local_registry:
        payload = run_public_fixture_e2e(temp_home=args.temp_home)
    else:
        payload = run_local_registry_e2e(Path(args.registry_repo), temp_home=args.temp_home)
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print("catalog browser cross-repo E2E passed")
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
