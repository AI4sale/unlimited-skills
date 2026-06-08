from __future__ import annotations

import json
import re
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from . import __version__
from .registration import RegistrationError, RegistrationState, post_json, redact_sensitive_text, unlimited_skills_home, write_private_json
from .updates import CollectionUpdate, current_collection_state, parse_updates, validate_collection_name


TEAM_STATE_NAME = "team.json"
TEAM_EVENT_LOG = "team-events.jsonl"
TEAM_REQUIRED_MESSAGE = "Registration is required for Team Free sync. The MIT local core still works offline. Run: unlimited-skills register"
TEAM_FREE_AUTO_APPROVAL_MAX_HOURS = 24
TEAM_FREE_MAX_INSTANCES = 10
DURATION_RE = re.compile(r"^(\d+)(h)?$")


class TeamError(RuntimeError):
    """Raised when team registration or synchronization cannot proceed."""


@dataclass(frozen=True)
class TeamMember:
    install_id: str
    display_name: str = ""
    role: str = "member"
    status: str = "approved"
    agent_surfaces: tuple[str, ...] = ()
    client_version: str = ""
    created_at: str = ""
    approved_at: str = ""
    last_seen_at: str = ""
    collections_assigned: tuple[str, ...] = ()
    notes: str = ""


@dataclass(frozen=True)
class TeamCollection:
    collection: str
    version: str = ""
    source: str = "team"
    visibility: str = "team-free"
    assigned_to: tuple[str, ...] = ()
    update_available: bool = False
    installed_version: str = ""
    compatible_agents: tuple[str, ...] = ()
    archive_url: str = ""
    sha256: str = ""
    signature: str = ""
    format: str = "skill-collection-zip-v1"
    install_mode: str = "install_or_update"
    notes: str = ""
    archive_size: int = 0
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True)
class TeamSyncPlan:
    schema_version: int = 1
    team_id: str = ""
    plan: str = "team-free"
    server_time: str = ""
    limits: dict[str, Any] | None = None
    collections: tuple[TeamCollection, ...] = ()
    removals: tuple[dict[str, Any], ...] = ()
    request_id: str = ""

    @property
    def updates(self) -> list[CollectionUpdate]:
        updates: list[CollectionUpdate] = []
        for item in self.collections:
            if item.install_mode in {"remove", "noop"}:
                continue
            validate_collection_name(item.collection)
            updates.append(
                CollectionUpdate(
                    collection=item.collection,
                    version=item.version,
                    archive_url=item.archive_url,
                    sha256=item.sha256,
                    signature=item.signature,
                    notes=item.notes,
                    format=item.format,
                )
            )
        return updates

    def dry_run_payload(self, root: Path) -> dict[str, Any]:
        local = current_collection_state(root)
        planned = []
        for item in self.collections:
            installed = local.get(item.collection, {})
            planned.append(
                {
                    "collection": item.collection,
                    "version": item.version,
                    "installed_version": installed.get("version", item.installed_version),
                    "visibility": item.visibility,
                    "install_mode": item.install_mode,
                    "archive_size": item.archive_size,
                    "warnings": list(item.warnings),
                    "local_path": str(root / item.collection),
                    "update_available": item.update_available or installed.get("version") != item.version,
                }
            )
        return {
            "team_id": self.team_id,
            "plan": self.plan,
            "limits": self.limits or {},
            "collections": planned,
            "removals": list(self.removals),
            "reindex_needed": bool(planned or self.removals),
        }


