from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from unlimited_skills.hub_allowlist import allowlist_sha256
from unlimited_skills.registration import (
    base64_urlsafe_decode,
    base64_urlsafe_encode,
    proof_headers,
    redact_sensitive_text,
    state_from_json,
)
from unlimited_skills.signatures import sign_manifest_for_tests


PRODUCTION_HOSTS = {"unlimited.ai4.sale", "api.github.com", "github.com"}
KEY_ID = "production-contract-e2e-key"
TOKEN = "uls_prod_contract_e2e_token"


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def write_skill_pack(path: Path) -> bytes:
    content = "---\nname: production-fixture-skill\ndescription: Production registry contract fixture.\n---\n\n# production-fixture-skill\n"
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("production-fixture-pack/skills/production-fixture-skill/SKILL.md", content)
    return path.read_bytes()


def valid_allowlist() -> dict[str, Any]:
    return json.loads((ROOT / "examples" / "hub" / "allowlist-fixture.v1.json").read_text(encoding="utf-8"))


def signed(payload: dict[str, Any], private_key: Ed25519PrivateKey) -> dict[str, Any]:
    return sign_manifest_for_tests(payload, private_key, key_id=KEY_ID)


def make_fixture_state(base_url: str, temp_root: Path) -> dict[str, Any]:
    private_key = Ed25519PrivateKey.generate()
    public_key = private_key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    archive_path = temp_root / "production-fixture-pack.zip"
    archive_bytes = write_skill_pack(archive_path)
    archive_sha = sha256_bytes(archive_bytes)
    enhancer_body = b"print('production local enhancer contract fixture')\n"
    enhancer_sha = sha256_bytes(enhancer_body)
    allowlist = valid_allowlist()
    update = {
        "collection": "production-fixture-pack",
        "pack_id": "production-fixture-pack",
        "version": "0.2.1-production-e2e",
        "archive_url": f"{base_url}/archives/production-fixture-pack.zip",
        "sha256": archive_sha,
        "signature": "",
        "notes": "production registry contract fixture",
        "format": "skill-collection-zip-v1",
    }
    catalog = signed(
        {
            "schema_version": 1,
            "manifest_type": "catalog-updates",
            "requires_registration": True,
            "distribution_mode": "registered_catalog",
            "updates": [update],
            "packs": [
                {
                    "pack_id": "production-fixture-pack",
                    "collection": "production-fixture-pack",
                    "version": "0.2.1-production-e2e",
                    "requires_registration": True,
                    "format": "skill-collection-zip-v1",
                    "archive": {
                        "filename": "production-fixture-pack.zip",
                        "url": f"{base_url}/archives/production-fixture-pack.zip",
                        "sha256": archive_sha,
                        "bytes": len(archive_bytes),
                    },
                    "skill_count": 1,
                    "notes": "production registry contract fixture",
                }
            ],
        },
        private_key,
    )
    enhancement = signed(
        {
            "schema_version": 1,
            "manifest_type": "enhancement-manifest",
            "requires_registration": True,
            "script_id": "local-skill-enhancer",
            "version": "0.2.1-production-e2e",
            "download_url": f"{base_url}/enhancers/local-skill-enhancer.py",
            "sha256": enhancer_sha,
            "signature": "",
            "notes": "production contract enhancer fixture",
            "scripts": [
                {
                    "script_id": "local-skill-enhancer",
                    "version": "0.2.1-production-e2e",
                    "download_url": f"{base_url}/enhancers/local-skill-enhancer.py",
                    "sha256": enhancer_sha,
                    "runs_locally": True,
                    "sends_skill_content": False,
                }
            ],
        },
        private_key,
    )
    hub_allowlist = signed(
        {
            "schema_version": 1,
            "distribution_mode": "allowlist_only",
            "catalog_audit_verdict": "YES_WITH_ALLOWLIST",
            "full_catalog_distribution_allowed": False,
            "requires_registration": True,
            "free_active_client_instance_limit": 100,
            "allowlist": allowlist,
            "allowlist_sha256": allowlist_sha256(allowlist),
            "notes": "production signed hub allowlist fixture",
        },
        private_key,
    )
    team_sync = signed(
        {
            "schema_version": 1,
            "manifest_type": "team-sync-manifest",
            "team_id": "team_prod_contract",
            "plan": "team-free",
            "limits": {"max_instances": 10},
            "updates": [update],
            "removals": [],
            "request_id": "req_prod_contract_e2e",
        },
        private_key,
    )
    release_channels = signed(
        {
            "schema_version": 1,
            "manifest_type": "release-channels",
            "generated_at": "2026-06-09T00:00:00Z",
            "requires_registration": True,
            "policy": {
                "default_channel": "stable",
                "allowed_channels": ["stable", "beta", "canary"],
                "promotion_supported": True,
                "rollback_supported": True,
                "deprecation_supported": True,
            },
            "channels": [
                {
                    "name": "stable",
                    "status": "active",
                    "current_release_id": "a" * 64,
                    "catalog_updates_sha256": archive_sha,
                    "pack_count": 1,
                    "rollback_available": False,
                },
                {
                    "name": "beta",
                    "status": "active",
                    "current_release_id": "b" * 64,
                    "catalog_updates_sha256": archive_sha,
                    "pack_count": 1,
                    "rollback_available": True,
                },
            ],
            "deprecated_releases": [],
        },
        private_key,
    )
    entitlements = {
        "schema_version": 1,
        "plan": "registered-community",
        "features_enabled": ["hosted_catalog", "collection_updates", "local_skill_hub", "team_sync"],
        "limits": {"max_hub_clients": 100},
        "policy": {
            "hub_distribution_mode": "allowlist_only",
            "hosted_query_forwarding_allowed": False,
            "signed_manifests_required": True,
            "team_sync_enabled": True,
        },
        "grace": {"offline_grace_until": "2026-06-30T00:00:00Z"},
    }
    return {
        "public_key": base64_urlsafe_encode(public_key),
        "archive_bytes": archive_bytes,
        "enhancer_body": enhancer_body,
        "catalog": catalog,
        "enhancement": enhancement,
        "hub_allowlist": hub_allowlist,
        "team_sync": team_sync,
        "release_channels": release_channels,
        "entitlements": entitlements,
        "installations": {},
        "nonces": set(),
        "seen_channels": [],
        "proof_success_count": 0,
        "missing_proof_rejections": 0,
        "invalid_proof_rejections": 0,
        "replay_rejections": 0,
    }


