from __future__ import annotations

import json
from pathlib import Path

import pytest

pytest.importorskip("fastapi")

from unlimited_skills import __version__
from unlimited_skills.hub_server import create_app
from unlimited_skills.server import app as daemon_app


def write_allowlist(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "source_audit": {"verdict": "YES_WITH_ALLOWLIST"},
                "policy": {
                    "default_distribution_mode": "allowlist_only",
                    "full_catalog_distribution_allowed": False,
                    "requires_registration": True,
                    "free_active_client_instance_limit": 100,
                    "hub_executes_skills": False,
                    "hosted_registry_receives_search_queries_by_default": False,
                },
                "allowlist": [],
                "counts": {"allowlist_total": 0},
            }
        ),
        encoding="utf-8",
    )


def test_fastapi_apps_use_package_version(tmp_path: Path) -> None:
    allowlist = tmp_path / "hub-allowlist.v1.json"
    write_allowlist(allowlist)

    assert daemon_app.version == __version__
    assert create_app(root=tmp_path / "library", allowlist_path=allowlist).version == __version__
