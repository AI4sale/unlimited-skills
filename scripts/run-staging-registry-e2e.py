from __future__ import annotations

import argparse
import io
import json
import os
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.parse
import urllib.request
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from unlimited_skills.hub_allowlist import allowlist_sha256
from unlimited_skills.registration import base64_urlsafe_encode, redact_sensitive_text, state_from_json
from unlimited_skills.signatures import sign_manifest_for_tests
from unlimited_skills.updates import CollectionUpdate, UpdateClient, UpdateError, safe_extract_zip


ROOT = Path(__file__).resolve().parents[1]
PRODUCTION_HOSTS = {"unlimited.ai4.sale", "api.github.com", "github.com"}
KEY_ID = "staging-e2e-key"


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def write_skill_pack(path: Path) -> bytes:
    content = "---\nname: fixture-skill\ndescription: Signed registry E2E skill.\n---\n\n# fixture-skill\n"
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("fixture-pack/skills/fixture-skill/SKILL.md", content)
    return path.read_bytes()


def sha256_bytes(value: bytes) -> str:
    import hashlib

    return hashlib.sha256(value).hexdigest()


def valid_allowlist() -> dict[str, Any]:
    return json.loads((ROOT / "examples" / "hub" / "allowlist-fixture.v1.json").read_text(encoding="utf-8"))


def signed(payload: dict[str, Any], private_key: Ed25519PrivateKey) -> dict[str, Any]:
    return sign_manifest_for_tests(payload, private_key, key_id=KEY_ID)


