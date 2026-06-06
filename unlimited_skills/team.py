from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from . import __version__
from .registration import RegistrationState, post_json, unlimited_skills_home
from .updates import CollectionUpdate, current_collection_state, parse_updates


TEAM_STATE_NAME = "team.json"


class TeamError(RuntimeError):
    """Raised when team registration or synchronization cannot proceed."""


@dataclass(frozen=True)
class TeamState:
    schema_version: int = 1
    team_id: str = ""
    team_name: str = ""
    team_token: str = ""
    role: str = ""
    status: str = ""
    joined_at: str = ""
    last_synced_at: str = ""

    @property
    def joined(self) -> bool:
        return bool(self.team_id and self.team_token and self.status == "active")

    def to_json(self) -> dict[str, str | int]:
        return {
            "schema_version": self.schema_version,
            "team_id": self.team_id,
            "team_name": self.team_name,
            "team_token": self.team_token,
            "role": self.role,
            "status": self.status,
            "joined_at": self.joined_at,
            "last_synced_at": self.last_synced_at,
        }


def now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def team_state_path(home: Path | None = None) -> Path:
    return (home or unlimited_skills_home()) / TEAM_STATE_NAME


def team_state_from_json(data: dict[str, Any] | None) -> TeamState:
    data = data or {}
    return TeamState(
        schema_version=int(data.get("schema_version") or 1),
        team_id=str(data.get("team_id") or ""),
        team_name=str(data.get("team_name") or ""),
        team_token=str(data.get("team_token") or ""),
        role=str(data.get("role") or ""),
        status=str(data.get("status") or ""),
        joined_at=str(data.get("joined_at") or ""),
        last_synced_at=str(data.get("last_synced_at") or ""),
    )


def load_team_state(home: Path | None = None) -> TeamState:
    path = team_state_path(home)
    if not path.exists():
        return TeamState()
    try:
        return team_state_from_json(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, json.JSONDecodeError) as exc:
        raise TeamError(f"Cannot read team state file: {path}") from exc


def save_team_state(state: TeamState, home: Path | None = None) -> Path:
    path = team_state_path(home)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state.to_json(), ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def redacted_team_status(state: TeamState) -> dict[str, Any]:
    return {
        "joined": state.joined,
        "team_id": state.team_id,
        "team_name": state.team_name,
        "role": state.role,
        "status": state.status,
        "joined_at": state.joined_at,
        "last_synced_at": state.last_synced_at,
        "team_token": "present" if state.team_token else "",
        "team_file": str(team_state_path()),
    }


class TeamClient:
    def __init__(self, state: RegistrationState, *, timeout: float = 30.0) -> None:
        if not state.registered:
            raise TeamError("Team sync requires a registered Unlimited Skills installation.")
        self.state = state
        self.timeout = timeout

    def _client_payload(self) -> dict[str, str]:
        return {"name": "unlimited-skills", "version": __version__}

    def create(self, root: Path, *, name: str) -> tuple[TeamState, dict[str, Any]]:
        response = post_json(
            f"{self.state.server_url.rstrip('/')}/v1/teams",
            {
                "schema_version": 1,
                "install_id": self.state.install_id,
                "client": self._client_payload(),
                "team_name": name,
                "collections": current_collection_state(root),
            },
            token=self.state.license_token,
            timeout=self.timeout,
        )
        team = self._team_from_response(response, fallback_name=name)
        return team, response

    def join(self, root: Path, *, join_code: str) -> tuple[TeamState, dict[str, Any]]:
        response = post_json(
            f"{self.state.server_url.rstrip('/')}/v1/teams/join",
            {
                "schema_version": 1,
                "install_id": self.state.install_id,
                "client": self._client_payload(),
                "join_code": join_code,
                "collections": current_collection_state(root),
            },
            token=self.state.license_token,
            timeout=self.timeout,
        )
        team = self._team_from_response(response)
        return team, response

    def sync_manifest(self, root: Path, team: TeamState) -> list[CollectionUpdate]:
        if not team.joined:
            raise TeamError("This installation is not an active team member yet. In manual mode, the master instance must approve the join request first.")
        response = post_json(
            f"{self.state.server_url.rstrip('/')}/v1/teams/{team.team_id}/sync",
            {
                "schema_version": 1,
                "install_id": self.state.install_id,
                "client": self._client_payload(),
                "team_token": team.team_token,
                "collections": current_collection_state(root),
            },
            token=self.state.license_token,
            timeout=self.timeout,
        )
        return parse_updates(response)

    def mark_synced(self, team: TeamState) -> TeamState:
        return TeamState(
            schema_version=team.schema_version,
            team_id=team.team_id,
            team_name=team.team_name,
            team_token=team.team_token,
            role=team.role,
            status=team.status,
            joined_at=team.joined_at,
            last_synced_at=now_iso(),
        )

    def pending(self, team: TeamState) -> dict[str, Any]:
        response = post_json(
            f"{self.state.server_url.rstrip('/')}/v1/teams/{team.team_id}/members/pending",
            {
                "schema_version": 1,
                "install_id": self.state.install_id,
                "client": self._client_payload(),
                "team_token": team.team_token,
            },
            token=self.state.license_token,
            timeout=self.timeout,
        )
        return response

    def approve(self, team: TeamState, *, member_install_id: str) -> dict[str, Any]:
        response = post_json(
            f"{self.state.server_url.rstrip('/')}/v1/teams/{team.team_id}/members/{member_install_id}/approve",
            {
                "schema_version": 1,
                "install_id": self.state.install_id,
                "client": self._client_payload(),
                "team_token": team.team_token,
            },
            token=self.state.license_token,
            timeout=self.timeout,
        )
        return response

    def set_mode(self, team: TeamState, *, mode: str, hours: int = 0) -> dict[str, Any]:
        response = post_json(
            f"{self.state.server_url.rstrip('/')}/v1/teams/{team.team_id}/approval-mode",
            {
                "schema_version": 1,
                "install_id": self.state.install_id,
                "client": self._client_payload(),
                "team_token": team.team_token,
                "mode": mode,
                "hours": hours,
            },
            token=self.state.license_token,
            timeout=self.timeout,
        )
        return response

    @staticmethod
    def _team_from_response(response: dict[str, Any], *, fallback_name: str = "") -> TeamState:
        team_id = str(response.get("team_id") or "")
        team_token = str(response.get("team_token") or response.get("member_token") or "")
        if not team_id or not team_token:
            raise TeamError("Team service did not return team_id and team_token.")
        return TeamState(
            team_id=team_id,
            team_name=str(response.get("team_name") or fallback_name),
            team_token=team_token,
            role=str(response.get("role") or "member"),
            status=str(response.get("status") or "active"),
            joined_at=str(response.get("joined_at") or now_iso()),
            last_synced_at="",
        )
