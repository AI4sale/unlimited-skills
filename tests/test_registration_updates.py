from __future__ import annotations

import io
import json
import os
import stat
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from unlimited_skills.registration import (
    RegistrationError,
    RegistrationState,
    build_registration_payload,
    post_json,
    save_registration,
    with_install_identity,
    with_install_id,
)
from unlimited_skills.team import TeamClient, TeamState, save_team_state
from unlimited_skills.updates import (
    RegistrationRequired,
    UpdateClient,
    UpdateError,
    current_collection_state,
    download_file,
    parse_updates,
    safe_extract_zip,
    sha256_file,
)


class FakeResponse:
    def __init__(self, data: bytes) -> None:
        self._stream = io.BytesIO(data)

    def __enter__(self) -> "FakeResponse":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None

    def read(self, size: int = -1) -> bytes:
        return self._stream.read(size)


def make_collection_archive(tmp_path: Path, collection: str, skill: str, description: str = "test") -> Path:
    archive = tmp_path / f"{collection}.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr(
            f"{collection}/skills/{skill}/SKILL.md",
            f"---\nname: {skill}\ndescription: {description}\n---\n\n# {skill}\n",
        )
    return archive


def registered_state() -> RegistrationState:
    return with_install_identity(
        RegistrationState(install_id="uls_inst_test", server_url="https://updates.example.test", license_token="tok_test")
    )


