"""Tests for `unlimited-skills mcp install|uninstall|install-status --claude-code` (A3.1).

Covers the full safety contract of the one-command Claude Code gateway
installer: safe config creation, timestamped backups, idempotency, foreign
servers never touched, --force semantics, --dry-run, JSON validation before
and after, secret redaction, uninstall surgical removal, install-status,
the exact post-install next step, pip-clean written entries (no repo
paths), and both human and --json output. All file system access goes
through tmp_path homes; nothing touches the network or the real config.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pytest

from unlimited_skills import cli
from unlimited_skills.mcp.install import (
    GATEWAY_CONFIG_REFERENCE,
    SERVER_NAME,
    InstallError,
    backup_config,
    desired_server_entry,
    ensure_gateway_config,
    format_install_text,
    format_status_text,
    format_uninstall_text,
    install_claude_code,
    install_status,
    load_host_config,
    target_config_path,
    uninstall_claude_code,
)

SECRET = "hunter2-super-secret-token"

FOREIGN_SERVER = {
    "command": "npx",
    "args": ["-y", "@example/some-mcp-server"],
    "env": {"EXAMPLE_API_KEY": SECRET},
}


def make_dirs(tmp_path: Path) -> tuple[Path, Path]:
    cwd = tmp_path / "project"
    home = tmp_path / "home"
    cwd.mkdir()
    home.mkdir()
    return cwd, home


def backups_for(path: Path) -> list[Path]:
    return sorted(path.parent.glob(f"{path.name}.backup-*"))


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# Target paths: the exact places `mcp savings` reads


def test_target_paths_match_savings_read_locations(tmp_path: Path) -> None:
    cwd, home = make_dirs(tmp_path)
    assert target_config_path("project", cwd=cwd, home=home) == cwd / ".mcp.json"
    assert target_config_path("global", cwd=cwd, home=home) == home / ".claude.json"
    with pytest.raises(ValueError):
        target_config_path("system", cwd=cwd, home=home)


def test_global_install_lands_where_savings_discovers_servers(tmp_path: Path) -> None:
    from unlimited_skills.mcp.savings import discover_mcp_servers

    cwd, home = make_dirs(tmp_path)
    report = install_claude_code("global", cwd=cwd, home=home)
    assert report["status"] == "installed"
    servers = discover_mcp_servers(home / ".claude.json", home=home)
    assert [server.name for server in servers] == [SERVER_NAME]


# ---------------------------------------------------------------------------
# 1. Safe creation: new file is valid JSON


def test_install_creates_new_project_config_as_valid_json(tmp_path: Path) -> None:
    cwd, home = make_dirs(tmp_path)
    config = cwd / ".mcp.json"
    assert not config.exists()
    report = install_claude_code("project", cwd=cwd, home=home)
    assert report["status"] == "installed"
    assert report["exit_code"] == 0
    data = read_json(config)  # raises on invalid JSON
    assert data["mcpServers"][SERVER_NAME] == desired_server_entry()
    assert report["backup_path"] == ""  # nothing existed, nothing to back up


def test_install_global_creates_claude_json_with_top_level_mcp_servers(tmp_path: Path) -> None:
    cwd, home = make_dirs(tmp_path)
    report = install_claude_code("global", cwd=cwd, home=home)
    assert report["status"] == "installed"
    data = read_json(home / ".claude.json")
    assert data["mcpServers"][SERVER_NAME] == desired_server_entry()


def test_install_preserves_unrelated_top_level_keys(tmp_path: Path) -> None:
    cwd, home = make_dirs(tmp_path)
    config = home / ".claude.json"
    original = {"projects": {"C:/work/app": {"mcpServers": {}}}, "theme": "dark"}
    config.write_text(json.dumps(original), encoding="utf-8")
    report = install_claude_code("global", cwd=cwd, home=home)
    assert report["status"] == "installed"
    data = read_json(config)
    assert data["projects"] == original["projects"]
    assert data["theme"] == "dark"
    assert data["mcpServers"][SERVER_NAME] == desired_server_entry()


# ---------------------------------------------------------------------------
# 2. Backup before write, timestamped, path reported


def test_install_backs_up_existing_config_before_writing(tmp_path: Path) -> None:
    cwd, home = make_dirs(tmp_path)
    config = cwd / ".mcp.json"
    original = {"mcpServers": {"other": dict(FOREIGN_SERVER)}}
    original_text = json.dumps(original)
    config.write_text(original_text, encoding="utf-8")
    now = datetime(2026, 6, 12, 13, 14, 15)
    report = install_claude_code("project", cwd=cwd, home=home, now=now)
    assert report["status"] == "installed"
    backups = backups_for(config)
    assert len(backups) == 1
    assert backups[0].name == ".mcp.json.backup-20260612-131415"
    assert backups[0].read_text(encoding="utf-8") == original_text
    assert report["backup_path"] == str(backups[0])
    assert str(backups[0]) in format_install_text(report)


def test_backup_never_overwrites_an_existing_backup(tmp_path: Path) -> None:
    cwd, _ = make_dirs(tmp_path)
    config = cwd / ".mcp.json"
    config.write_text("{}", encoding="utf-8")
    now = datetime(2026, 6, 12, 13, 14, 15)
    first = backup_config(config, now=now)
    second = backup_config(config, now=now)
    assert first != second
    assert first.exists() and second.exists()


# ---------------------------------------------------------------------------
# 3. Idempotent rerun


def test_install_is_idempotent_no_new_backup_no_write(tmp_path: Path) -> None:
    cwd, home = make_dirs(tmp_path)
    config = cwd / ".mcp.json"
    first = install_claude_code("project", cwd=cwd, home=home)
    assert first["status"] == "installed"
    written = config.read_bytes()
    backups_before = backups_for(config)
    second = install_claude_code("project", cwd=cwd, home=home)
    assert second["status"] == "already_installed"
    assert second["exit_code"] == 0
    assert config.read_bytes() == written
    assert backups_for(config) == backups_before
    assert second["backup_path"] == ""
    assert "already installed" in format_install_text(second)


# ---------------------------------------------------------------------------
# 4. Foreign servers untouched; differing same-name entry needs --force


def test_install_never_touches_other_servers(tmp_path: Path) -> None:
    cwd, home = make_dirs(tmp_path)
    config = cwd / ".mcp.json"
    config.write_text(
        json.dumps({"mcpServers": {"other": dict(FOREIGN_SERVER)}}), encoding="utf-8"
    )
    report = install_claude_code("project", cwd=cwd, home=home)
    assert report["status"] == "installed"
    data = read_json(config)
    assert data["mcpServers"]["other"] == FOREIGN_SERVER  # byte-for-byte JSON-equal
    assert data["mcpServers"][SERVER_NAME] == desired_server_entry()
    assert report["other_servers"] == ["other"]


def test_differing_existing_entry_refused_without_force(tmp_path: Path) -> None:
    cwd, home = make_dirs(tmp_path)
    config = cwd / ".mcp.json"
    stale = {"command": "python", "args": ["-m", "old.gateway"]}
    original_text = json.dumps({"mcpServers": {SERVER_NAME: stale}})
    config.write_text(original_text, encoding="utf-8")
    report = install_claude_code("project", cwd=cwd, home=home)
    assert report["status"] == "refused"
    assert report["exit_code"] == 1
    assert "--force" in report["reason"]
    assert config.read_text(encoding="utf-8") == original_text  # untouched
    assert backups_for(config) == []


def test_force_replaces_differing_entry_with_backup(tmp_path: Path) -> None:
    cwd, home = make_dirs(tmp_path)
    config = cwd / ".mcp.json"
    stale = {"command": "python", "args": ["-m", "old.gateway"]}
    config.write_text(
        json.dumps({"mcpServers": {SERVER_NAME: stale, "other": dict(FOREIGN_SERVER)}}),
        encoding="utf-8",
    )
    report = install_claude_code("project", cwd=cwd, home=home, force=True)
    assert report["status"] == "installed"
    assert report["replaced_existing"] is True
    assert len(backups_for(config)) == 1
    data = read_json(config)
    assert data["mcpServers"][SERVER_NAME] == desired_server_entry()
    assert data["mcpServers"]["other"] == FOREIGN_SERVER


# ---------------------------------------------------------------------------
# 5. --dry-run: diff shown, nothing written


def test_dry_run_shows_diff_and_writes_nothing(tmp_path: Path) -> None:
    cwd, home = make_dirs(tmp_path)
    config = cwd / ".mcp.json"
    report = install_claude_code("project", cwd=cwd, home=home, dry_run=True)
    assert report["status"] == "would_install"
    assert report["exit_code"] == 0
    assert not config.exists()
    assert not (home / ".unlimited-skills").exists()
    added = [line for line in report["diff"] if line.startswith("+") and SERVER_NAME in line]
    assert added, "diff must show the entry that would be added"
    text = format_install_text(report)
    assert "Dry run" in text
    assert "nothing was written" in text


def test_dry_run_with_existing_config_leaves_it_untouched(tmp_path: Path) -> None:
    cwd, home = make_dirs(tmp_path)
    config = cwd / ".mcp.json"
    original_text = json.dumps({"mcpServers": {"other": dict(FOREIGN_SERVER)}})
    config.write_text(original_text, encoding="utf-8")
    report = install_claude_code("project", cwd=cwd, home=home, dry_run=True, force=True)
    assert report["status"] == "would_install"
    assert config.read_text(encoding="utf-8") == original_text
    assert backups_for(config) == []


# ---------------------------------------------------------------------------
# 6. JSON validation: invalid source refused, never silently overwritten


@pytest.mark.parametrize(
    "broken",
    ["{not json", '["top-level array"]', '{"mcpServers": "not an object"}'],
)
def test_invalid_source_config_is_refused_even_with_force(tmp_path: Path, broken: str) -> None:
    cwd, home = make_dirs(tmp_path)
    config = cwd / ".mcp.json"
    config.write_text(broken, encoding="utf-8")
    for force in (False, True):
        report = install_claude_code("project", cwd=cwd, home=home, force=force)
        assert report["status"] == "refused"
        assert report["exit_code"] == 1
        assert str(config) in report["reason"]
    assert config.read_text(encoding="utf-8") == broken  # never overwritten
    assert backups_for(config) == []


def test_invalid_json_refusal_names_the_problem(tmp_path: Path) -> None:
    cwd, _ = make_dirs(tmp_path)
    config = cwd / ".mcp.json"
    config.write_text("{broken", encoding="utf-8")
    with pytest.raises(InstallError) as excinfo:
        load_host_config(config)
    assert "not valid JSON" in str(excinfo.value)
    assert "never overwrites" in str(excinfo.value)


def test_missing_and_empty_files_load_as_empty_config(tmp_path: Path) -> None:
    cwd, _ = make_dirs(tmp_path)
    assert load_host_config(cwd / "missing.json") == {}
    empty = cwd / "empty.json"
    empty.write_text("   \n", encoding="utf-8")
    assert load_host_config(empty) == {}
    bom = cwd / "bom.json"
    bom.write_text("﻿{}", encoding="utf-8")
    assert load_host_config(bom) == {}


def test_written_config_is_validated_after_write(tmp_path: Path) -> None:
    cwd, home = make_dirs(tmp_path)
    install_claude_code("project", cwd=cwd, home=home)
    # The post-write validation already ran inside install; prove the file
    # round-trips here too.
    read_json(cwd / ".mcp.json")


# ---------------------------------------------------------------------------
# 7. No secrets in any output


def secret_free(text: str) -> bool:
    return SECRET not in text


def test_no_env_values_in_install_output_or_report(tmp_path: Path) -> None:
    cwd, home = make_dirs(tmp_path)
    config = cwd / ".mcp.json"
    stale_ours = {"command": "old", "env": {"GATEWAY_TOKEN": SECRET}}
    config.write_text(
        json.dumps({"mcpServers": {SERVER_NAME: stale_ours, "other": dict(FOREIGN_SERVER)}}),
        encoding="utf-8",
    )
    report = install_claude_code("project", cwd=cwd, home=home, force=True, dry_run=True)
    serialized = json.dumps(report)
    assert secret_free(serialized)
    assert "<redacted>" in serialized  # our differing entry's env value is masked
    assert "GATEWAY_TOKEN" in serialized  # names are fine, values are not
    assert secret_free(format_install_text(report))


def test_no_env_values_in_uninstall_output_or_report(tmp_path: Path) -> None:
    cwd, home = make_dirs(tmp_path)
    config = cwd / ".mcp.json"
    ours_with_env = dict(desired_server_entry(), env={"GATEWAY_TOKEN": SECRET})
    config.write_text(
        json.dumps({"mcpServers": {SERVER_NAME: ours_with_env, "other": dict(FOREIGN_SERVER)}}),
        encoding="utf-8",
    )
    report = uninstall_claude_code("project", cwd=cwd, home=home, dry_run=True)
    assert secret_free(json.dumps(report))
    assert secret_free(format_uninstall_text(report))


def test_no_foreign_server_content_in_status_report(tmp_path: Path) -> None:
    cwd, home = make_dirs(tmp_path)
    (cwd / ".mcp.json").write_text(
        json.dumps({"mcpServers": {"other": dict(FOREIGN_SERVER)}}), encoding="utf-8"
    )
    report = install_status(cwd=cwd, home=home)
    serialized = json.dumps(report)
    assert secret_free(serialized)
    assert "EXAMPLE_API_KEY" not in serialized  # foreign entries: not even key names
    assert secret_free(format_status_text(report))


# ---------------------------------------------------------------------------
# 8. Uninstall: surgical, backed up, idempotent


def test_uninstall_removes_only_our_entry_with_backup(tmp_path: Path) -> None:
    cwd, home = make_dirs(tmp_path)
    config = cwd / ".mcp.json"
    install_claude_code("project", cwd=cwd, home=home)
    data = read_json(config)
    data["mcpServers"]["other"] = dict(FOREIGN_SERVER)
    data["unrelated"] = {"keep": True}
    config.write_text(json.dumps(data), encoding="utf-8")
    backups_before = len(backups_for(config))
    report = uninstall_claude_code("project", cwd=cwd, home=home)
    assert report["status"] == "uninstalled"
    assert report["exit_code"] == 0
    assert len(backups_for(config)) == backups_before + 1
    assert report["backup_path"]
    after = read_json(config)
    assert SERVER_NAME not in after["mcpServers"]
    assert after["mcpServers"]["other"] == FOREIGN_SERVER
    assert after["unrelated"] == {"keep": True}


def test_uninstall_when_not_installed_is_exit_zero(tmp_path: Path) -> None:
    cwd, home = make_dirs(tmp_path)
    report = uninstall_claude_code("project", cwd=cwd, home=home)
    assert report["status"] == "not_installed"
    assert report["exit_code"] == 0
    assert not (cwd / ".mcp.json").exists()
    assert "not installed" in format_uninstall_text(report)


def test_uninstall_dry_run_writes_nothing(tmp_path: Path) -> None:
    cwd, home = make_dirs(tmp_path)
    config = cwd / ".mcp.json"
    install_claude_code("project", cwd=cwd, home=home)
    written = config.read_bytes()
    backups_before = backups_for(config)
    report = uninstall_claude_code("project", cwd=cwd, home=home, dry_run=True)
    assert report["status"] == "would_uninstall"
    assert config.read_bytes() == written
    assert backups_for(config) == backups_before
    removed = [line for line in report["diff"] if line.startswith("-") and SERVER_NAME in line]
    assert removed


def test_uninstall_refuses_invalid_config(tmp_path: Path) -> None:
    cwd, home = make_dirs(tmp_path)
    config = cwd / ".mcp.json"
    config.write_text("{broken", encoding="utf-8")
    report = uninstall_claude_code("project", cwd=cwd, home=home)
    assert report["status"] == "refused"
    assert report["exit_code"] == 1
    assert config.read_text(encoding="utf-8") == "{broken"


# ---------------------------------------------------------------------------
# 9. install-status


def test_status_not_installed(tmp_path: Path) -> None:
    cwd, home = make_dirs(tmp_path)
    report = install_status(cwd=cwd, home=home)
    assert report["installed"] is False
    assert report["exit_code"] == 1
    assert [location["scope"] for location in report["locations"]] == ["project", "global"]
    assert all(not location["installed"] for location in report["locations"])
    text = format_status_text(report)
    assert "not installed" in text
    assert "mcp install --claude-code" in text


def test_status_reports_scope_and_staleness(tmp_path: Path) -> None:
    cwd, home = make_dirs(tmp_path)
    install_claude_code("project", cwd=cwd, home=home)
    report = install_status(cwd=cwd, home=home)
    assert report["installed"] is True
    assert report["exit_code"] == 0
    by_scope = {location["scope"]: location for location in report["locations"]}
    assert by_scope["project"]["installed"] is True
    assert by_scope["project"]["matches_current"] is True
    assert by_scope["project"]["config_path"] == str(cwd / ".mcp.json")
    assert by_scope["global"]["installed"] is False
    # A stale entry is reported as installed but not matching.
    config = cwd / ".mcp.json"
    data = read_json(config)
    data["mcpServers"][SERVER_NAME] = {"command": "old"}
    config.write_text(json.dumps(data), encoding="utf-8")
    stale = install_status(cwd=cwd, home=home)
    assert stale["installed"] is True
    by_scope = {location["scope"]: location for location in stale["locations"]}
    assert by_scope["project"]["matches_current"] is False


def test_status_flags_invalid_config(tmp_path: Path) -> None:
    cwd, home = make_dirs(tmp_path)
    (home / ".claude.json").write_text("{broken", encoding="utf-8")
    report = install_status(cwd=cwd, home=home)
    by_scope = {location["scope"]: location for location in report["locations"]}
    assert by_scope["global"]["config_valid"] is False
    assert "not valid JSON" in format_status_text(report)


# ---------------------------------------------------------------------------
# 10. Exact next step after install


def test_install_prints_restart_next_step(tmp_path: Path) -> None:
    cwd, home = make_dirs(tmp_path)
    report = install_claude_code("project", cwd=cwd, home=home)
    assert "Restart your Claude Code session" in report["next_step"]
    assert "Restart your Claude Code session" in format_install_text(report)


# ---------------------------------------------------------------------------
# 11. pip-clean entry: works without a repo checkout


def test_written_entry_carries_no_machine_or_repo_paths(tmp_path: Path) -> None:
    cwd, home = make_dirs(tmp_path)
    install_claude_code("project", cwd=cwd, home=home)
    entry = read_json(cwd / ".mcp.json")["mcpServers"][SERVER_NAME]
    assert entry["command"] == "unlimited-skills"  # console script from PATH
    serialized = json.dumps(entry)
    assert str(tmp_path) not in serialized
    assert "\\" not in serialized  # no Windows absolute paths
    assert ":/" not in serialized and ":\\" not in serialized  # no drive letters
    assert GATEWAY_CONFIG_REFERENCE in entry["args"]  # portable ~/... reference


def test_gateway_config_is_created_minimal_and_never_clobbered(tmp_path: Path) -> None:
    cwd, home = make_dirs(tmp_path)
    report = install_claude_code("project", cwd=cwd, home=home)
    gateway_config = home / ".unlimited-skills" / "gateway-config.json"
    assert report["gateway_config_created"] is True
    data = read_json(gateway_config)
    assert data["upstreams"] == []
    # An existing gateway config is never modified.
    gateway_config.write_text(json.dumps({"upstreams": [{"name": "mine"}]}), encoding="utf-8")
    path, created = ensure_gateway_config(home)
    assert created is False
    assert read_json(gateway_config)["upstreams"] == [{"name": "mine"}]
    assert path == gateway_config


# ---------------------------------------------------------------------------
# 12. CLI: human and --json output, flags, exit codes


@pytest.fixture()
def cli_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path, Path]:
    cwd, home = make_dirs(tmp_path)
    root = tmp_path / "library"
    monkeypatch.chdir(cwd)
    monkeypatch.setattr(Path, "home", staticmethod(lambda: home))
    return cwd, home, root


def run_cli(root: Path, *argv: str) -> int:
    return cli.main(["--root", str(root), *argv])


def test_cli_install_json_contract(cli_env, capsys: pytest.CaptureFixture) -> None:
    cwd, home, root = cli_env
    code = run_cli(root, "mcp", "install", "--claude-code", "--json")
    assert code == 0
    report = json.loads(capsys.readouterr().out)
    assert report["action"] == "install"
    assert report["status"] == "installed"
    assert report["scope"] == "project"
    assert report["server_name"] == SERVER_NAME
    assert report["config_path"] == str(cwd / ".mcp.json")
    assert "Restart your Claude Code session" in report["next_step"]
    assert report["exit_code"] == 0
    assert read_json(cwd / ".mcp.json")["mcpServers"][SERVER_NAME] == desired_server_entry()


def test_cli_install_human_output_and_idempotent_rerun(
    cli_env, capsys: pytest.CaptureFixture
) -> None:
    cwd, home, root = cli_env
    assert run_cli(root, "mcp", "install", "--claude-code") == 0
    out = capsys.readouterr().out
    assert f"Installed '{SERVER_NAME}'" in out
    assert "Restart your Claude Code session" in out
    assert run_cli(root, "mcp", "install", "--claude-code") == 0
    assert "already installed" in capsys.readouterr().out
    assert backups_for(cwd / ".mcp.json") == []


def test_cli_global_scope_targets_home_claude_json(cli_env, capsys: pytest.CaptureFixture) -> None:
    cwd, home, root = cli_env
    assert run_cli(root, "mcp", "install", "--claude-code", "--global", "--json") == 0
    report = json.loads(capsys.readouterr().out)
    assert report["scope"] == "global"
    assert report["config_path"] == str(home / ".claude.json")
    assert read_json(home / ".claude.json")["mcpServers"][SERVER_NAME] == desired_server_entry()
    assert not (cwd / ".mcp.json").exists()


def test_cli_refusal_exits_one_and_prints_reason_to_stderr(
    cli_env, capsys: pytest.CaptureFixture
) -> None:
    cwd, home, root = cli_env
    (cwd / ".mcp.json").write_text(
        json.dumps({"mcpServers": {SERVER_NAME: {"command": "old"}}}), encoding="utf-8"
    )
    assert run_cli(root, "mcp", "install", "--claude-code") == 1
    captured = capsys.readouterr()
    assert "refused" in captured.err
    assert "--force" in captured.err


def test_cli_requires_claude_code_flag(cli_env, capsys: pytest.CaptureFixture) -> None:
    cwd, home, root = cli_env
    for argv in (
        ("mcp", "install"),
        ("mcp", "uninstall"),
        ("mcp", "install-status"),
    ):
        assert run_cli(root, *argv) == 2
        assert "--claude-code" in capsys.readouterr().err
    assert not (cwd / ".mcp.json").exists()


def test_cli_dry_run_writes_nothing(cli_env, capsys: pytest.CaptureFixture) -> None:
    cwd, home, root = cli_env
    assert run_cli(root, "mcp", "install", "--claude-code", "--dry-run") == 0
    assert "Dry run" in capsys.readouterr().out
    assert not (cwd / ".mcp.json").exists()


def test_cli_uninstall_json_contract(cli_env, capsys: pytest.CaptureFixture) -> None:
    cwd, home, root = cli_env
    assert run_cli(root, "mcp", "install", "--claude-code") == 0
    capsys.readouterr()
    assert run_cli(root, "mcp", "uninstall", "--claude-code", "--json") == 0
    report = json.loads(capsys.readouterr().out)
    assert report["action"] == "uninstall"
    assert report["status"] == "uninstalled"
    assert report["backup_path"]
    assert SERVER_NAME not in read_json(cwd / ".mcp.json")["mcpServers"]
    # Idempotent rerun: not installed, exit 0.
    assert run_cli(root, "mcp", "uninstall", "--claude-code", "--json") == 0
    rerun = json.loads(capsys.readouterr().out)
    assert rerun["status"] == "not_installed"


def test_cli_install_status_json_contract(cli_env, capsys: pytest.CaptureFixture) -> None:
    cwd, home, root = cli_env
    assert run_cli(root, "mcp", "install-status", "--claude-code", "--json") == 1
    report = json.loads(capsys.readouterr().out)
    assert report["action"] == "install-status"
    assert report["installed"] is False
    assert {location["scope"] for location in report["locations"]} == {"project", "global"}
    for location in report["locations"]:
        assert set(location) == {
            "scope",
            "config_path",
            "config_exists",
            "config_valid",
            "installed",
            "matches_current",
        }
    assert run_cli(root, "mcp", "install", "--claude-code") == 0
    capsys.readouterr()
    assert run_cli(root, "mcp", "install-status", "--claude-code", "--json") == 0
    after = json.loads(capsys.readouterr().out)
    assert after["installed"] is True


def test_cli_output_never_contains_env_values(cli_env, capsys: pytest.CaptureFixture) -> None:
    cwd, home, root = cli_env
    (cwd / ".mcp.json").write_text(
        json.dumps({"mcpServers": {"other": dict(FOREIGN_SERVER)}}), encoding="utf-8"
    )
    for argv in (
        ("mcp", "install", "--claude-code", "--dry-run", "--json"),
        ("mcp", "install", "--claude-code", "--json"),
        ("mcp", "install-status", "--claude-code", "--json"),
        ("mcp", "uninstall", "--claude-code", "--json"),
    ):
        run_cli(root, *argv)
        captured = capsys.readouterr()
        assert secret_free(captured.out + captured.err), argv


def test_cli_logs_event_without_paths(cli_env, capsys: pytest.CaptureFixture) -> None:
    cwd, home, root = cli_env
    assert run_cli(root, "mcp", "install", "--claude-code") == 0
    events_file = root / ".learning" / "events.jsonl"
    assert events_file.is_file()
    events = [json.loads(line) for line in events_file.read_text(encoding="utf-8").splitlines()]
    install_events = [event for event in events if event.get("type") == "mcp_install"]
    assert install_events
    serialized = json.dumps(install_events)
    assert str(cwd) not in serialized
    assert str(home) not in serialized
