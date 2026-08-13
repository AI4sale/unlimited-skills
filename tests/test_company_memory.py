from __future__ import annotations

import json
import ssl
import urllib.error
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

from unlimited_skills.cli import build_parser
from unlimited_skills.memory import (
    MemoryError,
    init_trial,
    memory_doctor,
    memory_outcome,
    memory_revoke,
)
from unlimited_skills.memory_provider import provide


class Response:
    def __init__(self, payload: dict):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self, _limit: int) -> bytes:
        return json.dumps(self.payload).encode("utf-8")


class FakeMemoryNode:
    def __init__(self, *, lose_first_trial_response: bool = False, certificate_hours: int = 24):
        self.lose_first_trial_response = lose_first_trial_response
        self.certificate_hours = certificate_hours
        self.trial_requests = 0
        self.renewals = 0
        self.installations: dict[str, dict] = {}
        self.trial_state = "TRIAL_ACTIVE"
        self.source_ref = "tenant-memory/trial-outcome.md"
        self.outcomes: list[dict] = []
        self.ca_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        self.ca_subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Test CA")])

    def _certificate(self, csr_pem: str, *, hours: int | None = None) -> str:
        csr = x509.load_pem_x509_csr(csr_pem.encode("ascii"))
        now = datetime.now(timezone.utc)
        certificate = (
            x509.CertificateBuilder()
            .subject_name(csr.subject)
            .issuer_name(self.ca_subject)
            .public_key(csr.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now - timedelta(minutes=1))
            .not_valid_after(now + timedelta(hours=hours or self.certificate_hours))
            .sign(self.ca_key, hashes.SHA256())
        )
        return certificate.public_bytes(serialization.Encoding.PEM).decode("ascii")

    def _trial_payload(self, request: dict) -> dict:
        installation = request["installation_id"]
        if installation not in self.installations:
            suffix = installation.removeprefix("install-")[:16]
            self.installations[installation] = {
                "schema_version": "ais-os-company-memory-trial.v1",
                "status": "active",
                "trial": {
                    "trial_id": f"trl-{suffix}",
                    "tenant_id": f"trial-{suffix}",
                    "state": self.trial_state,
                    "created_at": "2026-08-13T00:00:00Z",
                    "expires_at": "2026-08-27T00:00:00Z",
                    "request_count_today": 0,
                    "write_count": 0,
                    "first_value_verified_at": None,
                    "human_action_required": False,
                },
                "executor": {
                    "workload": {
                        "workload_id": f"wld-executor-{suffix}",
                        "tenant_id": f"trial-{suffix}",
                    },
                    "certificate_pem": self._certificate(request["executor_csr_pem"]),
                },
                "checker": {
                    "workload": {
                        "workload_id": f"wld-checker-{suffix}",
                        "tenant_id": f"trial-{suffix}",
                    },
                    "certificate_pem": self._certificate(request["checker_csr_pem"]),
                },
            }
        return self.installations[installation]

    def __call__(self, request, *, context: ssl.SSLContext, timeout: int):
        del context, timeout
        path = request.full_url.removeprefix("https://memory.example")
        body = json.loads(request.data) if request.data else {}
        request_id = request.headers.get("X-request-id", "")
        if path == "/v1/trials":
            self.trial_requests += 1
            payload = self._trial_payload(body)
            if self.lose_first_trial_response:
                self.lose_first_trial_response = False
                raise urllib.error.URLError("response lost after provisioning")
            return Response(payload)
        if path == "/v1/knowledge-requests" and body.get("operation") == "task_outcome":
            self.outcomes.append(body)
            self.trial_state = "INTEGRATION_VERIFIED"
            return Response(
                {
                    "status": "accepted",
                    "source_ref": self.source_ref,
                    "completion_receipt": {"receipt_id": "completion-1"},
                }
            )
        if path == "/v1/knowledge-requests":
            if request_id == "trial:first-value:retrieve":
                self.trial_state = "FIRST_VALUE_VERIFIED"
                return Response(
                    {
                        "status": "ok",
                        "items": [{"source_ref": self.source_ref, "excerpt": "verified"}],
                        "access_receipt": {"response_event_id": "KA-first-value"},
                    }
                )
            return Response(
                {
                    "status": "ok",
                    "items": [{"source_ref": "overlay/trial.md", "excerpt": "ready"}],
                    "access_receipt": {"response_event_id": f"KA-{request_id}"},
                }
            )
        if path == "/v1/self/certificate:renew":
            self.renewals += 1
            return Response(
                {
                    "certificate_pem": self._certificate(body["csr_pem"], hours=24),
                    "not_after": "2026-08-14T00:00:00Z",
                    "replayed": False,
                }
            )
        if path == "/v1/self/trial:handoff":
            self.trial_state = "CLAIM_PENDING"
            trial = next(iter(self.installations.values()))["trial"].copy()
            trial["state"] = self.trial_state
            return Response({"status": "handoff_pending", "trial": trial})
        if path == "/v1/self/trial":
            trial = next(iter(self.installations.values()))["trial"].copy()
            trial["state"] = self.trial_state
            if self.trial_state == "FIRST_VALUE_VERIFIED":
                trial["first_value_verified_at"] = "2026-08-13T00:01:00Z"
            return Response({"status": "ok", "trial": trial})
        if path == "/v1/self":
            installation = next(iter(self.installations.values()))
            return Response(
                {
                    "principal": {
                        "workload_id": installation["executor"]["workload"]["workload_id"],
                        "tenant_id": installation["trial"]["tenant_id"],
                    }
                }
            )
        raise AssertionError(f"unexpected request: {path} {body}")


