"""Verify the 0.6.8 signed-receipt transport from an exact installed wheel."""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import tempfile
import venv
import zipfile
from pathlib import Path


PROVIDER = r'''
import json, os, pathlib, sys
request = json.load(sys.stdin)
if os.environ.get("REQUEST_LOG"):
    pathlib.Path(os.environ["REQUEST_LOG"]).write_text(json.dumps(request), encoding="utf-8")
response = {
    "schema_version": "unlimited-skills.business-context-response.v1",
    "request_id": request["request_id"],
}
if request["operation"] == "completion_receipt":
    response.update({
        "status": "queued",
        "receipt_id": "a" * 64,
        "operation_id": "op-" + "a" * 32,
        "committed": False,
        "indexed": False,
        "visible": False,
    })
elif request["operation"] == "doctor":
    response.update({"status": "ok", "writeback": "signed_receipt_v1"})
else:
    response.update({"status": "ignored"})
print(json.dumps(response))
'''


def receipt() -> dict:
    return {
        "schema_version": "unlimited-skills.accepted-completion-receipt.v1",
        "audience": "owner-company-memory",
        "purpose": "completion_memory",
        "project_scope": "core-ai4sale",
        "entity": "core-ai4sale",
        "sensitivity": "internal",
        "issued_at": "2026-07-11T10:00:00Z",
        "summary": "The release was published and independently verified.",
        "producer": {"id": "codex-executor"},
        "artifact": {
            "type": "release",
            "logical_ref": "pypi:unlimited-skills",
            "canonical_ref": "https://pypi.org/project/unlimited-skills/0.6.8/",
            "revision": "0.6.8",
            "digest": "sha256:" + "a" * 64,
            "supersedes": None,
        },
        "destination": {"status": "published", "receipt_id": "pypi:unlimited-skills@0.6.8"},
        "checker": {
            "id": "github-actions:ci",
            "status": "passed",
            "evidence_digest": "sha256:" + "b" * 64,
        },
        "signature": {"algorithm": "ed25519", "key_id": "release-operator-2026-01", "value": "A" * 86},
    }


def python(root: Path) -> Path:
    return root / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def cli(root: Path) -> Path:
    return root / ("Scripts/unlimited-skills.exe" if os.name == "nt" else "bin/unlimited-skills")


def run(command: list[str], *, cwd: Path, env: dict[str, str] | None = None, input_text: str | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=cwd,
        env=env,
        input=input_text,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=300,
    )


def payload(proc: subprocess.CompletedProcess[str], label: str) -> dict:
    if proc.returncode != 0:
        raise RuntimeError(f"{label} failed: {proc.stderr[-1000:]}")
    value = json.loads(proc.stdout)
    if not isinstance(value, dict):
        raise RuntimeError(f"{label} returned non-object JSON")
    return value


def verify(wheel: Path, expected_version: str) -> dict:
    errors: list[str] = []
    with zipfile.ZipFile(wheel) as archive:
        metadata_name = next(name for name in archive.namelist() if name.endswith(".dist-info/METADATA"))
        metadata = archive.read(metadata_name).decode("utf-8", errors="replace")
    if f"This is `v{expected_version}`" not in metadata:
        errors.append("wheel METADATA long description has a stale release version")
    if "explicit, bounded signed receipt" not in metadata or "assistant prose" not in metadata:
        errors.append("wheel METADATA lacks the v0.6.8 signed-receipt safety statement")
    with tempfile.TemporaryDirectory(prefix="uls-v068-receipt-wheel-") as directory:
        work = Path(directory)
        env_root = work / "venv"
        venv.EnvBuilder(with_pip=True).create(env_root)
        py = python(env_root)
        executable = cli(env_root)
        installed = run([str(py), "-m", "pip", "install", "--disable-pip-version-check", str(wheel)], cwd=work)
        if installed.returncode != 0:
            raise RuntimeError(f"wheel install failed: {installed.stderr[-1500:]}")
        version = run([str(executable), "--version"], cwd=work)
        if expected_version not in version.stdout:
            errors.append("installed CLI version mismatch")

        provider = work / "provider.py"
        request_log = work / "request.json"
        provider.write_text(PROVIDER, encoding="utf-8")
        config = work / "provider-config.json"
        config.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "provider": {
                        "id": "receipt-wheel-fixture",
                        "command": [str(py), str(provider)],
                        "capabilities": ["completion_receipt", "doctor"],
                        "timeout_seconds": 2,
                        "scope": "core-ai4sale",
                        "env": {"REQUEST_LOG": str(request_log)},
                    },
                }
            ),
            encoding="utf-8",
        )
        env = {**os.environ, "UNLIMITED_SKILLS_CONTEXT_PROVIDER_CONFIG": str(config)}
        receipt_file = work / "receipt.json"
        receipt_file.write_text(json.dumps(receipt()), encoding="utf-8")
        from_file = payload(
            run(
                [str(executable), "context", "completion-receipt", "--file", str(receipt_file), "--json"],
                cwd=work,
                env=env,
            ),
            "receipt file",
        )
        from_stdin = payload(
            run(
                [str(executable), "context", "completion-receipt", "--stdin", "--json"],
                cwd=work,
                env=env,
                input_text=json.dumps(receipt()),
            ),
            "receipt stdin",
        )
        recorded = json.loads(request_log.read_text(encoding="utf-8"))
        doctor = payload(
            run([str(executable), "context", "doctor", "--json"], cwd=work, env=env),
            "provider doctor",
        )
        request_log.unlink()
        invalid = receipt()
        invalid["signature"]["value"] = "invalid"
        rejected = payload(
            run(
                [str(executable), "context", "completion-receipt", "--stdin", "--json"],
                cwd=work,
                env=env,
                input_text=json.dumps(invalid),
            ),
            "invalid signature envelope",
        )
        duplicate_property = payload(
            run(
                [str(executable), "context", "completion-receipt", "--stdin", "--json"],
                cwd=work,
                env=env,
                input_text='{"schema_version":"x","schema_version":"y"}',
            ),
            "duplicate JSON property",
        )

        if from_file.get("status") != "queued" or from_file.get("visible") is not False:
            errors.append("file transport did not return enqueue-only state")
        if from_stdin.get("status") != "queued" or from_stdin.get("committed") is not False:
            errors.append("stdin transport did not return enqueue-only state")
        if recorded.get("operation") != "completion_receipt" or recorded.get("receipt") != receipt():
            errors.append("installed client did not forward the exact receipt")
        if rejected.get("status") != "rejected" or request_log.exists():
            errors.append("malformed signature envelope reached the provider")
        if duplicate_property.get("status") != "rejected":
            errors.append("duplicate JSON property was not rejected")
        if doctor.get("status") != "ok" or doctor.get("writeback") != "signed_receipt_v1":
            errors.append("installed doctor did not prove signed receipt writeback readiness")
        if any(key in from_file for key in ("summary", "signature", "receipt")):
            errors.append("public status response leaked the receipt envelope")

        return {
            "schema_version": 1,
            "ok": not errors,
            "version": expected_version,
            "wheel": wheel.name,
            "file_status": from_file.get("status"),
            "stdin_status": from_stdin.get("status"),
            "malformed_status": rejected.get("status"),
            "duplicate_property_status": duplicate_property.get("status"),
            "provider_called_only_for_valid_receipts": not request_log.exists(),
            "doctor_writeback": doctor.get("writeback"),
            "errors": errors,
        }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--wheel", type=Path, required=True)
    parser.add_argument("--expected-version", default="0.6.8")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    report = verify(args.wheel.resolve(), args.expected_version)
    print(json.dumps(report, indent=2))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
