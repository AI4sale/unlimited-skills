from __future__ import annotations

import json
import zipfile
from pathlib import Path
from unittest.mock import patch

from unlimited_skills.billing_status import save_billing_status
from unlimited_skills.cli import main
from unlimited_skills.private_packs import write_private_pack_metadata
from unlimited_skills.registration import RegistrationState, save_registration, with_install_identity
from unlimited_skills.support_bundle import assert_support_bundle_safe, build_bundle_report, build_support_diagnostics


def registered_state() -> RegistrationState:
    return with_install_identity(
        RegistrationState(
            install_id="uls_inst_support_test",
            server_url="https://updates.example.test",
            plan="registered-community",
            license_token="uls_secret_support_token",
            telemetry="off",
        )
    )


def block_network(*_args: object, **_kwargs: object) -> None:
    raise AssertionError("support bundle must not contact hosted services")


def write_private_skill(root: Path) -> None:
    skill = root / "local" / "skills" / "private-customer-skill" / "SKILL.md"
    skill.parent.mkdir(parents=True)
    skill.write_text(
        "---\nname: private-customer-skill\ndescription: private\n---\n\n"
        "Prompt: do not leak this. token=uls_secret_skill_body\n",
        encoding="utf-8",
    )
    (root / ".unlimited-skills-index.json").write_text(
        json.dumps(
            [
                {
                    "name": "private-customer-skill",
                    "description": "private",
                    "path": str(skill),
                    "search_text": "query and body uls_secret_index_body",
                }
            ]
        ),
        encoding="utf-8",
    )


def read_zip_text(path: Path) -> str:
    with zipfile.ZipFile(path) as archive:
        return "\n".join(archive.read(name).decode("utf-8") for name in archive.namelist())


def test_support_bundle_dry_run_writes_no_zip_and_redacts_private_data(tmp_path: Path, monkeypatch) -> None:
    home = tmp_path / "home"
    root = tmp_path / "library"
    out = tmp_path / "support-bundle.zip"
    monkeypatch.setenv("UNLIMITED_SKILLS_HOME", str(home))
    write_private_skill(root)
    state = registered_state()
    save_registration(state, home=home)

    with patch("urllib.request.urlopen", block_network):
        report = build_bundle_report(root, out=out, dry_run=True)

    serialized = json.dumps(report, ensure_ascii=False)
    assert report["manifest"]["dry_run"] is True
    assert report["manifest"]["wrote_bundle"] is False
    assert not out.exists()
    assert report["manifest"]["diagnostics_summary"]["physical_skill_files"] == 1
    assert report["diagnostics"]["service"]["snapshot_version"] == 2
    assert report["diagnostics"]["service"]["network"]["performed"] is False
    assert "private-customer-skill" not in serialized
    assert "uls_secret_support_token" not in serialized
    assert "uls_secret_skill_body" not in serialized
    assert "uls_secret_index_body" not in serialized
    assert str(root) not in serialized
    assert "SKILL.md" not in serialized


def test_support_bundle_zip_contains_only_redacted_metadata(tmp_path: Path, monkeypatch) -> None:
    home = tmp_path / "home"
    root = tmp_path / "library"
    out = tmp_path / "support-bundle.zip"
    monkeypatch.setenv("UNLIMITED_SKILLS_HOME", str(home))
    write_private_skill(root)
    save_registration(registered_state(), home=home)

    report = build_bundle_report(root, out=out, dry_run=False)

    assert report["manifest"]["wrote_bundle"] is True
    assert out.is_file()
    with zipfile.ZipFile(out) as archive:
        assert sorted(archive.namelist()) == ["README.txt", "diagnostics.json", "manifest.json"]
        diagnostics = json.loads(archive.read("diagnostics.json"))
        assert diagnostics["library"]["physical_skill_files"] == 1
        assert diagnostics["privacy"]["skill_bodies_included"] is False
        assert diagnostics["privacy"]["skill_names_included"] is False

    bundle_text = read_zip_text(out)
    assert "private-customer-skill" not in bundle_text
    assert "uls_secret_support_token" not in bundle_text
    assert "uls_secret_skill_body" not in bundle_text
    assert "uls_secret_index_body" not in bundle_text
    assert str(root) not in bundle_text
    assert "SKILL.md" not in bundle_text


def test_support_bundle_include_paths_is_explicit(tmp_path: Path, monkeypatch) -> None:
    home = tmp_path / "home"
    root = tmp_path / "library"
    monkeypatch.setenv("UNLIMITED_SKILLS_HOME", str(home))
    write_private_skill(root)

    redacted = build_support_diagnostics(root, include_paths=False)
    with_paths = build_support_diagnostics(root, include_paths=True)

    assert str(root) not in json.dumps(redacted, ensure_ascii=False)
    assert with_paths["library"]["root"] == str(root)
    assert "private-customer-skill" not in json.dumps(with_paths, ensure_ascii=False)