@dataclass(frozen=True)
class TeamState:
    schema_version: int = 1
    team_id: str = ""
    team_name: str = ""
    team_token: str = ""
    install_id: str = ""
    role: str = "none"
    status: str = ""
    approval_mode: str = "manual"
    auto_approval_expires_at: str = ""
    joined_at: str = ""
    approved_at: str = ""
    last_sync_at: str = ""
    server_url: str = ""
    features_enabled: tuple[str, ...] = ()
    limits: dict[str, Any] | None = None
    redacted_auth_state: dict[str, bool] | None = None

    @property
    def joined(self) -> bool:
        return bool(self.team_id and self.status in {"active", "approved"} and self.role not in {"pending", "none"})

    @property
    def admin(self) -> bool:
        return self.role in {"master", "admin", "owner"}

    def to_json(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "team_id": self.team_id,
            "team_name": self.team_name,
            "team_token": self.team_token,
            "install_id": self.install_id,
            "role": self.role,
            "status": self.status,
            "approval_mode": self.approval_mode,
            "auto_approval_expires_at": self.auto_approval_expires_at,
            "joined_at": self.joined_at,
            "approved_at": self.approved_at,
            "last_sync_at": self.last_sync_at,
            "last_synced_at": self.last_sync_at,
            "server_url": self.server_url,
            "features_enabled": list(self.features_enabled),
            "limits": self.limits or {},
            "redacted_auth_state": self.redacted_auth_state or {"token_present": False, "proof_key_present": False},
        }


def now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def team_state_path(home: Path | None = None) -> Path:
    return (home or unlimited_skills_home()) / TEAM_STATE_NAME


def audit_log_path(home: Path | None = None) -> Path:
    return (home or unlimited_skills_home()) / ".learning" / TEAM_EVENT_LOG


def _tuple_of_strings(value: Any) -> tuple[str, ...]:
    if isinstance(value, (list, tuple)):
        return tuple(str(item) for item in value)
    if value:
        return (str(value),)
    return ()