class FixtureHandler(BaseHTTPRequestHandler):
    server_version = "UnlimitedSkillsProductionContractFixture/1"

    def log_message(self, _format: str, *_args: Any) -> None:
        return

    @property
    def state(self) -> dict[str, Any]:
        return self.server.state  # type: ignore[attr-defined]

    def read_raw_body(self) -> tuple[bytes, dict[str, Any]]:
        length = int(self.headers.get("Content-Length", "0") or "0")
        raw = self.rfile.read(length) if length > 0 else b"{}"
        try:
            payload = json.loads(raw.decode("utf-8") or "{}")
        except json.JSONDecodeError:
            payload = {}
        return raw, payload if isinstance(payload, dict) else {}

    def send_json(self, payload: dict[str, Any], status: int = 200) -> None:
        raw = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def send_bytes(self, payload: bytes, content_type: str) -> None:
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def reject(self, code: str, status: int = 401) -> bool:
        self.send_json({"error": {"code": code, "message": code}}, status=status)
        return False

    def verify_proof(self, raw_body: bytes) -> bool:
        auth = self.headers.get("Authorization", "")
        if auth != f"Bearer {TOKEN}":
            return self.reject("registration_required")
        proof_header = self.headers.get("X-ULS-Proof", "")
        if not proof_header:
            self.state["missing_proof_rejections"] += 1
            return self.reject("device_proof_required")
        try:
            proof = json.loads(base64_urlsafe_decode(proof_header).decode("utf-8"))
            install_id = str(proof.get("install_id") or "")
            key_thumbprint = str(proof.get("key_thumbprint") or "")
            body_sha256 = str(proof.get("body_sha256") or "")
            timestamp = str(proof.get("timestamp") or "")
            nonce = str(proof.get("nonce") or "")
            signature = str(proof.get("signature") or "")
        except Exception:
            self.state["invalid_proof_rejections"] += 1
            return self.reject("invalid_device_proof")
        install = self.state["installations"].get(install_id)
        if not install or key_thumbprint != install["key_thumbprint"]:
            self.state["invalid_proof_rejections"] += 1
            return self.reject("invalid_device_proof")
        if body_sha256 != hashlib.sha256(raw_body).hexdigest():
            self.state["invalid_proof_rejections"] += 1
            return self.reject("invalid_device_proof")
        nonce_key = (install_id, nonce)
        if nonce_key in self.state["nonces"]:
            self.state["replay_rejections"] += 1
            return self.reject("replayed_device_proof")
        message = "\n".join(["POST", urllib.parse.urlsplit(self.path).path or "/", body_sha256, timestamp, nonce, install_id, key_thumbprint])
        try:
            Ed25519PublicKey.from_public_bytes(base64_urlsafe_decode(install["public_key"])).verify(
                base64_urlsafe_decode(signature),
                message.encode("utf-8"),
            )
        except (InvalidSignature, ValueError):
            self.state["invalid_proof_rejections"] += 1
            return self.reject("invalid_device_proof")
        self.state["nonces"].add(nonce_key)
        self.state["proof_success_count"] += 1
        return True

    def do_GET(self) -> None:
        parsed = urllib.parse.urlsplit(self.path)
        if parsed.path == "/health":
            self.send_json({"status": "healthy", "production_contract_fixture": True})
            return
        if parsed.path == "/v1/public-keys":
            self.send_json(
                {
                    "schema_version": 1,
                    "keys": [
                        {
                            "key_id": KEY_ID,
                            "algorithm": "ed25519",
                            "public_key": self.state["public_key"],
                            "status": "active",
                            "scopes": ["hub-allowlist", "catalog-updates", "enhancement-manifest", "team-sync-manifest"],
                            "registry_origins": ["*"],
                        }
                    ],
                }
            )
            return
        if parsed.path == "/archives/production-fixture-pack.zip":
            self.send_bytes(self.state["archive_bytes"], "application/zip")
            return
        if parsed.path == "/enhancers/local-skill-enhancer.py":
            self.send_bytes(self.state["enhancer_body"], "text/x-python")
            return
        self.send_json({"error": "not_found"}, status=404)

    def do_POST(self) -> None:
        parsed = urllib.parse.urlsplit(self.path)
        raw_body, body = self.read_raw_body()
        if parsed.path == "/v1/installations/register":
            install_id = str(body.get("install_id") or "uls_inst_prod_contract")
            public_key = str(body.get("public_key") or "")
            key_thumbprint = str(body.get("key_thumbprint") or "")
            if not public_key or not key_thumbprint:
                self.send_json({"error": {"code": "invalid_registration"}}, status=400)
                return
            self.state["installations"][install_id] = {"public_key": public_key, "key_thumbprint": key_thumbprint}
            self.send_json(
                {
                    "schema_version": 1,
                    "install_id": install_id,
                    "plan": "registered-community",
                    "update_channel": "production-contract",
                    "license_token": TOKEN,
                    "registered_at": "2026-06-09T00:00:00Z",
                    "features_enabled": ["hosted_catalog", "collection_updates", "local_skill_hub", "team_sync"],
                    "key_thumbprint": key_thumbprint,
                    "proof_required": True,
                }
            )
            return
        if not self.verify_proof(raw_body):
            return
        if parsed.path in {"/v1/catalog", "/v1/collections/updates"}:
            self.state["seen_channels"].append(str(body.get("channel") or ""))
            self.send_json(self.state["catalog"])
            return
        if parsed.path == "/v1/channels/status":
            self.state["seen_channels"].append(str(body.get("channel") or ""))
            self.send_json(self.state["release_channels"])
            return
        if parsed.path == "/v1/enhancement/script":
            self.send_json(self.state["enhancement"])
            return
        if parsed.path == "/v1/hub/allowlist":
            self.send_json(self.state["hub_allowlist"])
            return
        if parsed.path in {"/v1/hub/heartbeat", "/v1/hub/entitlements"}:
            self.send_json(self.state["entitlements"])
            return
        if parsed.path == "/v1/teams":
            self.send_json(
                {
                    "schema_version": 1,
                    "team_id": "team_prod_contract",
                    "team_name": str(body.get("team_name") or "Production Contract"),
                    "team_token": "team_prod_contract_token",
                    "role": "master",
                    "status": "approved",
                    "approval_mode": "manual",
                    "join_code": "join_prod_contract",
                    "features_enabled": ["team_sync"],
                    "limits": {"max_instances": 10, "auto_approval_max_hours": 24},
                }
            )
            return
        if parsed.path == "/v1/teams/team_prod_contract/sync":
            self.send_json(self.state["team_sync"])
            return
        self.send_json({"error": "not_found"}, status=404)