def test_support_bundle_private_pack_summary_is_redacted(tmp_path: Path, monkeypatch) -> None:
    home = tmp_path / "home"
    root = tmp_path / "library"
    target = root / "registry" / "private" / "team_pack_secret"
    target.mkdir(parents=True)
    monkeypatch.setenv("UNLIMITED_SKILLS_HOME", str(home))
    save_registration(registered_state(), home=home)
    save_billing_status(
        {
            "schema_version": 1,
            "source": "cached",
            "plan": "business",
            "entitlement_source": "organization",
            "subscription_status": "past_due",
            "billing_mode": "sandbox_only",
            "features_denied": [{"feature": "private_team_packs", "denial_reason": "billing_past_due"}],
            "denial_reason": "billing_past_due",
        },
        home=home,
    )
    write_private_pack_metadata(
        root,
        {
            "schema_version": 1,
            "items": {
                "team_pack_secret": {
                    "team_id": "team_secret",
                    "name": "secret private skills",
                    "version": "1.0.0",
                    "sha256": "b" * 64,
                    "target": "registry/private/team_pack_secret",
                    "source": "private-team-pack",
                    "last_error_code": "sha_mismatch",
                }
            },
        },
    )

    report = build_bundle_report(root, dry_run=True)
    serialized = json.dumps(report, ensure_ascii=False, sort_keys=True)

    assert report["diagnostics"]["private_packs"]["local"]["installed_count"] == 1
    assert report["diagnostics"]["plan"]["registered"] is True
    assert report["diagnostics"]["plan"]["privacy"]["tokens_included"] is False
    assert report["diagnostics"]["billing"]["subscription_status"] == "past_due"
    assert report["diagnostics"]["billing"]["denial_reason"] == "past_due"
    assert report["diagnostics"]["billing"]["privacy"]["checkout_urls_included"] is False
    assert report["diagnostics"]["billing"]["privacy"]["payment_card_data_included"] is False
    assert report["diagnostics"]["private_packs"]["local"]["sha_mismatch_count"] == 1
    assert report["manifest"]["diagnostics_summary"]["plan"] == "community-core"
    assert report["manifest"]["diagnostics_summary"]["subscription_status"] == "past_due"
    assert report["manifest"]["diagnostics_summary"]["private_pack_installed_count"] == 1
    assert report["diagnostics"]["privacy"]["skill_bodies_included"] is False
    assert "secret private skills" not in serialized
    assert "team_pack_secret" not in serialized
    assert "uls_secret_support_token" not in serialized
    assert "SKILL.md" not in serialized
    assert_support_bundle_safe(report)


def test_support_bundle_can_include_hashed_private_pack_refs(tmp_path: Path, monkeypatch) -> None:
    home = tmp_path / "home"
    root = tmp_path / "library"
    monkeypatch.setenv("UNLIMITED_SKILLS_HOME", str(home))
    save_registration(registered_state(), home=home)
    write_private_pack_metadata(root, {"schema_version": 1, "items": {"team_pack_secret": {"target": "", "source": "private-team-pack"}}})

    report = build_bundle_report(root, dry_run=True, include_private_pack_refs=True)

    assert report["diagnostics"]["private_packs"]["local"]["pack_refs"] == ["pack:e5376a07f257"]
    assert "team_pack_secret" not in json.dumps(report, ensure_ascii=False, sort_keys=True)
    assert_support_bundle_safe(report)


def test_support_bundle_cli_json_and_zip(tmp_path: Path, monkeypatch, capsys) -> None:
    home = tmp_path / "home"
    root = tmp_path / "library"
    out = tmp_path / "support-bundle.zip"
    monkeypatch.setenv("UNLIMITED_SKILLS_HOME", str(home))
    monkeypatch.setenv("UNLIMITED_SKILLS_DISABLE_NATIVE_SYNC", "1")
    write_private_skill(root)

    assert main(["--root", str(root), "support", "bundle", "--out", str(out), "--dry-run", "--json"]) == 0
    manifest = json.loads(capsys.readouterr().out)
    assert manifest["dry_run"] is True
    assert manifest["wrote_bundle"] is False
    assert not out.exists()

    assert main(["--root", str(root), "support", "bundle", "--out", str(out)]) == 0
    text = capsys.readouterr().out
    assert "Unlimited Skills support bundle" in text
    assert out.is_file()
