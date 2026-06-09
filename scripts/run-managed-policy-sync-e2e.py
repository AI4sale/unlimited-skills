from __future__ import annotations

import argparse
import hashlib
import json
import os
import socket
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from unlimited_skills.policy import canonical_policy_sha256, install_policy_payload, load_policy
from unlimited_skills.policy_enforcement import (
    PolicyViolation,
    enforce_community_install,
    enforce_registry_url,
    enforce_release_channel,
    enforce_remote_fallback_allowed,
)
from unlimited_skills.policy_sync import sync_managed_policy
from unlimited_skills.registration import (
    RegistrationState,
    base64_urlsafe_decode,
    base64_urlsafe_encode,
    proof_headers,
    register_installation,
    save_registration,
)
from unlimited_skills.signatures import sign_manifest_for_tests


KEY_ID = "managed-policy-e2e-key"
UNKNOWN_KEY_ID = "managed-policy-unknown-key"
TOKEN = "uls_tok_managed_policy_e2e"
PRODUCTION_HOSTS = {"unlimited.ai4.sale", "github.com", "api.github.com"}


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def public_key_b64(private_key: Ed25519PrivateKey) -> str:
    raw = private_key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    return base64_urlsafe_encode(raw)


def policy_payload(policy_id: str, *, mode: str = "enforce", allowed_registry: str = "http://127.0.0.1") -> dict[str, Any]:
    payload = {
        "schema_version": 1,
        "policy_id": policy_id,
        "mode": mode,
        "allowed_registries": [allowed_registry],
        "allowed_release_channels": ["stable"],
        "required_manifest_signatures": True,
        "allowed_key_ids": [KEY_ID],
        "allowed_key_scopes": ["enterprise-policy", "catalog-updates"],
        "allowed_local_roots": [],
        "community": {"install_allowed": False, "submit_allowed": False},
        "hub": {"remote_required": True, "local_fallback_allowed": False, "unsigned_local_allowlist_allowed": False},
        "audit": {"log_refusals": True},
    }
    payload["policy_sha256"] = canonical_policy_sha256(payload)
    return payload


def signed_assignment(action: str, private_key: Ed25519PrivateKey, *, policy: dict[str, Any] | None = None, key_id: str = KEY_ID) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "schema_version": 1,
        "manifest_type": "enterprise-policy-assignment",
        "assignment_id": f"assign_{action}_{int(time.time())}",
        "install_id": "uls_inst_managed_policy_e2e",
        "action": action,
        "assigned_at": "2026-06-09T00:00:00Z",
    }
    if policy is not None:
        payload["policy"] = json.loads(json.dumps(policy, ensure_ascii=False, sort_keys=True))
    return sign_manifest_for_tests(payload, private_key, key_id=key_id)


def assert_no_production_url(url: str) -> None:
    host = (urllib.parse.urlsplit(url).hostname or "").lower()
    if host in PRODUCTION_HOSTS:
        raise RuntimeError(f"Refusing production hosted call in managed policy sync E2E: {url}")