class RegistrationUpdatesTest(unittest.TestCase):
    def test_registration_payload_does_not_include_local_paths_or_skill_contents(self) -> None:
        state = with_install_identity(with_install_id(RegistrationState(), server_url="https://updates.example.test"))

        payload = build_registration_payload(
            state,
            agent="codex",
            skill_count=184,
            telemetry="off",
        )

        serialized = json.dumps(payload)
        self.assertEqual(payload["skill_count_bucket"], "51-250")
        self.assertIn("public_key", payload)
        self.assertIn("key_thumbprint", payload)
        self.assertNotIn("registration_key", payload)
        self.assertNotIn("C:\\", serialized)
        self.assertNotIn("/Users/", serialized)
        self.assertNotIn("SKILL.md", serialized)
        self.assertNotIn("security-review", serialized)

    def test_hosted_updates_require_registered_installation(self) -> None:
        with self.assertRaises(RegistrationRequired):
            UpdateClient(RegistrationState())

    def test_hosted_service_rejects_non_local_plain_http(self) -> None:
        with self.assertRaises(RegistrationError):
            post_json("http://updates.example.test/v1/catalog", {}, token="tok_test", proof_state=registered_state())

    def test_registry_download_rejects_non_local_plain_http(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(UpdateError):
                download_file("http://updates.example.test/ecc.zip", Path(tmp) / "ecc.zip")

    def test_registration_and_team_state_are_private_on_posix(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / "state"
            registration_file = save_registration(registered_state(), home=home)
            team_file = save_team_state(TeamState(team_id="team_1", team_token="team_tok", status="active"), home=home)

            self.assertTrue(registration_file.is_file())
            self.assertTrue(team_file.is_file())
            if os.name != "nt":
                self.assertEqual(stat.S_IMODE(home.stat().st_mode), 0o700)
                self.assertEqual(stat.S_IMODE(registration_file.stat().st_mode), 0o600)
                self.assertEqual(stat.S_IMODE(team_file.stat().st_mode), 0o600)

    def test_current_collection_state_uses_versions_and_count_buckets(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "library"
            skill = root / "ecc" / "skills" / "security-review" / "SKILL.md"
            skill.parent.mkdir(parents=True)
            skill.write_text("---\nname: security-review\n---\n\n# security-review\n", encoding="utf-8")
            (root / ".unlimited-skills-collections.json").write_text(
                json.dumps({"schema_version": 1, "collections": {"ecc": {"version": "2026.06.01", "source": "hosted"}}}),
                encoding="utf-8",
            )

            state = current_collection_state(root)

        self.assertEqual(state, {"ecc": {"version": "2026.06.01", "source": "hosted", "skill_count_bucket": "1-10"}})

    def test_registered_update_check_and_apply_downloads_verified_collection(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            root = tmp_path / "library"
            archive = make_collection_archive(tmp_path, "ecc", "security-review", "v2")
            digest = sha256_file(archive)
            manifest = {"updates": [{"collection": "ecc", "version": "2026.06.06", "archive_url": "https://updates.example.test/ecc.zip", "sha256": digest}]}

            def fake_urlopen(request, timeout=30.0):
                url = request.full_url if hasattr(request, "full_url") else str(request)
                if url.endswith("/v1/collections/updates"):
                    return FakeResponse(json.dumps(manifest).encode("utf-8"))
                if url.endswith("/ecc.zip"):
                    return FakeResponse(archive.read_bytes())
                raise AssertionError(f"Unexpected URL: {url}")

            state = registered_state()
            client = UpdateClient(state)
            with patch("urllib.request.urlopen", fake_urlopen):
                updates = client.check(root)
                result = client.apply(root, updates[0])

            self.assertEqual(result["collection"], "ecc")
            self.assertIn("description: v2", (root / "ecc" / "skills" / "security-review" / "SKILL.md").read_text(encoding="utf-8"))
            collection_manifest = json.loads((root / ".unlimited-skills-collections.json").read_text(encoding="utf-8"))
            self.assertEqual(collection_manifest["collections"]["ecc"]["version"], "2026.06.06")
            self.assertEqual(collection_manifest["collections"]["ecc"]["source"], "hosted")

    def test_registered_catalog_uses_hosted_service_token(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "library"
            catalog = {"collections": [{"name": "ecc", "version": "2026.06.06"}]}

            def fake_urlopen(request, timeout=30.0):
                self.assertTrue(request.full_url.endswith("/v1/catalog"))
                self.assertEqual(request.headers.get("Authorization"), "Bearer tok_test")
                proof = next((value for key, value in request.headers.items() if key.lower() == "x-uls-proof"), "")
                self.assertTrue(proof)
                body = json.loads(request.data.decode("utf-8"))
                self.assertEqual(body["install_id"], "uls_inst_test")
                self.assertEqual(body["collections"], {})
                return FakeResponse(json.dumps(catalog).encode("utf-8"))

            state = registered_state()
            client = UpdateClient(state)
            with patch("urllib.request.urlopen", fake_urlopen):
                payload = client.catalog(root)

            self.assertEqual(payload, catalog)

    def test_registered_enhancement_script_download_is_verified(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            root = tmp_path / "library"
            target_dir = tmp_path / "cache"
            script_body = b"#!/usr/bin/env python3\nprint('enhance local skills')\n"
            digest = __import__("hashlib").sha256(script_body).hexdigest()
            manifest = {
                "script_id": "local-skill-enhancer",
                "version": "0.1.0",
                "download_url": "https://updates.example.test/enhancer.py",
                "sha256": digest,
                "signature": "ed25519:test",
            }

            def fake_urlopen(request, timeout=30.0):
                url = request.full_url if hasattr(request, "full_url") else str(request)
                if url.endswith("/v1/enhancement/script"):
                    body = json.loads(request.data.decode("utf-8"))
                    self.assertEqual(body["collections"], {})
                    self.assertNotIn("SKILL.md", request.data.decode("utf-8"))
                    return FakeResponse(json.dumps(manifest).encode("utf-8"))
                if url.endswith("/enhancer.py"):
                    return FakeResponse(script_body)
                raise AssertionError(f"Unexpected URL: {url}")

            state = registered_state()
            client = UpdateClient(state)
            with patch("urllib.request.urlopen", fake_urlopen):
                path = client.download_enhancement_script(root, target_dir=target_dir)

            self.assertEqual(path.read_bytes(), script_body)
            self.assertEqual(path.name, "local-skill-enhancer-0.1.0.py")

    def test_registered_team_create_manual_join_approval_and_sync_use_service_token(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "library"
            state = registered_state()
            calls: list[str] = []

            def fake_urlopen(request, timeout=30.0):
                self.assertEqual(request.headers.get("Authorization"), "Bearer tok_test")
                body = json.loads(request.data.decode("utf-8"))
                self.assertEqual(body["install_id"], "uls_inst_test")
                self.assertNotIn("SKILL.md", request.data.decode("utf-8"))
                calls.append(request.full_url)
                if request.full_url.endswith("/v1/teams"):
                    self.assertEqual(body["team_name"], "AI4SALE")
                    return FakeResponse(
                        json.dumps(
                            {
                                "team_id": "team_123",
                                "team_name": "AI4SALE",
                                "team_token": "team_tok",
                                "role": "owner",
                                "status": "active",
                                "join_code": "join_abc",
                            }
                        ).encode("utf-8")
                    )
                if request.full_url.endswith("/v1/teams/join"):
                    self.assertEqual(body["join_code"], "join_abc")
                    return FakeResponse(json.dumps({"team_id": "team_123", "team_name": "AI4SALE", "team_token": "member_tok", "role": "pending", "status": "pending"}).encode("utf-8"))
                if request.full_url.endswith("/v1/teams/team_123/members/pending"):
                    self.assertEqual(body["team_token"], "team_tok")
                    return FakeResponse(json.dumps({"items": [{"install_id": "uls_inst_member", "status": "pending"}]}).encode("utf-8"))
                if request.full_url.endswith("/v1/teams/team_123/members/uls_inst_member/approve"):
                    self.assertEqual(body["team_token"], "team_tok")
                    return FakeResponse(json.dumps({"team_id": "team_123", "install_id": "uls_inst_member", "status": "active", "role": "member"}).encode("utf-8"))
                if request.full_url.endswith("/v1/teams/team_123/approval-mode"):
                    self.assertEqual(body["team_token"], "team_tok")
                    self.assertEqual(body["mode"], "auto")
                    self.assertEqual(body["hours"], 24)
                    return FakeResponse(json.dumps({"team_id": "team_123", "approval_mode": "auto", "auto_approve_until": "2026-06-07T00:00:00Z"}).encode("utf-8"))
                if request.full_url.endswith("/v1/teams/team_123/sync"):
                    self.assertEqual(body["team_token"], "team_tok")
                    return FakeResponse(json.dumps({"updates": []}).encode("utf-8"))
                raise AssertionError(f"Unexpected URL: {request.full_url}")

            client = TeamClient(state)
            with patch("urllib.request.urlopen", fake_urlopen):
                team, create_response = client.create(root, name="AI4SALE")
                joined, _ = client.join(root, join_code="join_abc")
                pending = client.pending(team)
                approved = client.approve(team, member_install_id="uls_inst_member")
                mode = client.set_mode(team, mode="auto", hours=24)
                updates = client.sync_manifest(root, team)

            self.assertEqual(team.team_id, "team_123")
            self.assertEqual(team.role, "owner")
            self.assertEqual(create_response["join_code"], "join_abc")
            self.assertEqual(joined.role, "pending")
            self.assertEqual(joined.status, "pending")
            self.assertEqual(pending["items"][0]["install_id"], "uls_inst_member")
            self.assertEqual(approved["status"], "active")
            self.assertEqual(mode["approval_mode"], "auto")
            self.assertEqual(updates, [])
            self.assertEqual(
                calls,
                [
                    "https://updates.example.test/v1/teams",
                    "https://updates.example.test/v1/teams/join",
                    "https://updates.example.test/v1/teams/team_123/members/pending",
                    "https://updates.example.test/v1/teams/team_123/members/uls_inst_member/approve",
                    "https://updates.example.test/v1/teams/team_123/approval-mode",
                    "https://updates.example.test/v1/teams/team_123/sync",
                ],
            )

    def test_enhancement_script_checksum_mismatch_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            manifest = {
                "script_id": "local-skill-enhancer",
                "version": "0.1.0",
                "download_url": "https://updates.example.test/enhancer.py",
                "sha256": "0" * 64,
                "signature": "ed25519:test",
            }

            def fake_urlopen(request, timeout=30.0):
                url = request.full_url if hasattr(request, "full_url") else str(request)
                if url.endswith("/v1/enhancement/script"):
                    return FakeResponse(json.dumps(manifest).encode("utf-8"))
                if url.endswith("/enhancer.py"):
                    return FakeResponse(b"changed")
                raise AssertionError(f"Unexpected URL: {url}")

            state = registered_state()
            client = UpdateClient(state)
            with patch("urllib.request.urlopen", fake_urlopen):
                with self.assertRaises(UpdateError):
                    client.download_enhancement_script(tmp_path / "library", target_dir=tmp_path / "cache")

            self.assertEqual(list((tmp_path / "cache").glob("*.py")), [])

    def test_collection_archives_cannot_escape_extract_dir(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            archive = tmp_path / "bad.zip"
            with zipfile.ZipFile(archive, "w") as zf:
                zf.writestr("../escape.txt", "no")

            with self.assertRaises(UpdateError):
                safe_extract_zip(archive, tmp_path / "out")

    def test_update_manifest_rejects_unsafe_collection_names(self) -> None:
        with self.assertRaises(UpdateError):
            parse_updates({"updates": [{"collection": "../ecc", "version": "1", "archive_url": "https://example.test/ecc.zip", "sha256": "abc"}]})


if __name__ == "__main__":
    unittest.main()
