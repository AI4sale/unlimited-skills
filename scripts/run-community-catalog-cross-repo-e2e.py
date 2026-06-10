from __future__ import annotations

import argparse
import base64
import io
import json
import os
import subprocess
import sys
import tempfile
import urllib.error
import zipfile
from pathlib import Path
from unittest.mock import patch

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from unlimited_skills.community import CommunityClient
from unlimited_skills.registration import RegistrationState, base64_urlsafe_encode, with_install_identity
from unlimited_skills.signatures import sign_manifest_for_tests
from unlimited_skills.updates import sha256_file


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REGISTRY_REPO = Path(os.environ.get("UNLIMITED_SKILLS_REGISTRY_REPO", r"D:\git\unlimited-skills-registry"))


class FakeResponse:
    def __init__(self, data: bytes) -> None:
        self._stream = io.BytesIO(data)

    def __enter__(self) -> "FakeResponse":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None

    def read(self, size: int = -1) -> bytes:
        return self._stream.read(size)


def run(command: list[str], *, cwd: Path) -> str:
    completed = subprocess.run(command, cwd=cwd, text=True, encoding="utf-8", errors="replace", capture_output=True, check=False)
    if completed.returncode != 0:
        raise RuntimeError(
            "command failed: "
            + " ".join(command)
            + "\nstdout:\n"
            + completed.stdout
            + "\nstderr:\n"
            + completed.stderr
        )
    return completed.stdout


def make_archive(root: Path) -> tuple[Path, str]:
    archive = root / "community-approved.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr(
            "community/skills/community-sample/SKILL.md",
            "---\nname: community-sample\ndescription: Approved community sample\n---\n\n# Community Sample\n",
        )
    return archive, sha256_file(archive)


def signed_public_payload(payload: dict, private_key: Ed25519PrivateKey) -> dict:
    return sign_manifest_for_tests({"schema_version": 1, "manifest_type": "community-catalog", **payload}, private_key, key_id="community-e2e-key")


