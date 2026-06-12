from __future__ import annotations

import json
from pathlib import Path

from unlimited_skills import cli


def run_cli(args: list[str], capsys) -> tuple[int, str, str]:
    code = cli.main(args)
    out = capsys.readouterr()
    return code, out.out, out.err


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_project_install_creates_mcp_config_and_gateway_config(tmp_path: Path, capsys) -> None:
    code, out, err = run_cli(
        ["mcp", "install", "--claude-code", "--project-root", str(tmp_path), "--json"],
        capsys,
    )

    assert code == 0, err
    report = json.loads(out)
    assert report["changed"] is True
    assert report["gateway_config_created"] is True
    assert report["backup_created"] is False

    mcp_config = read_json(tmp_path / ".mcp.json")
    server = mcp_config["mcpServers"]["unlimited-tools"]
    assert server == {
        "command": "unlimited-skills",
        "args": ["mcp", "gateway", "--config", ".unlimited-skills/mcp/claude-code-gateway.json"],
    }
    gateway = read_json(tmp_path / ".unlimited-skills" / "mcp" / "claude-code-gateway.json")
    assert gateway == {"schema_version": 1, "upstreams": []}


def test_project_install_preserves_existing_servers_and_is_idempotent(tmp_path: Path, capsys) -> None:
    existing = {
        "mcpServers": {
            "github": {
                "command": "npx",
                "args": ["-y", "@modelcontextprotocol/server-github"],
                "env": {"GITHUB_TOKEN": "secret-token"},
            }
        }
    }
    (tmp_path / ".mcp.json").write_text(json.dumps(existing), encoding="utf-8")

    first_code, first_out, first_err = run_cli(
        ["mcp", "install", "--claude-code", "--project-root", str(tmp_path), "--json"],
        capsys,
    )
    assert first_code == 0, first_err
    assert json.loads(first_out)["backup_created"] is True
    assert list(tmp_path.glob(".mcp.json.*.back"))

    config = read_json(tmp_path / ".mcp.json")
    assert config["mcpServers"]["github"] == existing["mcpServers"]["github"]
    assert "unlimited-tools" in config["mcpServers"]

    second_code, second_out, second_err = run_cli(
        ["mcp", "install", "--claude-code", "--project-root", str(tmp_path), "--json"],
        capsys,
    )
    assert second_code == 0, second_err
    second = json.loads(second_out)
    assert second["changed"] is False
    assert second["idempotent"] is True
    assert second["backup_created"] is False


def test_project_install_dry_run_redacts_secrets_and_paths(tmp_path: Path, capsys) -> None:
    secret_value = "ghp_super_secret_value"
    (tmp_path / ".mcp.json").write_text(
        json.dumps(
            {
                "mcpServers": {
                    "github": {
                        "command": str(tmp_path / "node.exe"),
                        "env": {"GITHUB_TOKEN": secret_value},
                    }
                }
            }
        ),
        encoding="utf-8",
    )

    code, out, err = run_cli(
        ["mcp", "install", "--claude-code", "--project-root", str(tmp_path), "--dry-run"],
        capsys,
    )

    assert code == 0, err
    assert "would change" in out
    assert "unlimited-tools" in out
    assert secret_value not in out
    assert str(tmp_path) not in out
    assert not (tmp_path / ".unlimited-skills").exists()
    assert "unlimited-tools" not in read_json(tmp_path / ".mcp.json")["mcpServers"]


def test_project_install_refuses_conflicting_server_without_force(tmp_path: Path, capsys) -> None:
    (tmp_path / ".mcp.json").write_text(
        json.dumps({"mcpServers": {"unlimited-tools": {"command": "other", "args": []}}}),
        encoding="utf-8",
    )

    code, _out, err = run_cli(
        ["mcp", "install", "--claude-code", "--project-root", str(tmp_path)],
        capsys,
    )
    assert code == 1
    assert "rerun with --force" in err

    force_code, force_out, force_err = run_cli(
        ["mcp", "install", "--claude-code", "--force", "--project-root", str(tmp_path), "--json"],
        capsys,
    )
    assert force_code == 0, force_err
    assert json.loads(force_out)["changed"] is True
    assert read_json(tmp_path / ".mcp.json")["mcpServers"]["unlimited-tools"]["command"] == "unlimited-skills"


def test_project_uninstall_removes_only_gateway_server(tmp_path: Path, capsys) -> None:
    config = {
        "mcpServers": {
            "github": {"command": "npx", "args": ["-y", "github-server"]},
            "unlimited-tools": {"command": "unlimited-skills", "args": ["mcp", "gateway", "--config", "cfg.json"]},
        }
    }
    (tmp_path / ".mcp.json").write_text(json.dumps(config), encoding="utf-8")

    code, out, err = run_cli(
        ["mcp", "uninstall", "--claude-code", "--project-root", str(tmp_path), "--json"],
        capsys,
    )
    assert code == 0, err
    assert json.loads(out)["backup_created"] is True
    updated = read_json(tmp_path / ".mcp.json")
    assert list(updated["mcpServers"]) == ["github"]
    assert list(tmp_path.glob(".mcp.json.*.back"))


def test_project_install_refuses_corrupt_json_without_backup_or_write(tmp_path: Path, capsys) -> None:
    bad = tmp_path / ".mcp.json"
    bad.write_text("{not json", encoding="utf-8")

    code, _out, err = run_cli(
        ["mcp", "install", "--claude-code", "--project-root", str(tmp_path)],
        capsys,
    )
    assert code == 1
    assert "not valid JSON" in err
    assert bad.read_text(encoding="utf-8") == "{not json"
    assert not list(tmp_path.glob(".mcp.json.*.back"))
    assert not (tmp_path / ".unlimited-skills").exists()


def test_global_install_uses_claude_json_when_requested(tmp_path: Path, capsys) -> None:
    claude_config = tmp_path / ".claude.json"
    gateway_config = tmp_path / "gateway.json"

    code, out, err = run_cli(
        [
            "mcp",
            "install",
            "--claude-code",
            "--global",
            "--claude-config",
            str(claude_config),
            "--gateway-config",
            str(gateway_config),
            "--json",
        ],
        capsys,
    )

    assert code == 0, err
    assert json.loads(out)["target"] == "global .claude.json"
    server = read_json(claude_config)["mcpServers"]["unlimited-tools"]
    assert server["command"] == "unlimited-skills"
    assert str(gateway_config) in server["args"]
    assert read_json(gateway_config) == {"schema_version": 1, "upstreams": []}


def test_install_status_reports_project_and_global(tmp_path: Path, capsys) -> None:
    claude_config = tmp_path / ".claude.json"
    run_cli(["mcp", "install", "--claude-code", "--project-root", str(tmp_path)], capsys)
    run_cli(
        [
            "mcp",
            "install",
            "--claude-code",
            "--global",
            "--claude-config",
            str(claude_config),
            "--gateway-config",
            str(tmp_path / "global-gateway.json"),
        ],
        capsys,
    )

    code, out, err = run_cli(
        ["mcp", "install", "status", "--project-root", str(tmp_path), "--claude-config", str(claude_config), "--json"],
        capsys,
    )
    assert code == 0, err
    report = json.loads(out)
    by_scope = {entry["scope"]: entry for entry in report["entries"]}
    assert by_scope["project"]["configured"] is True
    assert by_scope["global"]["configured"] is True