def test_one_command_trial_creates_independent_identities_and_first_value(tmp_path: Path) -> None:
    server = FakeMemoryNode()

    result = init_trial("https://memory.example", home=tmp_path, opener=server)

    assert result["trial"]["state"] == "FIRST_VALUE_VERIFIED"
    bundle = tmp_path / "company-memory"
    assert (bundle / "executor-identity.pem").read_bytes() != (
        bundle / "checker-identity.pem"
    ).read_bytes()
    assert not (bundle / "bootstrap.json").exists()
    assert (tmp_path / "business-context-provider.json").is_file()
    assert memory_doctor(home=tmp_path, opener=server)["status"] == "ok"

    replay = init_trial("https://memory.example", home=tmp_path, opener=server)
    assert replay["idempotent"] is True
    assert len(server.installations) == 1


def test_lost_trial_response_reuses_persisted_installation_and_keys(tmp_path: Path) -> None:
    server = FakeMemoryNode(lose_first_trial_response=True)

    with pytest.raises(MemoryError, match="endpoint is unavailable"):
        init_trial("https://memory.example", home=tmp_path, opener=server)

    bootstrap = json.loads(
        (tmp_path / "company-memory" / "bootstrap.json").read_text(encoding="utf-8")
    )
    assert not (tmp_path / "business-context-provider.json").exists()
    installation_id = bootstrap["installation_id"]
    result = init_trial("https://memory.example", home=tmp_path, opener=server)

    assert result["trial"]["state"] == "FIRST_VALUE_VERIFIED"
    assert list(server.installations) == [installation_id]
    assert server.trial_requests == 2


def test_revoke_disables_local_provider_even_if_server_response_is_lost(tmp_path: Path) -> None:
    server = FakeMemoryNode()
    init_trial("https://memory.example", home=tmp_path, opener=server)

    def lost_response(*_args, **_kwargs):
        raise urllib.error.URLError("response lost")

    with pytest.raises(MemoryError, match="endpoint is unavailable"):
        memory_revoke(home=tmp_path, opener=lost_response)

    config = json.loads(
        (tmp_path / "business-context-provider.json").read_text(encoding="utf-8")
    )
    assert config["enabled"] is False