def make_fixture_state(base_url: str, temp_root: Path) -> dict[str, Any]:
    private_key = Ed25519PrivateKey.generate()
    public_key = private_key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    archive_path = temp_root / "fixture-pack.zip"
    archive_bytes = write_skill_pack(archive_path)
    archive_sha = sha256_bytes(archive_bytes)
    enhancer_body = b"print('staging local enhancer fixture')\n"
    enhancer_sha = sha256_bytes(enhancer_body)
    allowlist = valid_allowlist()
    update = {
        "collection": "fixture-pack",
        "pack_id": "fixture-pack",
        "version": "0.2.1-e2e",
        "archive_url": f"{base_url}/archives/fixture-pack.zip",
        "sha256": archive_sha,
        "signature": "",
        "notes": "staging signed registry e2e fixture",
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
                    "pack_id": "fixture-pack",
                    "collection": "fixture-pack",
                    "version": "0.2.1-e2e",
                    "requires_registration": True,
                    "format": "skill-collection-zip-v1",
                    "archive": {
                        "filename": "fixture-pack.zip",
                        "url": f"{base_url}/archives/fixture-pack.zip",
                        "sha256": archive_sha,
                        "bytes": len(archive_bytes),
                    },
                    "skill_count": 1,
                    "notes": "staging signed registry e2e fixture",
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
            "version": "0.2.1-e2e",
            "download_url": f"{base_url}/enhancers/local-skill-enhancer.py",
            "sha256": enhancer_sha,
            "signature": "",
            "notes": "staging local enhancer fixture",
            "scripts": [
                {
                    "script_id": "local-skill-enhancer",
                    "version": "0.2.1-e2e",
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
            "notes": "staging signed hub allowlist",
        },
        private_key,
    )
    team_sync = signed(
        {
            "schema_version": 1,
            "manifest_type": "team-sync-manifest",
            "team_id": "team_staging",
            "plan": "team-free",
            "limits": {"max_instances": 10},
            "updates": [update],
            "removals": [],
            "request_id": "req_staging_e2e",
        },
        private_key,
    )
    return {
        "public_key": base64_urlsafe_encode(public_key),
        "archive_bytes": archive_bytes,
        "enhancer_body": enhancer_body,
        "catalog": catalog,
        "enhancement": enhancement,
        "hub_allowlist": hub_allowlist,
        "team_sync": team_sync,
    }


class FixtureHandler(BaseHTTPRequestHandler):
    server_version = "UnlimitedSkillsStagingFixture/1"

    def log_message(self, _format: str, *_args: Any) -> None:
        return

    @property
    def state(self) -> dict[str, Any]:
        return self.server.state  # type: ignore[attr-defined]

    def read_body(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0") or "0")
        if length <= 0:
            return {}
        try:
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
        except json.JSONDecodeError:
            return {}
        return payload if isinstance(payload, dict) else {}

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

    def auth_ok(self) -> bool:
        value = self.headers.get("Authorization", "")
        return value.startswith("Bearer uls_dev_registry_e2e")

    def require_auth(self) -> bool:
        if self.auth_ok():
            return True
        self.send_json({"error": {"code": "registration_required", "message": "dev bearer token required"}}, status=401)
        return False

    def do_GET(self) -> None:
        parsed = urllib.parse.urlsplit(self.path)
        if parsed.path == "/health":
            self.send_json({"status": "healthy", "staging": True})
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
        if parsed.path == "/archives/fixture-pack.zip":
            self.send_bytes(self.state["archive_bytes"], "application/zip")
            return
        if parsed.path == "/enhancers/local-skill-enhancer.py":
            self.send_bytes(self.state["enhancer_body"], "text/x-python")
            return
        self.send_json({"error": "not_found"}, status=404)

    def do_POST(self) -> None:
        parsed = urllib.parse.urlsplit(self.path)
        body = self.read_body()
        if parsed.path == "/v1/installations/register":
            install_id = str(body.get("install_id") or "uls_inst_staging_e2e")
            self.send_json(
                {
                    "install_id": install_id,
                    "plan": "registered-community-dev",
                    "update_channel": "staging",
                    "license_token": "uls_dev_registry_e2e_token",
                    "registered_at": "2026-06-08T00:00:00Z",
                    "features_enabled": ["hosted_catalog", "collection_updates", "local_skill_hub", "team_sync"],
                    "key_thumbprint": str(body.get("key_thumbprint") or "0" * 64),
                    "proof_required": False,
                }
            )
            return
        if not self.require_auth():
            return
        if parsed.path in {"/v1/catalog", "/v1/collections/updates"}:
            self.send_json(self.state["catalog"])
            return
        if parsed.path == "/v1/enhancement/script":
            self.send_json(self.state["enhancement"])
            return
        if parsed.path == "/v1/hub/allowlist":
            self.send_json(self.state["hub_allowlist"])
            return
        if parsed.path.startswith("/v1/teams/") and parsed.path.endswith("/sync"):
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


def require_contains(needle: str, completed: subprocess.CompletedProcess[str]) -> None:
    if needle not in completed.stdout:
        raise RuntimeError(
            f"expected {needle!r} in output for command: {' '.join(completed.args)}"
            + "\nstdout:\n"
            + redact_sensitive_text(completed.stdout)
            + "\nstderr:\n"
            + redact_sensitive_text(completed.stderr)
        )


def first_allowlisted_skill(allowlist_path: str) -> str:
    payload = json.loads(Path(allowlist_path).read_text(encoding="utf-8"))
    for item in payload.get("allowlist", []):
        if isinstance(item, dict) and item.get("name"):
            return str(item["name"])
    raise RuntimeError(f"No allowlisted skills found in {allowlist_path}")


def wait_http(url: str, timeout: float = 15.0) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=1) as response:
                if response.status < 500:
                    return
        except OSError:
            time.sleep(0.2)
    raise RuntimeError(f"Timed out waiting for {url}")


def assert_no_production_url(url: str) -> None:
    host = (urllib.parse.urlsplit(url).hostname or "").lower()
    if host in PRODUCTION_HOSTS:
        raise RuntimeError(f"Refusing production hosted call in staging E2E: {url}")


def exercise_negative_cases(env: dict[str, str], temp_root: Path, registry_url: str) -> None:
    private_key = Ed25519PrivateKey.generate()
    unsigned = temp_root / "unsigned.json"
    unsigned.write_text(json.dumps({"schema_version": 1, "updates": []}), encoding="utf-8")
    assert run([sys.executable, "-m", "unlimited_skills.cli", "trust", "verify", str(unsigned), "--scope", "catalog-updates", "--registry-url", registry_url], env=env, check=False).returncode == 2

    tampered_payload = sign_manifest_for_tests({"schema_version": 1, "updates": [{"collection": "fixture-pack"}]}, private_key, key_id="tampered-key")
    public_key = private_key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    tampered_env = dict(env)
    tampered_env["UNLIMITED_SKILLS_MANIFEST_PUBLIC_KEYS"] = f"tampered-key:{base64_urlsafe_encode(public_key)}"
    tampered_payload["updates"][0]["collection"] = "changed-after-signing"
    tampered = temp_root / "tampered.json"
    tampered.write_text(json.dumps(tampered_payload), encoding="utf-8")
    assert run([sys.executable, "-m", "unlimited_skills.cli", "trust", "verify", str(tampered), "--scope", "catalog-updates", "--registry-url", registry_url], env=tampered_env, check=False).returncode == 2

    unknown = temp_root / "unknown.json"
    unknown.write_text(json.dumps(sign_manifest_for_tests({"schema_version": 1, "updates": []}, private_key, key_id="unknown-key")), encoding="utf-8")
    assert run([sys.executable, "-m", "unlimited_skills.cli", "trust", "verify", str(unknown), "--scope", "catalog-updates", "--registry-url", registry_url], env=env, check=False).returncode == 2

    bad_zip = temp_root / "path-traversal.zip"
    with zipfile.ZipFile(bad_zip, "w") as zf:
        zf.writestr("../escape/SKILL.md", "bad")
    try:
        safe_extract_zip(bad_zip, temp_root / "bad-extract")
    except UpdateError:
        pass
    else:
        raise RuntimeError("path traversal archive was not rejected")

    state_file = Path(env["UNLIMITED_SKILLS_HOME"]) / "registration.json"
    state = json.loads(state_file.read_text(encoding="utf-8"))
    client = UpdateClient(state_from_json(state), timeout=5)
    try:
        client.apply(
            temp_root / "library",
            CollectionUpdate(
                collection="fixture-pack",
                version="bad-sha",
                archive_url=f"{registry_url}/archives/fixture-pack.zip",
                sha256="0" * 64,
            ),
        )
    except UpdateError:
        pass
    else:
        raise RuntimeError("SHA mismatch update was not rejected")


def run_flow(registry_url: str, *, temp_home: bool = True, fixture_public_key: str = "", fixture_key_id: str = KEY_ID) -> None:
    assert_no_production_url(registry_url)
    with tempfile.TemporaryDirectory(prefix="uls-staging-e2e-") as temp:
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
                "PYTHONPATH": str(ROOT),
            }
        )
        if fixture_public_key:
            env["UNLIMITED_SKILLS_MANIFEST_PUBLIC_KEYS"] = f"{fixture_key_id}:{fixture_public_key}"

        run([sys.executable, "-m", "unlimited_skills.cli", "--root", str(library), "register", "--server-url", registry_url, "--agent", "codex", "--timeout", "10"], env=env)
        status = run([sys.executable, "-m", "unlimited_skills.cli", "license", "status", "--json"], env=env).stdout
        assert json.loads(status)["registered"] is True

        catalog = run([sys.executable, "-m", "unlimited_skills.cli", "--root", str(library), "catalog", "list"], env=env).stdout
        assert "manifest_signature" in catalog

        updates = json.loads(run([sys.executable, "-m", "unlimited_skills.cli", "--root", str(library), "updates", "check", "--json"], env=env).stdout)
        assert updates["count"] >= 1
        run([sys.executable, "-m", "unlimited_skills.cli", "--root", str(library), "updates", "apply", "--skip-reindex"], env=env)
        run([sys.executable, "-m", "unlimited_skills.cli", "--root", str(library), "reindex", "--no-native-sync"], env=env)

        enhancement = run([sys.executable, "-m", "unlimited_skills.cli", "--root", str(library), "enhance", "download"], env=env).stdout
        assert "Downloaded enhancer" in enhancement or "local-skill-enhancer" in enhancement

        hub_sync = json.loads(run([sys.executable, "-m", "unlimited_skills.cli", "--root", str(library), "hub", "sync", "--json"], env=env).stdout)
        assert hub_sync["distribution_mode"] == "allowlist_only"
        assert hub_sync["full_catalog_distribution_allowed"] is False
        selected_skill = first_allowlisted_skill(str(hub_sync["allowlist_path"]))
        selected_query = selected_skill.replace("-", " ")
        require_contains(selected_skill, run([sys.executable, "-m", "unlimited_skills.cli", "--root", str(library), "search", selected_query, "--mode", "lexical", "--no-native-sync"], env=env))
        token_payload = json.loads(run([sys.executable, "-m", "unlimited_skills.cli", "hub", "token", "create", "--label", "staging-e2e", "--json"], env=env).stdout)
        hub_token = token_payload["token"]
        env["ULS_HUB_TOKEN"] = hub_token
        hub_port = free_port()
        hub_proc = subprocess.Popen(
            [sys.executable, "-m", "unlimited_skills.cli", "--root", str(library), "hub", "serve", "--host", "127.0.0.1", "--port", str(hub_port)],
            cwd=ROOT,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        try:
            wait_http(f"http://127.0.0.1:{hub_port}/health")
            run([sys.executable, "-m", "unlimited_skills.cli", "remote", "configure", "--url", f"http://127.0.0.1:{hub_port}", "--token-env", "ULS_HUB_TOKEN", "--fallback", "hub_required"], env=env)
            remote_status = run([sys.executable, "-m", "unlimited_skills.cli", "remote", "status", "--json"], env=env).stdout
            assert "ULS_HUB_TOKEN" in remote_status and hub_token not in remote_status
            status_payload = json.loads(remote_status)
            assert status_payload["hub_status"]["allowlisted_skills"] >= 1
            require_contains(selected_skill, run([sys.executable, "-m", "unlimited_skills.cli", "--root", str(library), "remote", "search", selected_query, "--json"], env=env))
            require_contains(selected_skill, run([sys.executable, "-m", "unlimited_skills.cli", "--root", str(library), "remote", "resolve", selected_query, "--agent", "codex", "--json"], env=env))
            view_output = run([sys.executable, "-m", "unlimited_skills.cli", "--root", str(library), "remote", "view", selected_skill], env=env)
            require_contains(selected_skill, view_output)
            require_contains("description:", view_output)
        finally:
            hub_proc.terminate()
            try:
                hub_proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                hub_proc.kill()

        exercise_negative_cases(env, temp_root, registry_url)
    print("staging signed registry E2E passed")
    print(f"registry_url: {registry_url}")
    print("registration: ok")
    print("signed catalog/update/hub/team/enhancement verification: ok")
    print("hub sync and remote resolve: ok")
    print("tampered/unsigned/unknown-key/SHA/path-traversal rejection: ok")
    print("production hosted calls: none")
    print("raw token/private key output: redacted/not printed")


def fetch_public_key(registry_url: str) -> tuple[str, str]:
    with urllib.request.urlopen(f"{registry_url.rstrip('/')}/v1/public-keys", timeout=10) as response:
        payload = json.loads(response.read().decode("utf-8"))
    for item in payload.get("keys", []):
        if isinstance(item, dict) and item.get("key_id") == "registry-alpha-2026-06":
            return str(item.get("key_id") or ""), str(item.get("public_key") or "")
    for item in payload.get("keys", []):
        if isinstance(item, dict) and item.get("algorithm") == "ed25519":
            return str(item.get("key_id") or ""), str(item.get("public_key") or "")
    return "", ""


def main() -> int:
    parser = argparse.ArgumentParser(description="Run public client E2E against staging signed registry.")
    parser.add_argument("--registry-url", default="")
    parser.add_argument("--fixture-mode", action="store_true")
    parser.add_argument("--temp-home", action="store_true", help="Kept for CLI compatibility; temp HOME is always used.")
    args = parser.parse_args()

    if args.registry_url and args.fixture_mode:
        raise SystemExit("--registry-url and --fixture-mode are mutually exclusive")
    if args.registry_url:
        key_id, public_key = fetch_public_key(args.registry_url.rstrip("/"))
        run_flow(args.registry_url.rstrip("/"), temp_home=True, fixture_public_key=public_key, fixture_key_id=key_id)
        return 0
    with tempfile.TemporaryDirectory(prefix="uls-staging-fixture-") as temp:
        with FixtureServer(Path(temp)) as server:
            run_flow(server.url, temp_home=True, fixture_public_key=server.httpd.state["public_key"])  # type: ignore[attr-defined]
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
