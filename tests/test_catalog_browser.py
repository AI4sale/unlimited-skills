from __future__ import annotations

import io
import json
from pathlib import Path
from unittest.mock import patch

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from unlimited_skills.catalog_browser import CatalogBrowserClient, CatalogBrowserError
from unlimited_skills.cli import main
from unlimited_skills.registration import RegistrationState, base64_urlsafe_encode, save_registration, with_install_identity
from unlimited_skills.signatures import sign_manifest_for_tests


class FakeResponse:
    def __init__(self, data: bytes) -> None:
        self._stream = io.BytesIO(data)

    def __enter__(self) -> "FakeResponse":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None

    def read(self, size: int = -1) -> bytes:
        return self._stream.read(size)


def registered_state() -> RegistrationState:
    return with_install_identity(
        RegistrationState(install_id="uls_inst_catalog_test", server_url="https://catalog.example.test", license_token="tok_catalog")
    )


def write_registration(home: Path) -> None:
    save_registration(registered_state(), home=home / ".unlimited-skills")


def trust_test_key(monkeypatch) -> Ed25519PrivateKey:
    private_key = Ed25519PrivateKey.generate()
    public_key = private_key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    monkeypatch.setenv("UNLIMITED_SKILLS_MANIFEST_PUBLIC_KEYS", f"catalog-browser-test-key:{base64_urlsafe_encode(public_key)}")
    return private_key


def sign_catalog_payload(payload: dict, private_key: Ed25519PrivateKey, *, manifest_type: str = "catalog-browser-response") -> dict:
    body = {"schema_version": 1, "manifest_type": manifest_type, **payload}
    return sign_manifest_for_tests(body, private_key, key_id="catalog-browser-test-key")


def catalog_item(status: str = "published", *, item_id: str = "community:browser-qa-pack:0.1.0", installable: bool = True) -> dict:
    return {
        "schema_version": 1,
        "item_id": item_id,
        "pack_id": "browser-qa-pack",
        "collection": "community",
        "version": "0.1.0",
        "channel": "canary",
        "source": "community",
        "skill_kind": "skill-pack",
        "categories": ["qa"],
        "compatible_agents": ["codex"],
        "plan_requirement": "registered-community",
        "review_status": status,
        "deprecated": status == "deprecated",
        "retired": status == "retired",
        "installable": installable,
        "requires_registration": True,
        "description": "Browser QA pack",
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
        "quality_status": {
            "quality_grade": "a",
            "score_band": "90-100",
            "last_eval_at": "2026-06-10T08:00:00Z",
            "blockers": [],
            "warnings": [],
            "compatibility_notes": ["codex ok"],
            "deprecation_status": "active",
            "feedback_issue_categories": ["install_failure"],
            "install_risk": "low",
            "install_allowed": True,
        },
        "body_included": False,
    }


def catalog_quality_status() -> dict:
    return {
        "item_id": "community:browser-qa-pack:0.1.0",
        "quality_grade": "a",
        "score_band": "90-100",
        "last_eval_at": "2026-06-10T08:00:00Z",
        "blockers": [],
        "warnings": [],
        "compatibility_notes": ["codex ok"],
        "deprecation_status": "active",
        "retired": False,
        "feedback_issue_categories": ["install_failure"],
        "install_risk": "low",
        "install_allowed": True,
    }


def test_catalog_browser_commands_require_registration(tmp_path: Path, monkeypatch, capsys) -> None:
    root = tmp_path / "library"
    monkeypatch.setenv("UNLIMITED_SKILLS_HOME", str(tmp_path / ".unlimited-skills"))

    assert main(["--root", str(root), "catalog", "browse"]) == 2
    assert "Registration is required for hosted catalog browser operations" in capsys.readouterr().err