def public_client_flow(tmp: Path, *, submission_id: str) -> dict[str, object]:
    archive, digest = make_archive(tmp)
    private_key = Ed25519PrivateKey.generate()
    public_key = private_key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    os.environ["UNLIMITED_SKILLS_MANIFEST_PUBLIC_KEYS"] = f"community-e2e-key:{base64_urlsafe_encode(public_key)}"
    state = with_install_identity(
        RegistrationState(
            install_id="uls_inst_community_e2e",
            server_url="https://community.example.test",
            license_token="tok_community_e2e",
        )
    )
    root = tmp / "library"
    seen: list[str] = []

    def fake_urlopen(request, timeout=30.0):
        url = request.full_url if hasattr(request, "full_url") else str(request)
        seen.append(url)
        if url.endswith("/v1/community/submission-status"):
            return FakeResponse(json.dumps({"submission_id": submission_id, "status": "published"}).encode("utf-8"))
        if url.endswith("/v1/community/review-notes"):
            return FakeResponse(json.dumps({"submission_id": submission_id, "reviewer_notes": "approved for canary"}).encode("utf-8"))
        if url.endswith("/v1/community/withdraw"):
            return FakeResponse(json.dumps({"submission_id": submission_id, "status": "withdrawn"}).encode("utf-8"))
        if url.endswith("/v1/community/install"):
            return FakeResponse(
                json.dumps(
                    signed_public_payload(
                        {
                            "item": {
                                "item_id": "community-sample-pack",
                                "kind": "skill-pack",
                                "name": "community-sample",
                                "status": "published",
                                "channel": "canary",
                            },
                            "install_plan": {
                                "collection": "community",
                                "version": "0.1.0",
                                "archive_url": "https://community.example.test/community-approved.zip",
                                "sha256": digest,
                                "skill_count": 1,
                            },
                        },
                        private_key,
                    )
                ).encode("utf-8")
            )
        if url.endswith("/community-approved.zip"):
            return FakeResponse(archive.read_bytes())
        raise urllib.error.HTTPError(url, 404, "Not Found", hdrs=None, fp=io.BytesIO(b"{}"))

    client = CommunityClient(state)
    with patch("urllib.request.urlopen", fake_urlopen):
        status = client.get_submission_status(submission_id)
        notes = client.review_notes(submission_id)
        install = client.install_community_item(root, item_id="community-sample-pack")
        withdrawn = client.withdraw_submission(submission_id)

    return {
        "status": status.get("status"),
        "review_notes_present": bool(notes.get("reviewer_notes")),
        "install_collection": install.collection,
        "installed": install.installed,
        "withdraw_status": withdrawn.get("status"),
        "production_hosted_calls": any("unlimited.ai4.sale" in url for url in seen),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Run community catalog cross-repo fixture E2E.")
    parser.add_argument("--registry-repo", type=Path, default=DEFAULT_REGISTRY_REPO)
    parser.add_argument("--fixture-mode", action="store_true", help="Required; blocks production hosted calls.")
    parser.add_argument("--temp-home", action="store_true", help="Run with isolated temp state.")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    if not args.fixture_mode:
        raise SystemExit("--fixture-mode is required for this E2E.")
    registry_repo = args.registry_repo.expanduser()
    if not registry_repo.is_dir():
        raise SystemExit(f"Registry repo not found: {registry_repo}")
    sample = registry_repo / "examples" / "community" / "sample-safe"
    if not sample.is_dir():
        raise SystemExit(f"Registry community sample fixture not found: {sample}")

    with tempfile.TemporaryDirectory(prefix="uls-community-e2e-", ignore_cleanup_errors=True) as tmp_name:
        tmp = Path(tmp_name)
        if args.temp_home:
            os.environ["UNLIMITED_SKILLS_HOME"] = str(tmp / ".unlimited-skills")
        db_url = "sqlite:///" + str(tmp / "registry.sqlite3")
        artifact_root = tmp / "registry-artifacts"
        registry_python = registry_repo / ".venv" / "Scripts" / "python.exe"
        if not registry_python.is_file():
            registry_python = Path(sys.executable)
        submit = json.loads(
            run(
                [
                    str(registry_python),
                    "scripts/community-submission-review.py",
                    "--fixture-mode",
                    "--db-url",
                    db_url,
                    "--artifact-root",
                    str(artifact_root),
                    "--json",
                    "submit",
                    str(sample),
                ],
                cwd=registry_repo,
            )
        )
        submission_id = submit["submission"]["submission_id"]
        approve = json.loads(
            run(
                [
                    str(registry_python),
                    "scripts/community-submission-review.py",
                    "--fixture-mode",
                    "--db-url",
                    db_url,
                    "--artifact-root",
                    str(artifact_root),
                    "--json",
                    "approve",
                    submission_id,
                ],
                cwd=registry_repo,
            )
        )
        publish = json.loads(
            run(
                [
                    str(registry_python),
                    "scripts/community-submission-review.py",
                    "--fixture-mode",
                    "--db-url",
                    db_url,
                    "--artifact-root",
                    str(artifact_root),
                    "--json",
                    "publish-canary",
                    submission_id,
                ],
                cwd=registry_repo,
            )
        )
        artifacts = sorted((artifact_root / "community-catalog" / "canary").glob("*.json"))
        if len(artifacts) != 1:
            raise RuntimeError("Expected exactly one signed canary artifact.")
        artifact = json.loads(artifacts[0].read_text(encoding="utf-8"))
        serialized_artifact = json.dumps(artifact, sort_keys=True)
        if "manifest_signature" not in artifact:
            raise RuntimeError("Registry canary artifact is not signed.")
        if "When to Use" in serialized_artifact or "content_base64" in serialized_artifact:
            raise RuntimeError("Registry canary artifact leaked skill body content.")

        client = public_client_flow(tmp, submission_id=submission_id)
        payload = {
            "schema_version": 1,
            "status": "passed",
            "mode": "fixture",
            "registry_repo": str(registry_repo),
            "submission_id": submission_id,
            "registry_review_status": approve["submission"]["status"],
            "registry_publish_status": publish["submission"]["status"],
            "signed_canary_artifact": str(artifacts[0]),
            "public_client": client,
            "production_hosted_calls": bool(client["production_hosted_calls"]),
        }
        if payload["production_hosted_calls"]:
            raise RuntimeError("Fixture E2E attempted production hosted calls.")
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
