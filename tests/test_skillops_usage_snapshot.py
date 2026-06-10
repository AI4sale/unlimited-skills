from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from unlimited_skills.cli import main
from unlimited_skills.private_packs import write_private_pack_metadata
from unlimited_skills.registration import RegistrationState, save_registration, with_install_identity
from unlimited_skills.skillops_usage_snapshot import assert_usage_snapshot_safe, build_usage_snapshot, support_bundle_usage_summary
from unlimited_skills.updates import save_release_channel


FORBIDDEN_VALUES = (
    "acme-private-skill",
    "private-team-secret",
    "Prompt:",
    "customer task text",
    "search query",
    "uls_secret",
    "sk-secret",
    "ghp_secret",
    "C:\\Users\\tedja\\customer",
    "SKILL.md",
)


def block_network(*_args: object, **_kwargs: object) -> None:
    raise AssertionError("usage snapshot must not contact hosted services")


def registered_state() -> RegistrationState:
    return with_install_identity(
        RegistrationState(
            install_id="uls_inst_usage_snapshot_test",
            server_url="https://updates.example.test",
            plan="registered-community",
            license_token="uls_secret_usage_snapshot_token",
            telemetry="off",
        )
    )


def write_skill(path: Path, *, body: str = "safe body") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("---\nname: hidden-name\ndescription: hidden\n---\n\n" + body + "\n", encoding="utf-8")


def write_fixture_library(root: Path) -> None:
    private_skill = root / "local" / "skills" / "acme-private-skill" / "SKILL.md"
    write_skill(private_skill, body="Prompt: customer task text token=uls_secret_skill_body at C:\\Users\\tedja\\customer")
    write_skill(root / "registry" / "ecc" / "skills" / "public-helper" / "SKILL.md")
    write_skill(root / "registry" / "community" / "browser-pack" / "skills" / "community-helper" / "SKILL.md")
    write_skill(root / "registry" / "private" / "team-secret" / "skills" / "private-team-secret" / "SKILL.md")
    (root / ".unlimited-skills-index.json").write_text(
        json.dumps(
            [
                {
                    "name": "acme-private-skill",
                    "description": "search query should not leak",
                    "path": str(private_skill),
                    "search_text": "query and body sk-secret ghp_secret",
                }
            ]
        ),
        encoding="utf-8",
    )
    (root / ".unlimited-skills-collections.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "collections": {
                    "ecc": {"source": "official"},
                    "community": {"source": "community"},
                    "private": {"source": "private-team-pack"},
                    "local": {"source": "local"},
                },
            }
        ),
        encoding="utf-8",
    )
    write_private_pack_metadata(
        root,
        {
            "schema_version": 1,
            "items": {
                "private-team-secret": {
                    "name": "private-team-secret",
                    "target": "registry/private/team-secret",
                    "source": "private-team-pack",
                    "last_error_code": "sha_mismatch",
                }
            },
        },
    )


def assert_forbidden_values_absent(payload: object, root: Path) -> None:
    serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    for value in FORBIDDEN_VALUES:
        assert value not in serialized
    assert str(root) not in serialized
    assert_usage_snapshot_safe(payload)


def test_usage_snapshot_is_local_only_and_redacts_private_data(tmp_path: Path, monkeypatch) -> None:
    home = tmp_path / "home"
    root = tmp_path / "library"
    monkeypatch.setenv("UNLIMITED_SKILLS_HOME", str(home))
    save_registration(registered_state(), home=home)
    save_release_channel("beta", home=home)
    write_fixture_library(root)

    with patch("urllib.request.urlopen", block_network):
        snapshot = build_usage_snapshot(root, dry_run=True, created_at="2026-06-10T00:00:00Z")

    assert snapshot["local_only"] is True
    assert snapshot["network_calls"] is False
    assert snapshot["hosted_calls"] is False
    assert snapshot["upload_available"] is False
    assert snapshot["dry_run"] is True
    assert snapshot["release_channel"]["channel"] == "beta"
    assert snapshot["library"]["official_pack_skill_count"] == 1
    assert snapshot["library"]["community_pack_skill_count"] == 1
    assert snapshot["library"]["private_pack_skill_count"] == 1
    assert snapshot["library"]["local_skill_count"] == 1
    assert snapshot["private_packs"]["installed_count"] == 1
    assert snapshot["private_packs"]["pack_names_included"] is False
    assert snapshot["privacy"]["prompts_included"] is False
    assert snapshot["privacy"]["private_pack_names_included"] is False
    assert snapshot["privacy"]["private_skill_names_included"] is False
    assert_forbidden_values_absent(snapshot, root)


def test_usage_snapshot_cli_json_out_dry_run_and_explain(tmp_path: Path, monkeypatch, capsys) -> None:
    home = tmp_path / "home"
    root = tmp_path / "library"
    out = tmp_path / "usage-snapshot.json"
    monkeypatch.setenv("UNLIMITED_SKILLS_HOME", str(home))
    monkeypatch.setenv("UNLIMITED_SKILLS_DISABLE_NATIVE_SYNC", "1")
    write_fixture_library(root)

    assert main(["--root", str(root), "skillops", "usage-snapshot", "--json", "--out", str(out)]) == 0
    printed = json.loads(capsys.readouterr().out)
    written = json.loads(out.read_text(encoding="utf-8"))
    assert printed["snapshot_type"] == "skillops-usage-snapshot"
    assert written["snapshot_type"] == "skillops-usage-snapshot"
    assert_forbidden_values_absent(printed, root)
    assert_forbidden_values_absent(written, root)

    dry_run_out = tmp_path / "dry-run.json"
    assert main(["--root", str(root), "skillops", "usage-snapshot", "--dry-run", "--out", str(dry_run_out)]) == 0
    text = capsys.readouterr().out
    assert "Local-only: yes" in text
    assert "Hosted calls: no" in text
    assert "Output write: skipped by dry-run" in text
    assert not dry_run_out.exists()

    assert main(["skillops", "usage-snapshot", "explain"]) == 0
    explain = capsys.readouterr().out
    assert "local-only diagnostic summary" in explain
    assert "does not call hosted services" in explain


def test_usage_snapshot_support_bundle_summary_is_counts_only(tmp_path: Path, monkeypatch) -> None:
    home = tmp_path / "home"
    root = tmp_path / "library"
    monkeypatch.setenv("UNLIMITED_SKILLS_HOME", str(home))
    write_fixture_library(root)

    with patch("urllib.request.urlopen", block_network):
        summary = support_bundle_usage_summary(root)

    assert summary["available"] is True
    assert summary["counts_only"] is True
    assert summary["library"]["physical_skill_files"] == 4
    assert summary["privacy"]["skill_bodies_included"] is False
    assert summary["privacy"]["private_pack_names_included"] is False
    assert_forbidden_values_absent(summary, root)