def test_catalog_browser_browse_search_preview_and_dry_run_install_are_signed(tmp_path: Path, monkeypatch, capsys) -> None:
    home = tmp_path / "home"
    root = tmp_path / "library"
    write_registration(home)
    monkeypatch.setenv("UNLIMITED_SKILLS_HOME", str(home / ".unlimited-skills"))
    private_key = trust_test_key(monkeypatch)
    seen_urls: list[str] = []

    def fake_urlopen(request, timeout=30.0):
        url = request.full_url if hasattr(request, "full_url") else str(request)
        seen_urls.append(url)
        if url.endswith("/v1/catalog/browser/list"):
            return FakeResponse(
                json.dumps(
                    sign_catalog_payload(
                        {"items": [catalog_item("published"), catalog_item("pending_review", item_id="community:pending:0.1.0", installable=False)]},
                        private_key,
                    )
                ).encode("utf-8")
            )
        if url.endswith("/v1/catalog/browser/search"):
            return FakeResponse(json.dumps(sign_catalog_payload({"items": [catalog_item("published")]}, private_key)).encode("utf-8"))
        if url.endswith("/v1/catalog/browser/preview"):
            item = catalog_item("published")
            item["preview"] = {"description": "Browser QA pack", "requirements": ["registered community catalog"], "body_included": False}
            return FakeResponse(json.dumps(sign_catalog_payload({"item": item}, private_key, manifest_type="catalog-browser-preview")).encode("utf-8"))
        if url.endswith("/v1/catalog/browser/item"):
            return FakeResponse(json.dumps(sign_catalog_payload({"item": catalog_item("published")}, private_key, manifest_type="catalog-browser-item")).encode("utf-8"))
        if url.endswith("/v1/catalog/quality/status"):
            return FakeResponse(json.dumps(sign_catalog_payload({"quality_status": catalog_quality_status()}, private_key, manifest_type="catalog-quality-status")).encode("utf-8"))
        raise AssertionError(f"Unexpected URL: {url}")

    with patch("urllib.request.urlopen", fake_urlopen):
        assert main(["--root", str(root), "catalog", "browse", "--source", "community", "--show-quality", "--json"]) == 0
        browse = json.loads(capsys.readouterr().out)
        assert [item["pack_id"] for item in browse["items"]] == ["browser-qa-pack"]
        assert browse["items"][0]["quality_grade"] == "a"

        assert main(["--root", str(root), "catalog", "search", "browser-qa", "--source", "community", "--json"]) == 0
        search = json.loads(capsys.readouterr().out)
        assert search["items"][0]["review_status"] == "published"

        assert main(["--root", str(root), "catalog", "preview", "community:browser-qa-pack:0.1.0", "--json"]) == 0
        preview = json.loads(capsys.readouterr().out)
        assert preview["item"]["preview"]["body_included"] is False

        assert main(["--root", str(root), "catalog", "install", "community:browser-qa-pack:0.1.0", "--dry-run", "--json"]) == 0
        install = json.loads(capsys.readouterr().out)
        assert install["dry_run"] is True
        assert install["installable"] is True

    assert any(url.endswith("/v1/catalog/browser/list") for url in seen_urls)


def test_catalog_browser_rejects_unsigned_or_unapproved_install(tmp_path: Path, monkeypatch) -> None:
    private_key = trust_test_key(monkeypatch)
    client = CatalogBrowserClient(registered_state())

    def unsigned_urlopen(request, timeout=30.0):
        return FakeResponse(json.dumps({"items": [catalog_item("published")]}).encode("utf-8"))

    with patch("urllib.request.urlopen", unsigned_urlopen):
        with pytest.raises(CatalogBrowserError):
            client.browse(tmp_path / "library")

    def pending_urlopen(request, timeout=30.0):
        return FakeResponse(
            json.dumps(
                sign_catalog_payload(
                    {"item": catalog_item("pending_review", installable=False)},
                    private_key,
                    manifest_type="catalog-browser-item",
                )
            ).encode("utf-8")
        )

    with patch("urllib.request.urlopen", pending_urlopen):
        with pytest.raises(CatalogBrowserError, match="approved or published"):
            client.install(tmp_path / "library", item_id="community:browser-qa-pack:0.1.0", dry_run=True)