class FixtureServer:
    def __init__(self, temp_root: Path) -> None:
        self.port = free_port()
        self.url = f"http://127.0.0.1:{self.port}"
        self.httpd = ThreadingHTTPServer(("127.0.0.1", self.port), FixtureHandler)
        self.httpd.state = make_fixture_state(self.url, temp_root)  # type: ignore[attr-defined]
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)

    def __enter__(self) -> "FixtureServer":
        self.thread.start()
        return self

    def __exit__(self, *_args: Any) -> None:
        self.httpd.shutdown()
        self.thread.join(timeout=5)


def run(command: list[str], *, env: dict[str, str], cwd: Path = ROOT, check: bool = True) -> subprocess.CompletedProcess[str]:
    completed = subprocess.run(command, cwd=cwd, env=env, text=True, encoding="utf-8", errors="replace", capture_output=True, check=False)
    if check and completed.returncode != 0:
        raise RuntimeError(
            "command failed: "
            + " ".join(command)
            + "\nstdout:\n"
            + redact_sensitive_text(completed.stdout)
            + "\nstderr:\n"
            + redact_sensitive_text(completed.stderr)
        )
    return completed


def assert_no_production_url(url: str) -> None:
    host = (urllib.parse.urlsplit(url).hostname or "").lower()
    if host in PRODUCTION_HOSTS:
        raise RuntimeError(f"Refusing production hosted call in contract E2E: {url}")