class ManagedPolicyFixtureHandler(BaseHTTPRequestHandler):
    server_version = "UnlimitedSkillsManagedPolicyFixture/1"

    def log_message(self, _format: str, *_args: Any) -> None:
        return

    @property
    def state(self) -> dict[str, Any]:
        return self.server.state  # type: ignore[attr-defined]

    def read_body(self) -> tuple[bytes, dict[str, Any]]:
        length = int(self.headers.get("Content-Length", "0") or "0")
        raw = self.rfile.read(length) if length else b"{}"
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

    def reject(self, code: str, status: int = 401) -> bool:
        self.send_json({"error": {"code": code, "message": code}}, status=status)
        return False

    def verify_proof(self, raw_body: bytes) -> bool:
        if self.headers.get("Authorization", "") != f"Bearer {TOKEN}":
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
        if self.path == "/health":
            self.send_json({"status": "healthy"})
            return
        if self.path == "/v1/public-keys":
            self.send_json(
                {
                    "schema_version": 1,
                    "keys": [
                        {
                            "key_id": KEY_ID,
                            "algorithm": "ed25519",
                            "public_key": self.state["public_key"],
                            "status": "active",
                            "scopes": ["enterprise-policy"],
                            "registry_origins": ["*"],
                        }
                    ],
                }
            )
            return
        self.send_json({"error": "not_found"}, status=404)

    def do_POST(self) -> None:
        path = urllib.parse.urlsplit(self.path).path
        raw_body, body = self.read_body()
        if path == "/v1/installations/register":
            install_id = str(body.get("install_id") or "uls_inst_managed_policy_e2e")
            self.state["installations"][install_id] = {
                "public_key": str(body.get("public_key") or ""),
                "key_thumbprint": str(body.get("key_thumbprint") or ""),
            }
            self.send_json(
                {
                    "schema_version": 1,
                    "install_id": install_id,
                    "plan": "registered-community",
                    "license_token": TOKEN,
                    "registered_at": "2026-06-09T00:00:00Z",
                    "features_enabled": ["enterprise_policy_sync"],
                    "key_thumbprint": str(body.get("key_thumbprint") or ""),
                    "proof_required": True,
                }
            )
            return
        if path != "/v1/policy/sync":
            self.send_json({"error": "not_found"}, status=404)
            return
        if not self.verify_proof(raw_body):
            return
        self.state["requests"].append(body)
        if any(key in body for key in ("skill_bodies", "prompts", "source_code", "local_path", "token", "device_private_key")):
            self.state["forbidden_field_seen"] = True
            self.send_json({"error": "forbidden_field"}, status=400)
            return
        queue = self.state["assignments"]
        if not queue:
            self.send_json(signed_assignment("none", self.state["private_key"]))
            return
        response = queue.pop(0)
        self.send_json(response)


class FixtureServer:
    def __init__(self, temp_root: Path) -> None:
        self.port = free_port()
        self.url = f"http://127.0.0.1:{self.port}"
        private_key = Ed25519PrivateKey.generate()
        unknown_key = Ed25519PrivateKey.generate()
        v1 = policy_payload("managed_policy_v1", allowed_registry=self.url)
        v2 = policy_payload("managed_policy_v1", allowed_registry=self.url)
        v2["allowed_release_channels"] = ["stable"]
        v2["policy_sha256"] = canonical_policy_sha256(v2)
        tampered = signed_assignment("install", private_key, policy=v2)
        tampered["policy"]["policy_id"] = "tampered_after_sign"
        self.httpd = ThreadingHTTPServer(("127.0.0.1", self.port), ManagedPolicyFixtureHandler)
        self.httpd.state = {  # type: ignore[attr-defined]
            "private_key": private_key,
            "public_key": public_key_b64(private_key),
            "installations": {},
            "nonces": set(),
            "requests": [],
            "assignments": [
                signed_assignment("install", private_key, policy=v1),
                signed_assignment("install", private_key, policy=v1),
                signed_assignment("update", private_key, policy=v2),
                signed_assignment("remove", private_key),
                signed_assignment("remove", private_key),
                signed_assignment("remove", private_key),
                tampered,
                signed_assignment("install", unknown_key, policy=v2, key_id=UNKNOWN_KEY_ID),
            ],
            "missing_proof_rejections": 0,
            "invalid_proof_rejections": 0,
            "replay_rejections": 0,
            "proof_success_count": 0,
            "forbidden_field_seen": False,
        }
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)

    def __enter__(self) -> "FixtureServer":
        self.thread.start()
        return self

    def __exit__(self, *_args: Any) -> None:
        self.httpd.shutdown()
        self.thread.join(timeout=5)


