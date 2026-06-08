from __future__ import annotations

import io
import json
import tempfile
import unittest
import urllib.error
import zipfile
from pathlib import Path
from unittest.mock import patch

from unlimited_skills.cli import refresh_codex_router_skill
from unlimited_skills.self_update import (
    SelfUpdateError,
    SelfUpdateStatus,
    apply_public_repo_update,
    check_public_repo_update,
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


class FakeCompleted:
    def __init__(self, returncode: int = 0, stdout: str = "", stderr: str = "") -> None:
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


class SelfUpdateTest(unittest.TestCase):
    def latest_release(self, version: str = "v0.2.2") -> bytes:
        return json.dumps(
            {
                "tag_name": version,
                "name": version,
                "html_url": f"https://github.com/AI4sale/unlimited-skills/releases/tag/{version}",
                "zipball_url": f"https://api.github.com/repos/AI4sale/unlimited-skills/zipball/{version}",
                "published_at": "2026-06-06T00:00:00Z",
                "body": "Public repo update",
            }
        ).encode("utf-8")

    def test_check_public_repo_update_uses_public_release_without_registration(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)

            def fake_urlopen(request, timeout=30.0):
                self.assertTrue(request.full_url.endswith("/repos/AI4sale/unlimited-skills/releases/latest"))
                self.assertNotIn("Authorization", request.headers)
                return FakeResponse(self.latest_release())

            def fake_run(command, check=False, text=True, stdout=None, stderr=None):
                args = command[3:]
                if args == ["rev-parse", "--is-inside-work-tree"]:
                    return FakeCompleted(stdout="true\n")
                if args == ["status", "--porcelain"]:
                    return FakeCompleted(stdout="")
                if args == ["rev-parse", "--short", "HEAD"]:
                    return FakeCompleted(stdout="abc123\n")
                raise AssertionError(f"Unexpected git command: {command}")

            with patch("urllib.request.urlopen", fake_urlopen), patch("subprocess.run", fake_run):
                status = check_public_repo_update(install_root=root)

            self.assertEqual(status.latest_tag, "v0.2.2")
            self.assertEqual(status.latest_version, "0.2.2")
            self.assertTrue(status.update_available)
            self.assertTrue(status.is_git_checkout)
            self.assertFalse(status.dirty)
            self.assertEqual(status.current_ref, "abc123")

    def test_release_check_falls_back_to_tags_when_no_github_release_exists(self) -> None:
        calls: list[str] = []

        def fake_urlopen(request, timeout=30.0):
            calls.append(request.full_url)
            if request.full_url.endswith("/releases/latest"):
                raise urllib.error.HTTPError(request.full_url, 404, "Not Found", {}, None)
            if request.full_url.endswith("/tags"):
                return FakeResponse(json.dumps([{"name": "v0.2.0", "zipball_url": "https://example.test/v0.2.0.zip"}]).encode("utf-8"))
            raise AssertionError(f"Unexpected URL: {request.full_url}")

        def fake_run(command, check=False, text=True, stdout=None, stderr=None):
            return FakeCompleted(returncode=1)

        with tempfile.TemporaryDirectory() as tmp:
            with patch("urllib.request.urlopen", fake_urlopen), patch("subprocess.run", fake_run):
                status = check_public_repo_update(install_root=Path(tmp))

        self.assertEqual(status.latest_tag, "v0.2.0")
        self.assertEqual(len(calls), 2)

    def test_release_check_treats_empty_public_releases_as_no_update(self) -> None:
        def fake_urlopen(request, timeout=30.0):
            if request.full_url.endswith("/releases/latest"):
                raise urllib.error.HTTPError(request.full_url, 404, "Not Found", {}, None)
            if request.full_url.endswith("/tags"):
                return FakeResponse(b"[]")
            raise AssertionError(f"Unexpected URL: {request.full_url}")

        def fake_run(command, check=False, text=True, stdout=None, stderr=None):
            return FakeCompleted(returncode=1)

        with tempfile.TemporaryDirectory() as tmp:
            with patch("urllib.request.urlopen", fake_urlopen), patch("subprocess.run", fake_run):
                status = check_public_repo_update(install_root=Path(tmp))

        self.assertFalse(status.update_available)
        self.assertEqual(status.latest_tag, "")
        self.assertIn("no GitHub releases or tags yet", status.notes)

    def test_release_check_rejects_non_local_plain_http_api_base(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(SelfUpdateError):
                check_public_repo_update(install_root=Path(tmp), api_base="http://example.test")

    def test_apply_git_release_blocks_dirty_checkout(self) -> None:
        status = SelfUpdateStatus(
            repo="AI4sale/unlimited-skills",
            install_root=".",
            current_version="0.1.0",
            latest_version="0.2.0",
            latest_tag="v0.2.0",
            update_available=True,
            is_git_checkout=True,
            dirty=True,
            current_ref="abc123",
            release_url="",
            zipball_url="",
            published_at="",
        )

        with self.assertRaises(SelfUpdateError):
            apply_public_repo_update(status)

    def test_apply_git_release_fetches_tags_and_checks_out_release(self) -> None:
        calls: list[list[str]] = []
        status = SelfUpdateStatus(
            repo="AI4sale/unlimited-skills",
            install_root=".",
            current_version="0.1.0",
            latest_version="0.2.0",
            latest_tag="v0.2.0",
            update_available=True,
            is_git_checkout=True,
            dirty=False,
            current_ref="abc123",
            release_url="",
            zipball_url="",
            published_at="",
        )

        def fake_run_git(root: Path, args: list[str], check: bool = True):
            calls.append(args)
            return FakeCompleted(stdout="")

        with patch("unlimited_skills.self_update.run_git", fake_run_git):
            result = apply_public_repo_update(status)

        self.assertEqual(result.method, "git")
        self.assertEqual(calls, [["fetch", "--tags", "origin"], ["checkout", "v0.2.0"]])

    def test_archive_update_copies_release_tree(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            target = tmp_path / "install"
            archive = tmp_path / "release.zip"
            with zipfile.ZipFile(archive, "w") as zf:
                zf.writestr("AI4sale-unlimited-skills/pyproject.toml", "[project]\nname = \"unlimited-skills\"\n")
                zf.writestr("AI4sale-unlimited-skills/unlimited_skills/__init__.py", "__version__ = \"0.2.0\"\n")
                zf.writestr("AI4sale-unlimited-skills/skills/skill-router/SKILL.md", "---\nname: skill-router\n---\n")
                zf.writestr("AI4sale-unlimited-skills/.git/config", "ignored")
            status = SelfUpdateStatus(
                repo="AI4sale/unlimited-skills",
                install_root=str(target),
                current_version="0.1.0",
                latest_version="0.2.0",
                latest_tag="v0.2.0",
                update_available=True,
                is_git_checkout=False,
                dirty=False,
                current_ref="",
                release_url="",
                zipball_url="https://example.test/release.zip",
                published_at="",
            )

            def fake_urlopen(request, timeout=30.0):
                self.assertEqual(request.full_url, "https://example.test/release.zip")
                return FakeResponse(archive.read_bytes())

            with patch("urllib.request.urlopen", fake_urlopen):
                result = apply_public_repo_update(status, method="archive")

            self.assertEqual(result.method, "archive")
            self.assertTrue((target / "pyproject.toml").is_file())
            self.assertTrue((target / "unlimited_skills" / "__init__.py").is_file())
            self.assertFalse((target / ".git").exists())

    def test_archive_update_rejects_non_local_plain_http_release_url(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            status = SelfUpdateStatus(
                repo="AI4sale/unlimited-skills",
                install_root=str(Path(tmp) / "install"),
                current_version="0.1.0",
                latest_version="0.2.0",
                latest_tag="v0.2.0",
                update_available=True,
                is_git_checkout=False,
                dirty=False,
                current_ref="",
                release_url="",
                zipball_url="http://example.test/release.zip",
                published_at="",
            )

            with self.assertRaises(SelfUpdateError):
                apply_public_repo_update(status, method="archive")

    def test_refresh_codex_router_skill_updates_only_skill_md(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            install_root = tmp_path / "repo"
            source = install_root / "skills" / "skill-router" / "SKILL.md"
            source.parent.mkdir(parents=True)
            source.write_text("---\nname: unlimited-skills\n---\n\n# New router\n", encoding="utf-8")
            target = tmp_path / ".codex" / "skills" / "unlimited-skills"
            target.mkdir(parents=True)
            (target / "SKILL.md").write_text("old", encoding="utf-8")
            launcher = target / "scripts" / "unlimited-skills.ps1"
            launcher.parent.mkdir()
            launcher.write_text("launcher", encoding="utf-8")

            with patch("pathlib.Path.home", return_value=tmp_path):
                refreshed = refresh_codex_router_skill(install_root)

            self.assertEqual(refreshed, str(target / "SKILL.md"))
            self.assertIn("# New router", (target / "SKILL.md").read_text(encoding="utf-8"))
            self.assertEqual(launcher.read_text(encoding="utf-8"), "launcher")


if __name__ == "__main__":
    unittest.main()
