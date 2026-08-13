"""One-command Company Memory trial client for Unlimited Skills."""
from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import os
import re
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Iterator

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID


STATE_SCHEMA = "unlimited-skills.company-memory-installation.v1"
BOOTSTRAP_SCHEMA = "unlimited-skills.company-memory-bootstrap.v1"
REQUEST_SCHEMA = "unlimited-skills.business-context-request.v1"
MAX_RESPONSE_BYTES = 2_000_000
MAX_OUTCOME_BYTES = 64 * 1024
OUTCOME_SCHEMA = "unlimited-skills.checked-task-outcome.v1"
ACCESS_RECEIPT_SCHEMA = "unlimited-skills.company-memory-access-receipt.v1"
STABLE_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/-]{0,239}")
RENEW_BEFORE = timedelta(hours=6)
HANDOFF_BEFORE = timedelta(hours=24)


class MemoryError(RuntimeError):
    pass


def default_home() -> Path:
    explicit = os.environ.get("UNLIMITED_SKILLS_HOME")
    return (Path(explicit).expanduser() if explicit else Path.home() / ".unlimited-skills").resolve()


def default_bundle(home: Path | None = None) -> Path:
    return (home or default_home()) / "company-memory"


def _origin(value: str) -> str:
    parsed = urllib.parse.urlparse(value.rstrip("/"))
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.path not in {"", "/"}
        or parsed.params
        or parsed.query
        or parsed.fragment
    ):
        raise MemoryError("Company Memory URL must be an HTTPS origin")
    return value.rstrip("/")


def _atomic_private(path: Path, value: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    descriptor = os.open(temporary, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(value)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


def _atomic_json(path: Path, value: dict[str, Any], *, private: bool = True) -> None:
    encoded = (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode(
        "utf-8"
    )
    if private:
        _atomic_private(path, encoded)
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    temporary.write_bytes(encoded)
    os.replace(temporary, path)


def _key_csr(common_name: str) -> tuple[Any, str]:
    key = rsa.generate_private_key(public_exponent=65537, key_size=3072)
    csr = (
        x509.CertificateSigningRequestBuilder()
        .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, common_name)]))
        .sign(key, hashes.SHA256())
    )
    return key, csr.public_bytes(serialization.Encoding.PEM).decode("ascii")


def _private_key_pem(key: Any) -> str:
    return key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode("ascii")


def _private_key(value: str) -> Any:
    try:
        return serialization.load_pem_private_key(value.encode("ascii"), password=None)
    except (TypeError, ValueError) as exc:
        raise MemoryError("Company Memory bootstrap private key is invalid") from exc