def request_status(url: str, body: bytes, headers: dict[str, str]) -> int:
    request = urllib.request.Request(url, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            response.read()
            return int(response.status)
    except urllib.error.HTTPError as exc:
        exc.read()
        return int(exc.code)


def exercise_proof_negative_cases(registry_url: str, env: dict[str, str]) -> None:
    state_path = Path(env["UNLIMITED_SKILLS_HOME"]) / "registration.json"
    state = state_from_json(json.loads(state_path.read_text(encoding="utf-8")))
    url = f"{registry_url.rstrip('/')}/v1/catalog"
    body = json.dumps({"schema_version": 1, "install_id": state.install_id}).encode("utf-8")
    base_headers = {"Content-Type": "application/json", "Authorization": f"Bearer {state.license_token}"}
    if request_status(url, body, dict(base_headers)) != 401:
        raise RuntimeError("missing device proof was not rejected")

    valid_headers = dict(base_headers)
    valid_headers.update(proof_headers(state, "POST", url, body))
    if request_status(url, body, dict(valid_headers)) != 200:
        raise RuntimeError("valid device proof was not accepted")
    if request_status(url, body, dict(valid_headers)) != 401:
        raise RuntimeError("replayed device proof was not rejected")

    invalid_headers = dict(base_headers)
    proof = json.loads(base64_urlsafe_decode(proof_headers(state, "POST", url, body)["X-ULS-Proof"]).decode("utf-8"))
    proof["signature"] = base64_urlsafe_encode(b"invalid")
    invalid_headers["X-ULS-Proof"] = base64_urlsafe_encode(json.dumps(proof, separators=(",", ":"), sort_keys=True).encode("utf-8"))
    if request_status(url, body, invalid_headers) != 401:
        raise RuntimeError("invalid device proof was not rejected")


def first_allowlisted_skill(allowlist_path: str) -> str:
    payload = json.loads(Path(allowlist_path).read_text(encoding="utf-8"))
    for item in payload.get("allowlist", []):
        if isinstance(item, dict) and item.get("name"):
            return str(item["name"])
    raise RuntimeError(f"No allowlisted skills found in {allowlist_path}")


def run_flow(registry_url: str, *, fixture_public_key: str, fixture_key_id: str = KEY_ID, fixture_state: dict[str, Any] | None = None) -> None:
    assert_no_production_url(registry_url)
    with tempfile.TemporaryDirectory(prefix="uls-production-contract-e2e-") as temp:
        temp_root = Path(temp)
        home = temp_root / "home"
        library = temp_root / "library"
        home.mkdir()
        env = os.environ.copy()
        env.update(
            {
                "HOME": str(home),
                "USERPROFILE": str(home),
                "UNLIMITED_SKILLS_HOME": str(home / ".unlimited-skills"),
                "UNLIMITED_SKILLS_DISABLE_NATIVE_SYNC": "1",
                "UNLIMITED_SKILLS_MANIFEST_PUBLIC_KEYS": f"{fixture_key_id}:{fixture_public_key}",
                "UNLIMITED_SKILLS_SERVICE_RETRIES": "1",
                "PYTHONPATH": str(ROOT),
            }
        )

        run([sys.executable, "-m", "unlimited_skills.cli", "--root", str(library), "register", "--server-url", registry_url, "--agent", "codex", "--timeout", "10"], env=env)
        status = json.loads(run([sys.executable, "-m", "unlimited_skills.cli", "license", "status", "--json"], env=env).stdout)
        assert status["registered"] is True
        assert status["proof_required"] is True

        catalog = run([sys.executable, "-m", "unlimited_skills.cli", "--root", str(library), "catalog", "list"], env=env).stdout
        assert "manifest_signature" in catalog
        release_status = json.loads(run([sys.executable, "-m", "unlimited_skills.cli", "release", "status", "--json", "--timeout", "10"], env=env).stdout)
        assert release_status["manifest_type"] == "release-channels"
        run([sys.executable, "-m", "unlimited_skills.cli", "release", "pin", "beta"], env=env)
        updates = json.loads(run([sys.executable, "-m", "unlimited_skills.cli", "--root", str(library), "updates", "check", "--json"], env=env).stdout)
        assert updates["count"] >= 1
        assert updates["channel"] == "beta"
        run([sys.executable, "-m", "unlimited_skills.cli", "--root", str(library), "updates", "apply", "--skip-reindex"], env=env)
        run([sys.executable, "-m", "unlimited_skills.cli", "--root", str(library), "reindex", "--no-native-sync"], env=env)

        enhancement = run([sys.executable, "-m", "unlimited_skills.cli", "--root", str(library), "enhance", "download"], env=env).stdout
        assert "local-skill-enhancer" in enhancement or "Downloaded enhancer" in enhancement

        hub_sync = json.loads(run([sys.executable, "-m", "unlimited_skills.cli", "--root", str(library), "hub", "sync", "--json"], env=env).stdout)
        assert hub_sync["distribution_mode"] == "allowlist_only"
        assert hub_sync["full_catalog_distribution_allowed"] is False
        selected_skill = first_allowlisted_skill(str(hub_sync["allowlist_path"]))
        run([sys.executable, "-m", "unlimited_skills.cli", "hub", "heartbeat", "--json", "--timeout", "10"], env=env)
        run([sys.executable, "-m", "unlimited_skills.cli", "hub", "license", "refresh", "--json", "--timeout", "10"], env=env)

        team = json.loads(run([sys.executable, "-m", "unlimited_skills.cli", "--root", str(library), "team", "create", "Production Contract E2E", "--timeout", "10"], env=env).stdout)
        assert team["team_id"] == "team_prod_contract"
        team_plan = json.loads(run([sys.executable, "-m", "unlimited_skills.cli", "--root", str(library), "team", "sync", "--dry-run", "--json", "--timeout", "10"], env=env).stdout)
        assert team_plan["plan"]["team_id"] == "team_prod_contract"
        assert team_plan["plan"]["collections"][0]["collection"] == "production-fixture-pack"

        exercise_proof_negative_cases(registry_url, env)
        assert selected_skill

    if fixture_state is not None:
        assert fixture_state["proof_success_count"] >= 8
        assert fixture_state["missing_proof_rejections"] >= 1
        assert fixture_state["invalid_proof_rejections"] >= 1
        assert fixture_state["replay_rejections"] >= 1
        assert "beta" in fixture_state["seen_channels"]

    print("production registry contract E2E passed")
    print(f"registry_url: {registry_url}")
    print("registration with device proof: ok")
    print("catalog/update/enhancement/hub/team signed manifests: ok")
    print("release channel status and pinning: ok")
    print("device proof missing/invalid/replay rejection: ok")
    print("production hosted calls: none")
    print("raw token/private key output: redacted/not printed")


def fetch_public_key(registry_url: str) -> tuple[str, str]:
    with urllib.request.urlopen(f"{registry_url.rstrip('/')}/v1/public-keys", timeout=10) as response:
        payload = json.loads(response.read().decode("utf-8"))
    for item in payload.get("keys", []):
        if isinstance(item, dict) and item.get("algorithm") == "ed25519":
            return str(item.get("key_id") or ""), str(item.get("public_key") or "")
    return "", ""


def main() -> int:
    parser = argparse.ArgumentParser(description="Run public client E2E against a production-shaped registry API.")
    parser.add_argument("--registry-url", default="")
    parser.add_argument("--fixture-mode", action="store_true")
    parser.add_argument("--temp-home", action="store_true", help="Kept for CLI compatibility; temp HOME is always used.")
    args = parser.parse_args()

    if args.registry_url and args.fixture_mode:
        raise SystemExit("--registry-url and --fixture-mode are mutually exclusive")
    if args.registry_url:
        key_id, public_key = fetch_public_key(args.registry_url.rstrip("/"))
        run_flow(args.registry_url.rstrip("/"), fixture_public_key=public_key, fixture_key_id=key_id)
        return 0
    with tempfile.TemporaryDirectory(prefix="uls-production-contract-fixture-") as temp:
        with FixtureServer(Path(temp)) as server:
            run_flow(
                server.url,
                fixture_public_key=server.httpd.state["public_key"],  # type: ignore[attr-defined]
                fixture_state=server.httpd.state,  # type: ignore[attr-defined]
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