def _limits(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    return {"max_instances": TEAM_FREE_MAX_INSTANCES, "auto_approval_max_hours": TEAM_FREE_AUTO_APPROVAL_MAX_HOURS}


def team_state_from_json(data: dict[str, Any] | None) -> TeamState:
    data = data or {}
    role = str(data.get("role") or "")
    status = str(data.get("status") or "")
    if role == "owner":
        role = "master"
    if status == "active":
        status = "approved"
    return TeamState(
        schema_version=int(data.get("schema_version") or 1),
        team_id=str(data.get("team_id") or ""),
        team_name=str(data.get("team_name") or ""),
        team_token=str(data.get("team_token") or ""),
        install_id=str(data.get("install_id") or ""),
        role=role or ("member" if data.get("team_id") else "none"),
        status=status,
        approval_mode=str(data.get("approval_mode") or "manual"),
        auto_approval_expires_at=str(data.get("auto_approval_expires_at") or ""),
        joined_at=str(data.get("joined_at") or ""),
        approved_at=str(data.get("approved_at") or ""),
        last_sync_at=str(data.get("last_sync_at") or data.get("last_synced_at") or ""),
        server_url=str(data.get("server_url") or ""),
        features_enabled=_tuple_of_strings(data.get("features_enabled")),
        limits=_limits(data.get("limits")),
        redacted_auth_state=data.get("redacted_auth_state") if isinstance(data.get("redacted_auth_state"), dict) else None,
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
    return write_private_json(path, state.to_json())


def write_team_audit(
    event_type: str,
    *,
    team: TeamState | None = None,
    registration: RegistrationState | None = None,
    target_install_id: str = "",
    result: str = "ok",
    reason: str = "",
    request_id: str = "",
    home: Path | None = None,
) -> Path:
    row = {
        "ts": time.time(),
        "event_type": event_type,
        "team_id": team.team_id if team else "",
        "actor_install_id": (registration.install_id if registration else "") or (team.install_id if team else ""),
        "target_install_id": target_install_id,
        "result": redact_sensitive_text(result),
        "reason": redact_sensitive_text(reason),
        "request_id": redact_sensitive_text(request_id),
        "redacted": True,
    }
    path = audit_log_path(home)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
    return path


def redacted_team_status(state: TeamState, registration: RegistrationState | None = None, *, member_count: int = 0, pending_count: int = 0) -> dict[str, Any]:
    registered = bool(registration.registered) if registration else False
    token_present = bool(registration.license_token) if registration else False
    proof_key_present = bool(registration.device_private_key) if registration else False
    recommendations: list[str] = []
    if not registered:
        recommendations.append("Run: unlimited-skills register")
    if state.status == "pending":
        recommendations.append(f"Ask a team admin to run: unlimited-skills team approve {state.install_id or '<install_id>'}")
    if state.approval_mode == "auto" and state.auto_approval_expires_at:
        recommendations.append("Return to manual approval mode when onboarding is complete.")
    return {
        "registered": registered,
        "joined": state.joined,
        "team_id": state.team_id,
        "team_name": state.team_name,
        "install_id": state.install_id,
        "role": state.role,
        "status": state.status,
        "approval_mode": state.approval_mode,
        "auto_approval_expires_at": state.auto_approval_expires_at,
        "joined_at": state.joined_at,
        "approved_at": state.approved_at,
        "last_sync_at": state.last_sync_at,
        "server_url": state.server_url or (registration.server_url if registration else ""),
        "features_enabled": list(state.features_enabled),
        "limits": state.limits or {},
        "member_count": member_count,
        "pending_count": pending_count,
        "redacted_auth_state": {
            "token_present": token_present,
            "proof_key_present": proof_key_present,
        },
        "recommendations": recommendations,
        "team_file": str(team_state_path()),
    }


def parse_duration_hours(value: str, *, plan: str = "team-free") -> int:
    match = DURATION_RE.match(value.strip().lower())
    if not match:
        raise TeamError("Duration must use hours, for example 1h, 6h, or 24h.")
    hours = int(match.group(1))
    if hours <= 0:
        raise TeamError("Duration must be greater than zero.")
    if plan in {"team-free", "registered-community", "community"} and hours > TEAM_FREE_AUTO_APPROVAL_MAX_HOURS:
        raise TeamError("Team Free auto-approval is capped at 24 hours. Longer windows are a paid team/business feature.")
    return hours


def _member_from_json(data: dict[str, Any]) -> TeamMember:
    return TeamMember(
        install_id=str(data.get("install_id") or ""),
        display_name=str(data.get("display_name") or data.get("name") or ""),
        role=str(data.get("role") or "member"),
        status=str(data.get("status") or "approved"),
        agent_surfaces=_tuple_of_strings(data.get("agent_surfaces") or data.get("agents")),
        client_version=str(data.get("client_version") or ""),
        created_at=str(data.get("created_at") or data.get("requested_at") or ""),
        approved_at=str(data.get("approved_at") or ""),
        last_seen_at=str(data.get("last_seen_at") or ""),
        collections_assigned=_tuple_of_strings(data.get("collections_assigned")),
        notes=str(data.get("notes") or ""),
    )


def parse_members(data: dict[str, Any]) -> list[TeamMember]:
    raw = data.get("members") or data.get("items") or []
    if not isinstance(raw, list):
        raise TeamError("Team service returned an invalid members payload.")
    return [_member_from_json(item) for item in raw if isinstance(item, dict)]


def _collection_from_json(data: dict[str, Any]) -> TeamCollection:
    collection = str(data.get("collection") or "")
    if collection:
        validate_collection_name(collection)
    return TeamCollection(
        collection=collection,
        version=str(data.get("version") or ""),
        source=str(data.get("source") or "team"),
        visibility=str(data.get("visibility") or "team-free"),
        assigned_to=_tuple_of_strings(data.get("assigned_to")),
        update_available=bool(data.get("update_available", False)),
        installed_version=str(data.get("installed_version") or ""),
        compatible_agents=_tuple_of_strings(data.get("compatible_agents")),
        archive_url=str(data.get("archive_url") or data.get("download_url") or ""),
        sha256=str(data.get("sha256") or ""),
        signature=str(data.get("signature") or ""),
        format=str(data.get("format") or "skill-collection-zip-v1"),
        install_mode=str(data.get("install_mode") or "install_or_update"),
        notes=str(data.get("notes") or ""),
        archive_size=int(data.get("archive_size") or data.get("archive_bytes") or 0),
        warnings=_tuple_of_strings(data.get("warnings")),
    )


def parse_team_sync_plan(data: dict[str, Any]) -> TeamSyncPlan:
    if "updates" in data and "collections" not in data:
        updates = parse_updates(data)
        collections = tuple(
            TeamCollection(
                collection=item.collection,
                version=item.version,
                archive_url=item.archive_url,
                sha256=item.sha256,
                signature=item.signature,
                format=item.format,
                notes=item.notes,
            )
            for item in updates
        )
    else:
        raw_collections = data.get("collections") or []
        if not isinstance(raw_collections, list):
            raise TeamError("Team sync manifest returned invalid collections.")
        collections = tuple(_collection_from_json(item) for item in raw_collections if isinstance(item, dict))
    removals = data.get("removals") or []
    if not isinstance(removals, list):
        removals = []
    return TeamSyncPlan(
        schema_version=int(data.get("schema_version") or 1),
        team_id=str(data.get("team_id") or ""),
        plan=str(data.get("plan") or "team-free"),
        server_time=str(data.get("server_time") or ""),
        limits=_limits(data.get("limits")),
        collections=collections,
        removals=tuple(item for item in removals if isinstance(item, dict)),
        request_id=str(data.get("request_id") or ""),
    )


def friendly_team_error(message: str) -> str:
    lowered = message.lower()
    if "member_limit_reached" in lowered:
        return "Team Free supports up to 10 approved instances. Upgrade is required for larger teams."
    if "pending_approval" in lowered:
        return "This instance has joined but is not approved yet. Ask a team admin to run: unlimited-skills team approve <install_id>"
    if "auto_approval_window_too_long" in lowered:
        return "Team Free auto-approval is capped at 24 hours. Longer windows are a paid team/business feature."
    if "not_team_admin" in lowered:
        return "This command requires a team master or admin."
    if "registration_required" in lowered:
        return TEAM_REQUIRED_MESSAGE
    return message


class TeamClient:
    def __init__(self, state: RegistrationState, *, timeout: float = 30.0) -> None:
        if not state.registered:
            raise TeamError(TEAM_REQUIRED_MESSAGE)
        self.state = state
        self.timeout = timeout

    def _client_payload(self) -> dict[str, str]:
        return {"name": "unlimited-skills", "version": __version__}

    def _post(self, endpoint: str, payload: dict[str, Any]) -> dict[str, Any]:
        try:
            return post_json(
                f"{self.state.server_url.rstrip('/')}{endpoint}",
                payload,
                token=self.state.license_token,
                proof_state=self.state,
                timeout=self.timeout,
            )
        except RegistrationError as exc:
            friendly = friendly_team_error(str(exc))
            write_team_audit("team_error", registration=self.state, result=friendly)
            raise TeamError(friendly) from exc

    def _team_payload(self, team: TeamState, extra: dict[str, Any] | None = None) -> dict[str, Any]:
        payload = {
            "schema_version": 1,
            "install_id": self.state.install_id,
            "client": self._client_payload(),
            "team_token": team.team_token,
        }
        if extra:
            payload.update(extra)
        return payload

    def create(self, root: Path, *, name: str) -> tuple[TeamState, dict[str, Any]]:
        response = self._post(
            "/v1/teams",
            {
                "schema_version": 1,
                "install_id": self.state.install_id,
                "client": self._client_payload(),
                "team_name": name,
                "collections": current_collection_state(root),
            },
        )
        team = self._with_registration_fields(self._team_from_response(response, fallback_name=name))
        write_team_audit("team_created", team=team, registration=self.state, request_id=str(response.get("request_id") or ""))
        return team, response

    def join(self, root: Path, *, join_code: str, display_name: str = "", agent_surfaces: tuple[str, ...] = ()) -> tuple[TeamState, dict[str, Any]]:
        response = self._post(
            "/v1/teams/join",
            {
                "schema_version": 1,
                "install_id": self.state.install_id,
                "client": self._client_payload(),
                "join_code": join_code,
                "display_name": display_name,
                "agent_surfaces": list(agent_surfaces),
                "collections": current_collection_state(root),
            },
        )
        team = self._with_registration_fields(self._team_from_response(response))
        write_team_audit("team_join_requested", team=team, registration=self.state, request_id=str(response.get("request_id") or ""))
        return team, response

    def status(self, team: TeamState) -> dict[str, Any]:
        if not team.team_id:
            return {}
        return self._post(f"/v1/teams/{team.team_id}/status", self._team_payload(team))

    def members(self, team: TeamState, *, include_all: bool = False, pending_only: bool = False) -> list[TeamMember]:
        response = self._post(
            f"/v1/teams/{team.team_id}/members",
            self._team_payload(team, {"all": include_all, "pending": pending_only}),
        )
        return parse_members(response)

    def pending(self, team: TeamState) -> dict[str, Any]:
        return self._post(f"/v1/teams/{team.team_id}/members/pending", self._team_payload(team))

    def approve(self, team: TeamState, *, member_install_id: str) -> dict[str, Any]:
        response = self._post(f"/v1/teams/{team.team_id}/members/{member_install_id}/approve", self._team_payload(team))
        write_team_audit("team_member_approved", team=team, registration=self.state, target_install_id=member_install_id, request_id=str(response.get("request_id") or ""))
        return response

    def reject(self, team: TeamState, *, member_install_id: str, reason: str = "") -> dict[str, Any]:
        response = self._post(
            f"/v1/teams/{team.team_id}/members/{member_install_id}/reject",
            self._team_payload(team, {"reason": reason}),
        )
        write_team_audit("team_member_rejected", team=team, registration=self.state, target_install_id=member_install_id, reason=reason, request_id=str(response.get("request_id") or ""))
        return response

    def revoke(self, team: TeamState, *, member_install_id: str, reason: str = "") -> dict[str, Any]:
        response = self._post(
            f"/v1/teams/{team.team_id}/members/{member_install_id}/revoke",
            self._team_payload(team, {"reason": reason}),
        )
        write_team_audit("team_member_revoked", team=team, registration=self.state, target_install_id=member_install_id, reason=reason, request_id=str(response.get("request_id") or ""))
        return response

    def set_mode(self, team: TeamState, *, mode: str, hours: int = 0) -> dict[str, Any]:
        response = self._post(
            f"/v1/teams/{team.team_id}/approval-mode",
            self._team_payload(team, {"mode": mode, "hours": hours}),
        )
        write_team_audit("team_mode_changed", team=team, registration=self.state, result=mode, request_id=str(response.get("request_id") or ""))
        return response

    def collections(self, team: TeamState) -> list[TeamCollection]:
        response = self._post(f"/v1/teams/{team.team_id}/collections", self._team_payload(team))
        raw = response.get("collections") or response.get("items") or []
        if not isinstance(raw, list):
            raise TeamError("Team service returned invalid collections payload.")
        return [_collection_from_json(item) for item in raw if isinstance(item, dict)]

    def sync_manifest(self, root: Path, team: TeamState) -> TeamSyncPlan:
        if not team.joined:
            raise TeamError("This instance has joined but is not approved yet. Ask a team admin to run: unlimited-skills team approve <install_id>")
        response = self._post(
            f"/v1/teams/{team.team_id}/sync",
            self._team_payload(team, {"collections": current_collection_state(root)}),
        )
        return parse_team_sync_plan(response)

    def mark_synced(self, team: TeamState) -> TeamState:
        return TeamState(
            schema_version=team.schema_version,
            team_id=team.team_id,
            team_name=team.team_name,
            team_token=team.team_token,
            install_id=team.install_id or self.state.install_id,
            role=team.role,
            status=team.status,
            approval_mode=team.approval_mode,
            auto_approval_expires_at=team.auto_approval_expires_at,
            joined_at=team.joined_at,
            approved_at=team.approved_at,
            last_sync_at=now_iso(),
            server_url=team.server_url or self.state.server_url,
            features_enabled=team.features_enabled,
            limits=team.limits,
            redacted_auth_state={"token_present": bool(self.state.license_token), "proof_key_present": bool(self.state.device_private_key)},
        )

    def leave(self, team: TeamState) -> dict[str, Any]:
        response = self._post(f"/v1/teams/{team.team_id}/leave", self._team_payload(team))
        write_team_audit("team_left", team=team, registration=self.state, request_id=str(response.get("request_id") or ""))
        return response

    def left_state(self, team: TeamState) -> TeamState:
        return TeamState(
            schema_version=team.schema_version,
            team_id=team.team_id,
            team_name=team.team_name,
            install_id=team.install_id or self.state.install_id,
            role=team.role,
            status="left",
            approval_mode=team.approval_mode,
            auto_approval_expires_at=team.auto_approval_expires_at,
            joined_at=team.joined_at,
            approved_at=team.approved_at,
            last_sync_at=team.last_sync_at,
            server_url=team.server_url or self.state.server_url,
            features_enabled=team.features_enabled,
            limits=team.limits,
            redacted_auth_state={"token_present": bool(self.state.license_token), "proof_key_present": bool(self.state.device_private_key)},
        )

    @staticmethod
    def _team_from_response(response: dict[str, Any], *, fallback_name: str = "") -> TeamState:
        team_id = str(response.get("team_id") or "")
        team_token = str(response.get("team_token") or response.get("member_token") or "")
        if not team_id or not team_token:
            raise TeamError("Team service did not return team_id and team_token.")
        role = str(response.get("role") or "member")
        if role == "owner":
            role = "master"
        status = str(response.get("status") or "approved")
        if status == "active":
            status = "approved"
        return TeamState(
            team_id=team_id,
            team_name=str(response.get("team_name") or fallback_name),
            team_token=team_token,
            install_id=str(response.get("install_id") or ""),
            role=role,
            status=status,
            approval_mode=str(response.get("approval_mode") or "manual"),
            auto_approval_expires_at=str(response.get("auto_approval_expires_at") or response.get("auto_approve_until") or ""),
            joined_at=str(response.get("joined_at") or now_iso()),
            approved_at=str(response.get("approved_at") or ""),
            server_url=str(response.get("server_url") or ""),
            features_enabled=_tuple_of_strings(response.get("features_enabled")),
            limits=_limits(response.get("limits")),
        )

    def _with_registration_fields(self, team: TeamState) -> TeamState:
        return TeamState(
            schema_version=team.schema_version,
            team_id=team.team_id,
            team_name=team.team_name,
            team_token=team.team_token,
            install_id=team.install_id or self.state.install_id,
            role=team.role,
            status=team.status,
            approval_mode=team.approval_mode,
            auto_approval_expires_at=team.auto_approval_expires_at,
            joined_at=team.joined_at,
            approved_at=team.approved_at,
            last_sync_at=team.last_sync_at,
            server_url=team.server_url or self.state.server_url,
            features_enabled=team.features_enabled or self.state.features_enabled,
            limits=team.limits,
            redacted_auth_state={"token_present": bool(self.state.license_token), "proof_key_present": bool(self.state.device_private_key)},
        )


def team_state_with_mode(team: TeamState, response: dict[str, Any], *, mode: str, hours: int = 0) -> TeamState:
    return TeamState(
        schema_version=team.schema_version,
        team_id=team.team_id,
        team_name=team.team_name,
        team_token=team.team_token,
        install_id=team.install_id,
        role=team.role,
        status=team.status,
        approval_mode=str(response.get("approval_mode") or mode),
        auto_approval_expires_at=str(response.get("auto_approval_expires_at") or response.get("auto_approve_until") or ""),
        joined_at=team.joined_at,
        approved_at=team.approved_at,
        last_sync_at=team.last_sync_at,
        server_url=team.server_url,
        features_enabled=team.features_enabled,
        limits=team.limits or {"auto_approval_max_hours": TEAM_FREE_AUTO_APPROVAL_MAX_HOURS, "max_instances": TEAM_FREE_MAX_INSTANCES},
        redacted_auth_state=team.redacted_auth_state,
    )


def member_to_json(member: TeamMember, *, full_id: bool = False) -> dict[str, Any]:
    install_id = member.install_id if full_id or len(member.install_id) <= 16 else f"{member.install_id[:12]}..."
    return {
        **asdict(member),
        "install_id": install_id,
        "agent_surfaces": list(member.agent_surfaces),
        "collections_assigned": list(member.collections_assigned),
    }


def collection_to_json(collection: TeamCollection) -> dict[str, Any]:
    data = asdict(collection)
    data["assigned_to"] = list(collection.assigned_to)
    data["compatible_agents"] = list(collection.compatible_agents)
    data["warnings"] = list(collection.warnings)
    return data