def test_provider_roles_record_receipts_and_checked_outcome_derives_authority(tmp_path: Path) -> None:
    server = FakeMemoryNode()
    init_trial("https://memory.example", home=tmp_path, opener=server)
    server.outcomes.clear()
    state_path = tmp_path / "company-memory" / "state.json"
    task_id = "customer-task-42"
    base_request = {
        "schema_version": "unlimited-skills.business-context-request.v1",
        "operation": "retrieve",
        "task_id": task_id,
        "query": "task evidence",
    }
    provide(
        {**base_request, "request_id": "executor-start"},
        state_path,
        opener=server,
        env={"UNLIMITED_SKILLS_MEMORY_ROLE": "executor"},
    )
    provide(
        {**base_request, "request_id": "checker-start"},
        state_path,
        opener=server,
        env={"UNLIMITED_SKILLS_MEMORY_ROLE": "checker"},
    )
    checked = tmp_path / "checked-outcome.json"
    checked.write_text(
        json.dumps(
            {
                "schema_version": "unlimited-skills.checked-task-outcome.v1",
                "task_id": task_id,
                "outcome_key": "customer-task-42:accepted",
                "verdict": "accepted",
                "confidence": 0.95,
                "summary": "Customer task completed and independently checked.",
                "evidence_refs": ["artifact-ref:customer-task-42"],
            }
        ),
        encoding="utf-8",
    )

    result = memory_outcome(checked, home=tmp_path, opener=server)

    assert result["status"] == "accepted"
    submitted = server.outcomes[-1]
    state = json.loads(state_path.read_text(encoding="utf-8"))
    assert submitted["outcome"]["executor_id"] == state["executor_workload_id"]
    assert submitted["outcome"]["executor_access_receipt_id"] == "KA-executor-start"
    assert submitted["outcome"]["checker"]["access_receipt_id"] == "KA-checker-start"
    assert "tenant_id" not in submitted
    assert "id" not in submitted["outcome"]["checker"]


def test_checked_outcome_requires_both_task_bound_role_receipts(tmp_path: Path) -> None:
    server = FakeMemoryNode()
    init_trial("https://memory.example", home=tmp_path, opener=server)
    checked = tmp_path / "checked-outcome.json"
    checked.write_text(
        json.dumps(
            {
                "schema_version": "unlimited-skills.checked-task-outcome.v1",
                "task_id": "missing-receipts-task",
                "outcome_key": "missing-receipts-task:accepted",
                "verdict": "accepted",
                "summary": "Checked but missing correlated start receipts.",
                "evidence_refs": ["artifact-ref:missing"],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(MemoryError, match="checker task receipt is unavailable"):
        memory_outcome(checked, home=tmp_path, opener=server)


def test_active_use_rotates_expiring_certificates_and_requests_due_handoff(tmp_path: Path) -> None:
    server = FakeMemoryNode(certificate_hours=1)
    init_trial("https://memory.example", home=tmp_path, opener=server)
    state_path = tmp_path / "company-memory" / "state.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    state["expires_at"] = (
        datetime.now(timezone.utc) + timedelta(hours=12)
    ).isoformat().replace("+00:00", "Z")
    state_path.write_text(json.dumps(state), encoding="utf-8")

    provide(
        {
            "schema_version": "unlimited-skills.business-context-request.v1",
            "request_id": "maintenance-retrieve",
            "operation": "retrieve",
            "task_id": "maintenance-task",
            "query": "active memory use",
        },
        state_path,
        opener=server,
        env={"UNLIMITED_SKILLS_MEMORY_ROLE": "executor"},
    )

    assert server.renewals == 2
    assert server.trial_state == "CLAIM_PENDING"
    maintained = json.loads(state_path.read_text(encoding="utf-8"))
    assert maintained["handoff_state"] == "CLAIM_PENDING"


def test_memory_cli_requires_explicit_trial_and_https_origin() -> None:
    parser = build_parser()
    args = parser.parse_args(
        ["memory", "init", "--trial", "--url", "https://memory.example", "--json"]
    )
    assert args.memory_command == "init"
    outcome_args = parser.parse_args(
        ["memory", "outcome", "--file", "checked-outcome.json", "--json"]
    )
    assert outcome_args.memory_command == "outcome"
    with pytest.raises(SystemExit):
        parser.parse_args(["memory", "init", "--url", "https://memory.example"])
    with pytest.raises(MemoryError, match="HTTPS origin"):
        init_trial("http://memory.example")
