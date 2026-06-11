from __future__ import annotations

import json
from pathlib import Path

import pytest

from unlimited_skills.mcp.gateway import (
    COMMAND_NOT_ALLOWED,
    ENV_FORWARDING_DENIED,
    GatewayConfigError,
    UpstreamClient,
    UpstreamError,
    load_gateway_config,
)


def test_upstream_config_rejects_removed_env_value_map(tmp_path: Path) -> None:
    config_path = tmp_path / "gateway.json"
    config_path.write_text(
        json.dumps({"upstreams": [{"name": "bad", "command": "/x", "env": {"TOKEN": "%TOKEN%"}}]}),
        encoding="utf-8",
    )

    with pytest.raises(GatewayConfigError) as excinfo:
        load_gateway_config(config_path)

    assert "env_allowlist" in str(excinfo.value)


def test_upstream_config_rejects_env_wildcards(tmp_path: Path) -> None:
    config_path = tmp_path / "gateway.json"
    config_path.write_text(
        json.dumps({"upstreams": [{"name": "bad", "command": "/x", "env_allowlist": ["AWS_*"]}]}),
        encoding="utf-8",
    )

    with pytest.raises(GatewayConfigError):
        load_gateway_config(config_path)


def test_upstream_runtime_refuses_wildcard_env_allowlist() -> None:
    client = UpstreamClient({"name": "bad", "command": "/x", "env_allowlist": ["AWS_*"]})

    with pytest.raises(UpstreamError) as excinfo:
        client._build_env()

    assert excinfo.value.code == ENV_FORWARDING_DENIED


def test_upstream_config_rejects_shell_commands() -> None:
    client = UpstreamClient({"name": "bad", "command": "bash", "trust_level": "local-trusted"})

    with pytest.raises(UpstreamError) as excinfo:
        client._validate_command()

    assert excinfo.value.code == COMMAND_NOT_ALLOWED