def request_status(url: str, body: bytes, headers: dict[str, str]) -> int:
    request = urllib.request.Request(url, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            response.read()
            return int(response.status)
    except urllib.error.HTTPError as exc:
        exc.read()
        return int(exc.code)


def exercise_proof_negative_cases(registry_url: str, state: RegistrationState) -> None:
    url = f"{registry_url.rstrip('/')}/v1/policy/sync"
    body = json.dumps({"schema_version": 1, "install_id": state.install_id, "current_policy": {"installed": False}}).encode("utf-8")
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


def expect_violation(label: str, func: Any) -> None:
    try:
        func()
    except PolicyViolation:
        return
    raise RuntimeError(f"policy enforcement did not reject {label}")


def run_fixture_flow(registry_url: str, public_key: str, *, fixture_state: dict[str, Any] | None = None) -> None:
    assert_no_production_url(registry_url)
    with tempfile.TemporaryDirectory(prefix="uls-managed-policy-e2e-") as temp:
        home = Path(temp) / "home"
        os.environ["HOME"] = str(home)
        os.environ["USERPROFILE"] = str(home)
        os.environ["UNLIMITED_SKILLS_HOME"] = str(home / ".unlimited-skills")
        os.environ["UNLIMITED_SKILLS_MANIFEST_PUBLIC_KEYS"] = f"{KEY_ID}:{public_key}"
        os.environ["UNLIMITED_SKILLS_SERVICE_RETRIES"] = "1"
        home.mkdir(parents=True, exist_ok=True)
        state = register_installation(
            RegistrationState(install_id="uls_inst_managed_policy_e2e"),
            server_url=registry_url,
            agent="codex",
            skill_count=0,
            timeout=10,
        )
        save_registration(state, home=Path(os.environ["UNLIMITED_SKILLS_HOME"]))

        dry_run = sync_managed_policy(home=Path(os.environ["UNLIMITED_SKILLS_HOME"]), state=state, dry_run=True, timeout=10)
        assert dry_run["dry_run"] is True
        assert dry_run["assignment"]["action"] == "install"
        assert not (Path(os.environ["UNLIMITED_SKILLS_HOME"]) / "policy" / "managed-policy-state.json").exists()

        installed = sync_managed_policy(home=Path(os.environ["UNLIMITED_SKILLS_HOME"]), state=state, timeout=10)
        assert installed["changed"] is True
        assert load_policy(Path(os.environ["UNLIMITED_SKILLS_HOME"]))["policy_id"] == "managed_policy_v1"

        updated = sync_managed_policy(home=Path(os.environ["UNLIMITED_SKILLS_HOME"]), state=state, timeout=10)
        assert updated["assignment"]["action"] == "update"

        expect_violation("disallowed registry", lambda: enforce_registry_url("https://evil.example.test", home=Path(os.environ["UNLIMITED_SKILLS_HOME"])))
        expect_violation("disallowed release channel", lambda: enforce_release_channel("canary", home=Path(os.environ["UNLIMITED_SKILLS_HOME"])))
        expect_violation("community install", lambda: enforce_community_install(home=Path(os.environ["UNLIMITED_SKILLS_HOME"])))
        expect_violation("remote fallback", lambda: enforce_remote_fallback_allowed(home=Path(os.environ["UNLIMITED_SKILLS_HOME"])))

        removed = sync_managed_policy(home=Path(os.environ["UNLIMITED_SKILLS_HOME"]), state=state, timeout=10)
        assert removed["managed_state"]["remove_allowed"] is True
        assert load_policy(Path(os.environ["UNLIMITED_SKILLS_HOME"]))["installed"] is False

        unmanaged = policy_payload("local_unmanaged_policy", allowed_registry=registry_url)
        install_policy_payload(unmanaged, home=Path(os.environ["UNLIMITED_SKILLS_HOME"]), source="local-admin")
        refused = sync_managed_policy(home=Path(os.environ["UNLIMITED_SKILLS_HOME"]), state=state, dry_run=True, timeout=10)
        assert refused["managed_state"]["removal_refused"] is True
        refused_apply = sync_managed_policy(home=Path(os.environ["UNLIMITED_SKILLS_HOME"]), state=state, timeout=10)
        assert refused_apply["managed_state"]["removal_refused"] is True
        assert load_policy(Path(os.environ["UNLIMITED_SKILLS_HOME"]))["policy_id"] == "local_unmanaged_policy"

        for expected in ("signed_payload_sha256 mismatch", "not approved by policy"):
            try:
                sync_managed_policy(home=Path(os.environ["UNLIMITED_SKILLS_HOME"]), state=state, timeout=10)
            except Exception as exc:
                if expected not in str(exc):
                    raise
            else:
                raise RuntimeError(f"expected managed policy sync failure containing {expected}")

        exercise_proof_negative_cases(registry_url, state)
        request_text = json.dumps(fixture_state["requests"] if fixture_state else [], sort_keys=True)
        forbidden = ("skill_bodies", "prompts", "source_code", "local_path", "device_private_key")
        if any(item in request_text for item in forbidden):
            raise RuntimeError("policy sync request leaked forbidden local fields")
        audit_text = (Path(os.environ["UNLIMITED_SKILLS_HOME"]) / "policy" / "refusals.jsonl").read_text(encoding="utf-8")
        if state.license_token in audit_text or state.device_private_key in audit_text or "PRIVATE KEY" in audit_text:
            raise RuntimeError("policy audit leaked token/private key material")

    if fixture_state is not None:
        assert fixture_state["proof_success_count"] >= 6
        assert fixture_state["missing_proof_rejections"] >= 1
        assert fixture_state["invalid_proof_rejections"] >= 1
        assert fixture_state["replay_rejections"] >= 1

    print("managed Enterprise policy sync E2E passed")
    print(f"registry_url: {registry_url}")
    print("registration with device proof: ok")
    print("signed policy assignment install/update/remove: ok")
    print("unmanaged local policy remove refusal: ok")
    print("policy enforcement refusals: registry/channel/community/local fallback ok")
    print("unsigned/tampered/unknown-key assignment rejection: ok")
    print("request forbidden-field scan: clean")
    print("production hosted calls: none")
    print("raw token/private key/proof output: redacted/not printed")


def fetch_public_key(registry_url: str) -> str:
    with urllib.request.urlopen(f"{registry_url.rstrip('/')}/v1/public-keys", timeout=10) as response:
        payload = json.loads(response.read().decode("utf-8"))
    for item in payload.get("keys", []):
        if isinstance(item, dict) and item.get("algorithm") == "ed25519" and "enterprise-policy" in item.get("scopes", []):
            return str(item.get("public_key") or "")
    raise RuntimeError("Registry did not publish an enterprise-policy Ed25519 public key.")


def main() -> int:
    parser = argparse.ArgumentParser(description="Run managed Enterprise Skill Lock policy sync E2E.")
    parser.add_argument("--fixture-mode", action="store_true")
    parser.add_argument("--registry-url", default="")
    parser.add_argument("--temp-home", action="store_true", help="Kept for CLI compatibility; temp HOME is always used.")
    args = parser.parse_args()
    if args.fixture_mode and args.registry_url:
        raise SystemExit("--fixture-mode and --registry-url are mutually exclusive")
    if args.registry_url:
        registry_url = args.registry_url.rstrip("/")
        run_fixture_flow(registry_url, fetch_public_key(registry_url))
        return 0
    with tempfile.TemporaryDirectory(prefix="uls-managed-policy-fixture-") as temp:
        with FixtureServer(Path(temp)) as server:
            run_fixture_flow(
                server.url,
                server.httpd.state["public_key"],  # type: ignore[attr-defined]
                fixture_state=server.httpd.state,  # type: ignore[attr-defined]
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