def _certificate_matches(certificate_pem: str, key: Any) -> None:
    try:
        certificate = x509.load_pem_x509_certificate(certificate_pem.encode("ascii"))
    except ValueError as exc:
        raise MemoryError("server returned an invalid client certificate") from exc
    certificate_key = certificate.public_key().public_bytes(
        serialization.Encoding.DER,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    private_key = key.public_key().public_bytes(
        serialization.Encoding.DER,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    if certificate_key != private_key:
        raise MemoryError("server certificate does not match the local private key")


def _context(server_ca: Path | None, identity: Path | None = None) -> ssl.SSLContext:
    try:
        context = ssl.create_default_context(cafile=str(server_ca.resolve()) if server_ca else None)
        context.minimum_version = ssl.TLSVersion.TLSv1_2
        if identity:
            context.load_cert_chain(certfile=identity, keyfile=identity)
        return context
    except (OSError, ssl.SSLError) as exc:
        raise MemoryError("Company Memory TLS configuration is invalid") from exc


def _request_json(
    url: str,
    *,
    context: ssl.SSLContext,
    method: str = "GET",
    payload: dict[str, Any] | None = None,
    request_id: str,
    opener: Callable[..., Any] = urllib.request.urlopen,
) -> dict[str, Any]:
    encoded = json.dumps(payload, ensure_ascii=False).encode("utf-8") if payload is not None else None
    request = urllib.request.Request(
        url,
        data=encoded,
        headers={
            "Accept": "application/json",
            "X-Request-ID": request_id,
            "User-Agent": "unlimited-skills-company-memory/1",
            **({"Content-Type": "application/json; charset=utf-8"} if encoded is not None else {}),
        },
        method=method,
    )
    try:
        with opener(request, context=context, timeout=20) as response:
            raw = response.read(MAX_RESPONSE_BYTES + 1)
    except urllib.error.HTTPError as exc:
        raw = exc.read(MAX_RESPONSE_BYTES + 1)
        try:
            error = json.loads(raw.decode("utf-8")).get("error", {})
        except (UnicodeDecodeError, json.JSONDecodeError, AttributeError):
            error = {}
        raise MemoryError(
            f"Company Memory rejected request: {error.get('code', exc.code)}: "
            f"{error.get('message', 'request failed')}"
        ) from exc
    except (urllib.error.URLError, TimeoutError) as exc:
        raise MemoryError("Company Memory endpoint is unavailable") from exc
    if len(raw) > MAX_RESPONSE_BYTES:
        raise MemoryError("Company Memory response exceeds the size limit")
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise MemoryError("Company Memory returned invalid JSON") from exc
    if not isinstance(value, dict):
        raise MemoryError("Company Memory returned a non-object response")
    return value


def _load_state(bundle: Path) -> dict[str, Any]:
    try:
        value = json.loads((bundle / "state.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise MemoryError("Company Memory installation state is unavailable") from exc
    if not isinstance(value, dict) or value.get("schema_version") != STATE_SCHEMA:
        raise MemoryError("Company Memory installation state is incompatible")
    return value


@contextlib.contextmanager
def _bundle_lock(bundle: Path, *, timeout: float = 15.0) -> Iterator[None]:
    path = bundle / "maintenance.lock"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+b") as handle:
        handle.seek(0, os.SEEK_END)
        if handle.tell() == 0:
            handle.write(b"0")
            handle.flush()
        deadline = time.monotonic() + timeout
        while True:
            try:
                if os.name == "nt":
                    import msvcrt

                    handle.seek(0)
                    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl

                    fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except (OSError, BlockingIOError):
                if time.monotonic() >= deadline:
                    raise MemoryError("Company Memory maintenance lock timed out")
                time.sleep(0.05)
        try:
            yield
        finally:
            if os.name == "nt":
                import msvcrt

                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _parse_time(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _certificate_needs_renewal(path: Path) -> bool:
    try:
        certificate = x509.load_pem_x509_certificate(path.read_bytes())
    except (OSError, ValueError) as exc:
        raise MemoryError("Company Memory client certificate is unavailable") from exc
    return certificate.not_valid_after_utc <= datetime.now(timezone.utc) + RENEW_BEFORE


def _load_bootstrap(bundle: Path) -> dict[str, Any] | None:
    path = bundle / "bootstrap.json"
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (OSError, json.JSONDecodeError) as exc:
        raise MemoryError("Company Memory bootstrap state is unavailable") from exc
    required = {
        "schema_version",
        "base_url",
        "installation_id",
        "executor_private_key_pem",
        "executor_csr_pem",
        "checker_private_key_pem",
        "checker_csr_pem",
        "server_ca_bundled",
    }
    if not isinstance(value, dict) or value.get("schema_version") != BOOTSTRAP_SCHEMA:
        raise MemoryError("Company Memory bootstrap state is incompatible")
    if set(value) != required:
        raise MemoryError("Company Memory bootstrap state has an invalid schema")
    return value


def _prepare_bootstrap(bundle: Path, base_url: str, server_ca: Path | None) -> dict[str, Any]:
    existing = _load_bootstrap(bundle)
    if existing is not None:
        if existing["base_url"] != base_url:
            raise MemoryError("Company Memory bootstrap belongs to another origin")
        if bool(server_ca) != bool(existing["server_ca_bundled"]):
            raise MemoryError("Company Memory bootstrap TLS mode changed")
        if server_ca and server_ca.read_bytes() != (bundle / "server-ca.crt").read_bytes():
            raise MemoryError("Company Memory bootstrap server CA changed")
        return existing

    installation_id = f"install-{uuid.uuid4().hex}"
    executor_key, executor_csr = _key_csr(f"{installation_id}-executor")
    checker_key, checker_csr = _key_csr(f"{installation_id}-checker")
    if server_ca:
        _atomic_private(bundle / "server-ca.crt", server_ca.read_bytes())
    bootstrap = {
        "schema_version": BOOTSTRAP_SCHEMA,
        "base_url": base_url,
        "installation_id": installation_id,
        "executor_private_key_pem": _private_key_pem(executor_key),
        "executor_csr_pem": executor_csr,
        "checker_private_key_pem": _private_key_pem(checker_key),
        "checker_csr_pem": checker_csr,
        "server_ca_bundled": bool(server_ca),
    }
    _atomic_json(bundle / "bootstrap.json", bootstrap)
    return bootstrap


def _identity_context(bundle: Path, role: str, state: dict[str, Any]) -> ssl.SSLContext:
    server_ca = bundle / "server-ca.crt" if state.get("server_ca_bundled") else None
    return _context(server_ca, bundle / f"{role}-identity.pem")


def _access_receipt_path(bundle: Path, task_id: str, role: str) -> Path:
    digest = hashlib.sha256(task_id.encode("utf-8")).hexdigest()
    return bundle / "access-receipts" / f"{digest}.{role}.json"


def record_access_receipt(
    bundle: Path,
    *,
    task_id: str,
    role: str,
    response: dict[str, Any],
) -> None:
    if role not in {"executor", "checker"} or not STABLE_ID_RE.fullmatch(task_id):
        raise MemoryError("Company Memory task receipt identity is invalid")
    receipt = response.get("access_receipt")
    response_event_id = receipt.get("response_event_id") if isinstance(receipt, dict) else None
    if not isinstance(response_event_id, str) or not response_event_id:
        raise MemoryError("Company Memory did not return a correlated access receipt")
    _atomic_json(
        _access_receipt_path(bundle, task_id, role),
        {
            "schema_version": ACCESS_RECEIPT_SCHEMA,
            "task_id": task_id,
            "role": role,
            "response_event_id": response_event_id,
            "recorded_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        },
    )


def _load_access_receipt(bundle: Path, task_id: str, role: str) -> str:
    try:
        value = json.loads(_access_receipt_path(bundle, task_id, role).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise MemoryError(f"Company Memory {role} task receipt is unavailable") from exc
    if (
        not isinstance(value, dict)
        or value.get("schema_version") != ACCESS_RECEIPT_SCHEMA
        or value.get("task_id") != task_id
        or value.get("role") != role
        or not isinstance(value.get("response_event_id"), str)
    ):
        raise MemoryError(f"Company Memory {role} task receipt is invalid")
    return value["response_event_id"]


def _node_request(
    bundle: Path,
    state: dict[str, Any],
    *,
    role: str,
    path: str,
    method: str = "GET",
    payload: dict[str, Any] | None = None,
    request_id: str,
    opener: Callable[..., Any] = urllib.request.urlopen,
) -> dict[str, Any]:
    return _request_json(
        f"{state['base_url']}{path}",
        context=_identity_context(bundle, role, state),
        method=method,
        payload=payload,
        request_id=request_id,
        opener=opener,
    )


def _provider_config(bundle: Path) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "enabled": True,
        "provider": {
            "id": "company-memory",
            "command": [
                sys.executable,
                "-m",
                "unlimited_skills.memory_provider",
                "--state",
                str(bundle / "state.json"),
            ],
            "capabilities": ["retrieve", "doctor"],
            "timeout_seconds": 15,
            "max_context_chars": 6000,
            "allowed_sensitivities": ["public", "internal", "internal-sanitized"],
            "env_allowlist": ["UNLIMITED_SKILLS_MEMORY_ROLE"],
            "scope": "company-memory-trial",
        },
    }


def _run_canary(bundle: Path, state: dict[str, Any], *, opener=urllib.request.urlopen) -> dict[str, Any]:
    trial_id = state["trial_id"]
    task_id = f"trial-canary:{trial_id}"

    def retrieve(role: str, query: str, request_id: str) -> dict[str, Any]:
        return _node_request(
            bundle,
            state,
            role=role,
            path="/v1/knowledge-requests",
            method="POST",
            payload={
                "schema_version": REQUEST_SCHEMA,
                "request_id": request_id,
                "operation": "retrieve",
                "task_id": task_id,
                "query": query,
            },
            request_id=request_id,
            opener=opener,
        )

    executor_start = retrieve("executor", "trial operating context", "trial:executor:start")
    checker_start = retrieve("checker", "trial checker context", "trial:checker:start")
    outcome = _node_request(
        bundle,
        state,
        role="checker",
        path="/v1/knowledge-requests",
        method="POST",
        payload={
            "schema_version": REQUEST_SCHEMA,
            "request_id": "trial:outcome",
            "operation": "task_outcome",
            "task_id": task_id,
            "outcome": {
                "outcome_key": f"trial-first-value-{trial_id}",
                "task_id": task_id,
                "executor_id": state["executor_workload_id"],
                "executor_access_receipt_id": executor_start["access_receipt"]["response_event_id"],
                "checker": {
                    "verdict": "accepted",
                    "confidence": 1.0,
                    "access_receipt_id": checker_start["access_receipt"]["response_event_id"],
                },
                "summary": "Completed and verified Company Memory trial first value.",
                "evidence_refs": ["artifact-ref:unlimited-skills-trial-canary"],
            },
        },
        request_id="trial:outcome",
        opener=opener,
    )
    if outcome.get("status") not in {"accepted", "duplicate"}:
        raise MemoryError("Company Memory trial outcome was not accepted")
    recalled = retrieve(
        "executor", "Company Memory trial first value", "trial:first-value:retrieve"
    )
    if recalled.get("status") != "ok" or not recalled.get("items"):
        raise MemoryError("Company Memory trial first value was not retrievable")
    status = _node_request(
        bundle,
        state,
        role="executor",
        path="/v1/self/trial",
        request_id="trial:status:after-canary",
        opener=opener,
    )
    if status.get("trial", {}).get("state") != "FIRST_VALUE_VERIFIED":
        raise MemoryError("Company Memory server did not verify first value")
    return status


def init_trial(
    base_url: str,
    *,
    home: Path | None = None,
    server_ca: Path | None = None,
    opener=urllib.request.urlopen,
) -> dict[str, Any]:
    base_url = _origin(base_url)
    home = (home or default_home()).resolve()
    bundle = default_bundle(home)
    state_path = bundle / "state.json"
    if state_path.exists():
        state = _load_state(bundle)
        if state.get("base_url") != base_url:
            raise MemoryError("Company Memory is already initialized for another origin")
        status = memory_status(home=home, opener=opener)
        if status.get("trial", {}).get("state") in {"TRIAL_ACTIVE", "INTEGRATION_VERIFIED"}:
            status = _run_canary(bundle, state, opener=opener)
            state["first_value_verified_at"] = status["trial"]["first_value_verified_at"]
            _atomic_json(state_path, state)
            status = {
                "schema_version": STATE_SCHEMA,
                "status": "ok",
                "trial": status["trial"],
                "provider_configured": True,
                "bundle": str(bundle),
            }
        _atomic_json(home / "business-context-provider.json", _provider_config(bundle))
        return {**status, "idempotent": True}
    bundle.mkdir(parents=True, exist_ok=True)
    bootstrap = _prepare_bootstrap(bundle, base_url, server_ca)
    installation_id = bootstrap["installation_id"]
    executor_key = _private_key(bootstrap["executor_private_key_pem"])
    checker_key = _private_key(bootstrap["checker_private_key_pem"])
    bootstrap_ca = bundle / "server-ca.crt" if bootstrap["server_ca_bundled"] else None
    response = _request_json(
        f"{base_url}/v1/trials",
        context=_context(bootstrap_ca),
        method="POST",
        payload={
            "installation_id": installation_id,
            "executor_csr_pem": bootstrap["executor_csr_pem"],
            "checker_csr_pem": bootstrap["checker_csr_pem"],
        },
        request_id=f"trial:init:{installation_id}",
        opener=opener,
    )
    trial = response.get("trial")
    executor = response.get("executor")
    checker = response.get("checker")
    if not all(isinstance(value, dict) for value in (trial, executor, checker)):
        raise MemoryError("Company Memory trial response is incomplete")
    executor_workload = executor.get("workload")
    checker_workload = checker.get("workload")
    if not all(isinstance(value, dict) for value in (executor_workload, checker_workload)):
        raise MemoryError("Company Memory workload response is incomplete")
    tenant_id = str(trial.get("tenant_id") or "")
    executor_workload_id = str(executor_workload.get("workload_id") or "")
    checker_workload_id = str(checker_workload.get("workload_id") or "")
    if (
        not tenant_id
        or executor_workload.get("tenant_id") != tenant_id
        or checker_workload.get("tenant_id") != tenant_id
        or not executor_workload_id
        or not checker_workload_id
        or executor_workload_id == checker_workload_id
    ):
        raise MemoryError("Company Memory returned inconsistent workload identities")
    _certificate_matches(str(executor.get("certificate_pem") or ""), executor_key)
    _certificate_matches(str(checker.get("certificate_pem") or ""), checker_key)
    _atomic_private(
        bundle / "executor-identity.pem",
        (str(executor["certificate_pem"]) + _private_key_pem(executor_key)).encode("ascii"),
    )
    _atomic_private(
        bundle / "checker-identity.pem",
        (str(checker["certificate_pem"]) + _private_key_pem(checker_key)).encode("ascii"),
    )
    state = {
        "schema_version": STATE_SCHEMA,
        "status": "active",
        "base_url": base_url,
        "installation_id": installation_id,
        "trial_id": trial["trial_id"],
        "tenant_id": tenant_id,
        "expires_at": trial["expires_at"],
        "executor_workload_id": executor_workload_id,
        "checker_workload_id": checker_workload_id,
        "server_ca_bundled": bool(bootstrap["server_ca_bundled"]),
        "initialized_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    }
    _atomic_json(state_path, state)
    (bundle / "bootstrap.json").unlink(missing_ok=True)
    canary = _run_canary(bundle, state, opener=opener)
    state["first_value_verified_at"] = canary["trial"]["first_value_verified_at"]
    _atomic_json(state_path, state)
    _atomic_json(home / "business-context-provider.json", _provider_config(bundle))
    return {
        "schema_version": STATE_SCHEMA,
        "status": "active",
        "trial": canary["trial"],
        "provider_configured": True,
        "bundle": str(bundle),
        "idempotent": False,
    }


def memory_status(*, home: Path | None = None, opener=urllib.request.urlopen) -> dict[str, Any]:
    home = (home or default_home()).resolve()
    bundle = default_bundle(home)
    maintain_before_request(bundle / "state.json", opener=opener)
    state = _load_state(bundle)
    remote = _node_request(
        bundle,
        state,
        role="executor",
        path="/v1/self/trial",
        request_id=f"memory:status:{uuid.uuid4().hex}",
        opener=opener,
    )
    return {
        "schema_version": STATE_SCHEMA,
        "status": "ok",
        "trial": remote["trial"],
        "provider_configured": (home / "business-context-provider.json").is_file(),
        "bundle": str(bundle),
    }


def memory_doctor(*, home: Path | None = None, opener=urllib.request.urlopen) -> dict[str, Any]:
    home = (home or default_home()).resolve()
    bundle = default_bundle(home)
    maintain_before_request(bundle / "state.json", opener=opener)
    state = _load_state(bundle)
    identity = _node_request(
        bundle,
        state,
        role="executor",
        path="/v1/self",
        request_id=f"memory:doctor:self:{uuid.uuid4().hex}",
        opener=opener,
    )
    status = memory_status(home=home, opener=opener)
    checks = {
        "executor_identity": identity.get("principal", {}).get("workload_id")
        == state["executor_workload_id"],
        "tenant_identity": identity.get("principal", {}).get("tenant_id") == state["tenant_id"],
        "first_value": status["trial"].get("state")
        in {"FIRST_VALUE_VERIFIED", "CLAIM_PENDING", "TENANT_CLAIMED", "COMMERCIAL_PENDING", "ACTIVE"},
        "provider_config": (home / "business-context-provider.json").is_file(),
    }
    return {
        "schema_version": STATE_SCHEMA,
        "status": "ok" if all(checks.values()) else "error",
        "checks": checks,
        "trial": status["trial"],
    }


def _rotate_role(bundle: Path, state: dict[str, Any], role: str, *, opener) -> dict[str, Any]:
    pending_key_path = bundle / f"{role}-pending.key"
    pending_csr_path = bundle / f"{role}-pending.csr"
    identity_path = bundle / f"{role}-identity.pem"
    workload_id = state[f"{role}_workload_id"]
    if pending_key_path.exists() != pending_csr_path.exists():
        raise MemoryError(f"{role} pending rotation is incomplete")
    if pending_key_path.is_file():
        key = serialization.load_pem_private_key(pending_key_path.read_bytes(), password=None)
        csr = pending_csr_path.read_text(encoding="ascii")
    else:
        key, csr = _key_csr(workload_id)
        _atomic_private(pending_key_path, _private_key_pem(key).encode("ascii"))
        _atomic_private(pending_csr_path, csr.encode("ascii"))
    response = _node_request(
        bundle,
        state,
        role=role,
        path="/v1/self/certificate:renew",
        method="POST",
        payload={"csr_pem": csr},
        request_id=f"memory:renew:{role}:{uuid.uuid4().hex}",
        opener=opener,
    )
    certificate_pem = str(response.get("certificate_pem") or "")
    _certificate_matches(certificate_pem, key)
    _atomic_private(
        identity_path, (certificate_pem + _private_key_pem(key)).encode("ascii")
    )
    pending_key_path.unlink()
    pending_csr_path.unlink()
    return {"role": role, "not_after": response.get("not_after"), "replayed": response.get("replayed")}


def _renew_unlocked(bundle: Path, state: dict[str, Any], *, opener) -> dict[str, Any]:
    renewed = [_rotate_role(bundle, state, role, opener=opener) for role in ("executor", "checker")]
    return {"schema_version": STATE_SCHEMA, "status": "active", "renewed": renewed}


def memory_renew(*, home: Path | None = None, opener=urllib.request.urlopen) -> dict[str, Any]:
    home = (home or default_home()).resolve()
    bundle = default_bundle(home)
    with _bundle_lock(bundle):
        state = _load_state(bundle)
        return _renew_unlocked(bundle, state, opener=opener)


def maintain_before_request(
    state_path: Path,
    *,
    opener=urllib.request.urlopen,
) -> dict[str, Any]:
    bundle = state_path.resolve().parent
    with _bundle_lock(bundle):
        state = _load_state(bundle)
        roles = ("executor", "checker")
        if any(_certificate_needs_renewal(bundle / f"{role}-identity.pem") for role in roles):
            return _renew_unlocked(bundle, state, opener=opener)
    return {"schema_version": STATE_SCHEMA, "status": "current", "renewed": []}


def maintain_after_request(
    state_path: Path,
    *,
    opener=urllib.request.urlopen,
) -> dict[str, Any]:
    bundle = state_path.resolve().parent
    state = _load_state(bundle)
    if state.get("handoff_state") in {
        "CLAIM_PENDING",
        "TENANT_CLAIMED",
        "COMMERCIAL_PENDING",
        "ACTIVE",
    }:
        return {
            "schema_version": STATE_SCHEMA,
            "status": "already_requested",
            "trial_state": state["handoff_state"],
        }
    expires_at = _parse_time(str(state.get("expires_at") or ""))
    if datetime.now(timezone.utc) < expires_at - HANDOFF_BEFORE:
        return {"schema_version": STATE_SCHEMA, "status": "not_due"}
    status = memory_status(home=bundle.parent, opener=opener)
    trial_state = status.get("trial", {}).get("state")
    if trial_state == "FIRST_VALUE_VERIFIED":
        result = memory_handoff(home=bundle.parent, opener=opener)
        trial_state = result.get("trial", {}).get("state")
    if trial_state in {"CLAIM_PENDING", "TENANT_CLAIMED", "COMMERCIAL_PENDING", "ACTIVE"}:
        with _bundle_lock(bundle):
            current = _load_state(bundle)
            current["handoff_observed_at"] = datetime.now(timezone.utc).isoformat().replace(
                "+00:00", "Z"
            )
            current["handoff_state"] = trial_state
            _atomic_json(bundle / "state.json", current)
    return {"schema_version": STATE_SCHEMA, "status": "ok", "trial_state": trial_state}


def memory_maintain(*, home: Path | None = None, opener=urllib.request.urlopen) -> dict[str, Any]:
    home = (home or default_home()).resolve()
    state_path = default_bundle(home) / "state.json"
    renewal = maintain_before_request(state_path, opener=opener)
    handoff = maintain_after_request(state_path, opener=opener)
    return {
        "schema_version": STATE_SCHEMA,
        "status": "ok",
        "renewal": renewal,
        "handoff": handoff,
    }


def _checked_outcome(path: Path) -> dict[str, Any]:
    try:
        if not path.is_file():
            raise MemoryError("Company Memory checked outcome file is invalid")
        with path.open("rb") as handle:
            raw = handle.read(MAX_OUTCOME_BYTES + 1)
        if len(raw) > MAX_OUTCOME_BYTES:
            raise MemoryError("Company Memory checked outcome file is invalid")
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise MemoryError("Company Memory checked outcome JSON is invalid") from exc
    required = {"schema_version", "task_id", "outcome_key", "verdict", "summary", "evidence_refs"}
    allowed = required | {"confidence"}
    if not isinstance(value, dict) or set(value) < required or not set(value) <= allowed:
        raise MemoryError("Company Memory checked outcome schema is invalid")
    task_id = value.get("task_id")
    outcome_key = value.get("outcome_key")
    verdict = value.get("verdict")
    summary = value.get("summary")
    evidence_refs = value.get("evidence_refs")
    confidence = value.get("confidence")
    text_values = (outcome_key, summary)
    if (
        value.get("schema_version") != OUTCOME_SCHEMA
        or not isinstance(task_id, str)
        or not STABLE_ID_RE.fullmatch(task_id)
        or not isinstance(outcome_key, str)
        or not 1 <= len(outcome_key) <= 240
        or verdict not in {"accepted", "returned"}
        or not isinstance(summary, str)
        or not 1 <= len(summary) <= 6_000
        or any(any(ord(character) < 32 or ord(character) == 127 for character in text) for text in text_values)
        or not isinstance(evidence_refs, list)
        or not 1 <= len(evidence_refs) <= 100
        or any(
            not isinstance(item, str)
            or not 1 <= len(item) <= 1_000
            or any(ord(character) < 32 or ord(character) == 127 for character in item)
            for item in evidence_refs
        )
        or (
            confidence is not None
            and (isinstance(confidence, bool) or not isinstance(confidence, (int, float)) or not 0 <= confidence <= 1)
        )
    ):
        raise MemoryError("Company Memory checked outcome fields are invalid")
    return value


def memory_outcome(
    outcome_file: Path,
    *,
    home: Path | None = None,
    opener=urllib.request.urlopen,
) -> dict[str, Any]:
    home = (home or default_home()).resolve()
    bundle = default_bundle(home)
    maintain_before_request(bundle / "state.json", opener=opener)
    state = _load_state(bundle)
    checked = _checked_outcome(outcome_file.resolve())
    task_id = checked["task_id"]
    checker = {
        "verdict": checked["verdict"],
        "access_receipt_id": _load_access_receipt(bundle, task_id, "checker"),
    }
    if "confidence" in checked:
        checker["confidence"] = checked["confidence"]
    request_id = f"memory:outcome:{uuid.uuid4().hex}"
    response = _node_request(
        bundle,
        state,
        role="checker",
        path="/v1/knowledge-requests",
        method="POST",
        payload={
            "schema_version": REQUEST_SCHEMA,
            "request_id": request_id,
            "operation": "task_outcome",
            "task_id": task_id,
            "outcome": {
                "outcome_key": checked["outcome_key"],
                "task_id": task_id,
                "executor_id": state["executor_workload_id"],
                "executor_access_receipt_id": _load_access_receipt(
                    bundle, task_id, "executor"
                ),
                "checker": checker,
                "summary": checked["summary"],
                "evidence_refs": checked["evidence_refs"],
            },
        },
        request_id=request_id,
        opener=opener,
    )
    status = str(response.get("status") or "")
    if status not in {"accepted", "returned_recorded", "duplicate"}:
        raise MemoryError("Company Memory did not record the checked task outcome")
    return {
        "schema_version": STATE_SCHEMA,
        "status": status,
        **{
            key: response[key]
            for key in ("source_ref", "completion_receipt")
            if key in response
        },
    }


def _empty_action(
    action: str,
    *,
    home: Path | None = None,
    opener=urllib.request.urlopen,
) -> dict[str, Any]:
    home = (home or default_home()).resolve()
    bundle = default_bundle(home)
    maintain_before_request(bundle / "state.json", opener=opener)
    state = _load_state(bundle)
    response = _node_request(
        bundle,
        state,
        role="executor",
        path=f"/v1/self/trial:{action}",
        method="POST",
        payload={},
        request_id=f"memory:{action}:{uuid.uuid4().hex}",
        opener=opener,
    )
    return {"schema_version": STATE_SCHEMA, **response}


def memory_handoff(*, home: Path | None = None, opener=urllib.request.urlopen) -> dict[str, Any]:
    return _empty_action("handoff", home=home, opener=opener)


def memory_revoke(*, home: Path | None = None, opener=urllib.request.urlopen) -> dict[str, Any]:
    home = (home or default_home()).resolve()
    config_path = home / "business-context-provider.json"
    try:
        return _empty_action("revoke", home=home, opener=opener)
    finally:
        if config_path.is_file():
            config = json.loads(config_path.read_text(encoding="utf-8"))
            config["enabled"] = False
            _atomic_json(config_path, config)


def _emit(value: dict[str, Any], as_json: bool) -> int:
    if as_json:
        print(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print(f"Company Memory: {value.get('status', 'unknown')}")
        trial = value.get("trial")
        if isinstance(trial, dict):
            print(f"Trial: {trial.get('state')} until {trial.get('expires_at')}")
    return 0 if value.get("status") not in {"error", "unavailable"} else 2


def command(args: argparse.Namespace) -> int:
    home = Path(args.home).expanduser() if getattr(args, "home", "") else None
    try:
        if args.memory_command == "init":
            result = init_trial(
                args.url,
                home=home,
                server_ca=Path(args.server_ca).expanduser() if args.server_ca else None,
            )
        elif args.memory_command == "status":
            result = memory_status(home=home)
        elif args.memory_command == "doctor":
            result = memory_doctor(home=home)
        elif args.memory_command == "renew":
            result = memory_renew(home=home)
        elif args.memory_command == "outcome":
            result = memory_outcome(Path(args.file).expanduser(), home=home)
        elif args.memory_command == "maintain":
            result = memory_maintain(home=home)
        elif args.memory_command == "revoke":
            result = memory_revoke(home=home)
        else:
            result = memory_handoff(home=home)
        return _emit(result, args.json)
    except MemoryError as exc:
        return _emit(
            {"schema_version": STATE_SCHEMA, "status": "error", "reason": str(exc)},
            args.json,
        )
    except (OSError, ValueError):
        return _emit(
            {
                "schema_version": STATE_SCHEMA,
                "status": "error",
                "reason": "Company Memory local state operation failed",
            },
            args.json,
        )
