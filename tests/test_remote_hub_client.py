from __future__ import annotations

import io
import json
import urllib.error
from pathlib import Path
from typing import Any

from unlimited_skills.cli import main


class FakeHTTPResponse:
    def __init__(self, payload: dict[str, Any]) -> None:
        self.payload = payload

    def __enter__(self) -> "FakeHTTPResponse":
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def read(self) -> bytes:
        return json.dumps(self.payload).encode("utf-8")


def write_local_skill(root: Path, name: str = "local-debug") -> Path:
    path = root / "local" / "skills" / name / "SKILL.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"""---
name: {name}
description: Local fallback debug skill
---

## When to Use

Use this local fallback skill for hub outage tests.
""",
        encoding="utf-8",
    )
    return path


def configure_remote(tmp_path: Path, monkeypatch, *, fallback: str = "local_allowed", token: str = "uls_hub_remote_secret") -> Path:
    uls_home = tmp_path / ".unlimited-skills"
    monkeypatch.setenv("UNLIMITED_SKILLS_HOME", str(uls_home))
    assert main(["remote", "configure", "--url", "http://127.0.0.1:8766", "--token", token, "--fallback", fallback]) == 0
    return uls_home


def fake_hub_urlopen(request, timeout=10):
    assert timeout == 10
    assert request.get_header("Authorization") == "Bearer uls_hub_remote_secret"
    assert request.get_header("X-uls-hub-token") == "uls_hub_remote_secret"
    url = request.full_url
    method = request.get_method()
    body = json.loads(request.data.decode("utf-8")) if request.data else {}
    if method == "GET" and url.endswith("/v1/hub/status"):
        return FakeHTTPResponse({"schema_version": 1, "hub_id": "uls_hub_test", "distribution_mode": "allowlist_only", "skills_total": 2})
    if method == "POST" and url.endswith("/v1/skills/search"):
        assert body["query"] == "debug skill"
        return FakeHTTPResponse(
            {
                "schema_version": 1,
                "query": body["query"],
                "results": [
                    {
                        "name": "remote-debug",
                        "collection": "registry",
                        "confidence": 0.91,
                        "skill_kind": "pure_text",
                        "hub_behavior": "distribute_body",
                        "requires_local_install": False,
                    }
                ],
            }
        )
    if method == "POST" and url.endswith("/v1/skills/resolve"):
        assert body["client_capabilities"]["agent"] == "codex"
        return FakeHTTPResponse(
            {
                "schema_version": 1,
                "query": body["query"],
                "selected": [
                    {
                        "name": "remote-debug",
                        "collection": "registry",
                        "confidence": 0.95,
                        "skill_kind": "pure_text",
                        "hub_behavior": "distribute_body",
                        "requires_local_install": False,
                        "missing_capabilities": [],
                        "warnings": [],
                        "body": "REMOTE_SKILL_BODY_PUBLIC_TEST",
                    },
                    {
                        "name": "remote-tool-plan",
                        "collection": "registry",
                        "confidence": 0.72,
                        "skill_kind": "tool",
                        "hub_behavior": "distribute_body_with_local_install_plan",
                        "requires_local_install": True,
                        "missing_capabilities": ["client_capability_checks"],
                        "warnings": ["metadata-only until client capability checks are implemented"],
                        "body": "",
                    },
                ],
                "context_budget": {"max_skills": 2, "max_chars": 12000, "used_chars": 29},
            }
        )
    if method == "GET" and url.endswith("/v1/skills/remote-debug"):
        return FakeHTTPResponse(
            {
                "schema_version": 1,
                "skill": {
                    "name": "remote-debug",
                    "collection": "registry",
                    "skill_kind": "pure_text",
                    "hub_behavior": "distribute_body",
                    "requires_local_install": False,
                    "body": "REMOTE_VIEW_BODY_PUBLIC_TEST",
                    "warnings": [],
                },
            }
        )
    raise AssertionError(f"unexpected request {method} {url}")


def test_remote_configure_supports_token_env_and_redacts_output(tmp_path: Path, monkeypatch, capsys) -> None:
    uls_home = tmp_path / ".unlimited-skills"
    monkeypatch.setenv("UNLIMITED_SKILLS_HOME", str(uls_home))

    assert main(["remote", "configure", "--url", "http://127.0.0.1:8766?token=query_secret", "--token-env", "ULS_HUB_TOKEN", "--fallback", "hub_required"]) == 0

    output = capsys.readouterr().out
    payload = json.loads(output)
    config = json.loads((uls_home / "remote.json").read_text(encoding="utf-8"))
    assert payload["token_present"] is True
    assert payload["token_storage"] == "env"
    assert payload["fallback_mode"] == "hub_required"
    assert config["token_env"] == "ULS_HUB_TOKEN"
    assert "query_secret" not in output
    assert "query_secret" not in config["url"]


def test_remote_status_search_resolve_and_view_use_hub_token(tmp_path: Path, monkeypatch, capsys) -> None:
    configure_remote(tmp_path, monkeypatch)
    capsys.readouterr()
    monkeypatch.setattr("urllib.request.urlopen", fake_hub_urlopen)

    assert main(["remote", "status", "--json"]) == 0
    status = json.loads(capsys.readouterr().out)
    assert status["reachable"] is True
    assert status["hub_status"]["hub_id"] == "uls_hub_test"

    assert main(["remote", "search", "debug skill"]) == 0
    search_output = capsys.readouterr().out
    assert "remote-debug [registry]" in search_output
    assert "uls_hub_remote_secret" not in search_output

    assert main(["remote", "resolve", "debug skill", "--agent", "codex"]) == 0
    resolve_output = capsys.readouterr().out
    assert "REMOTE_SKILL_BODY_PUBLIC_TEST" in resolve_output
    assert "remote-tool-plan [registry]" in resolve_output
    assert "client_capability_checks" in resolve_output

    assert main(["remote", "view", "remote-debug"]) == 0
    view_output = capsys.readouterr().out
    assert "REMOTE_VIEW_BODY_PUBLIC_TEST" in view_output


def test_remote_auth_failure_is_friendly_and_redacted(tmp_path: Path, monkeypatch, capsys) -> None:
    configure_remote(tmp_path, monkeypatch, token="uls_hub_bad_secret")
    capsys.readouterr()

    def fail_auth(request, timeout=10):
        body = json.dumps({"schema_version": 1, "error": {"code": "invalid_hub_token", "message": "token=uls_hub_bad_secret rejected"}}).encode("utf-8")
        raise urllib.error.HTTPError(request.full_url, 401, "Unauthorized", {}, io.BytesIO(body))

    monkeypatch.setattr("urllib.request.urlopen", fail_auth)

    assert main(["remote", "search", "debug skill"]) == 2

    error = capsys.readouterr().err
    assert "invalid_hub_token" in error
    assert "uls_hub_bad_secret" not in error
    assert "[redacted]" in error


def test_remote_unavailable_local_allowed_falls_back_to_local_search(tmp_path: Path, monkeypatch, capsys) -> None:
    root = tmp_path / "library"
    write_local_skill(root)
    configure_remote(tmp_path, monkeypatch, fallback="local_allowed")
    capsys.readouterr()

    def fail_network(_request, timeout=10):
        raise urllib.error.URLError("hub down token=uls_hub_remote_secret")

    monkeypatch.setattr("urllib.request.urlopen", fail_network)

    assert main(["--root", str(root), "remote", "search", "fallback debug"]) == 0

    output = capsys.readouterr().out
    assert "Remote hub unavailable; using local fallback." in output
    assert "local-debug [local]" in output
    assert "uls_hub_remote_secret" not in output


def test_remote_unavailable_hub_required_fails_without_fallback(tmp_path: Path, monkeypatch, capsys) -> None:
    root = tmp_path / "library"
    write_local_skill(root)
    configure_remote(tmp_path, monkeypatch, fallback="hub_required")
    capsys.readouterr()

    def fail_network(_request, timeout=10):
        raise urllib.error.URLError("hub down")

    monkeypatch.setattr("urllib.request.urlopen", fail_network)

    assert main(["--root", str(root), "remote", "view", "local-debug"]) == 2

    captured = capsys.readouterr()
    assert "Remote hub is required by policy but unavailable." in captured.err
    assert "local-debug [local]" not in captured.out
