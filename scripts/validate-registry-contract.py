from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
SCHEMAS = ROOT / "schemas"
EXAMPLES = ROOT / "examples" / "registry"
COMMUNITY_EXAMPLES = ROOT / "examples" / "community"
TEAM_EXAMPLES = ROOT / "examples" / "team"
SHA256_RE = re.compile(r"^[a-f0-9]{64}$")
FORBIDDEN_KEYS = {
    "skill_body",
    "skill_content",
    "prompt",
    "source_code",
    "local_path",
    "full_path",
    "repo_path",
    "customer_name",
    "env",
    "secret",
    "private_key",
    "device_private_key",
}
TOKEN_KEYS = {"token", "license_token", "team_token", "member_token"}


class ContractError(RuntimeError):
    pass


def load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ContractError(f"Invalid JSON: {path}: {exc}") from exc


def walk(value: Any, path: str = "$"):
    if isinstance(value, dict):
        for key, item in value.items():
            yield path, key, item
            yield from walk(item, f"{path}.{key}")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            yield from walk(item, f"{path}[{index}]")


def require_fields(data: dict[str, Any], fields: list[str], path: Path) -> None:
    missing = [field for field in fields if field not in data]
    if missing:
        raise ContractError(f"{path} missing required fields: {', '.join(missing)}")


def validate_no_private_fields(path: Path, data: Any) -> None:
    serialized = json.dumps(data, ensure_ascii=False).lower()
    if "skill.md" in serialized or "```" in serialized:
        raise ContractError(f"{path} appears to include a skill body or markdown block")
    for parent_path, key, value in walk(data):
        normalized = str(key).lower()
        if normalized in FORBIDDEN_KEYS:
            raise ContractError(f"{path} contains forbidden private field {parent_path}.{key}")
        if normalized in TOKEN_KEYS:
            if not isinstance(value, str) or "redacted" not in value:
                raise ContractError(f"{path} token field {parent_path}.{key} must use a redacted placeholder")
        if normalized == "sha256":
            if not isinstance(value, str) or not SHA256_RE.match(value):
                raise ContractError(f"{path} has invalid sha256 at {parent_path}.{key}")


def validate_examples(examples: dict[str, Any]) -> None:
    require_fields(examples["registration-response.example.json"], ["license_token", "plan", "features_enabled", "proof_required"], EXAMPLES / "registration-response.example.json")
    require_fields(examples["collection-updates-response.example.json"], ["updates"], EXAMPLES / "collection-updates-response.example.json")
    for item in examples["collection-updates-response.example.json"]["updates"]:
        require_fields(item, ["collection", "version", "archive_url", "sha256"], EXAMPLES / "collection-updates-response.example.json")
        if item.get("format") != "skill-collection-zip-v1":
            raise ContractError("collection update example must use skill-collection-zip-v1")
    require_fields(examples["enhancement-script-response.example.json"], ["script_id", "version", "download_url", "sha256"], EXAMPLES / "enhancement-script-response.example.json")

    catalog_request = examples["catalog-request.example.json"]
    serialized_request = json.dumps(catalog_request, ensure_ascii=False).lower()
    for forbidden in ("skill_name", "skill_names", "local_path", "full_path", "repo_path"):
        if forbidden in serialized_request:
            raise ContractError(f"catalog request example contains forbidden field text: {forbidden}")

    catalog_response = examples["catalog-response.example.json"]
    total_skills = int(catalog_response.get("total_skills") or 0)
    snapshot_note = json.dumps(catalog_response, ensure_ascii=False).lower()
    if total_skills < 40:
        raise ContractError("catalog response example should show an early-access snapshot with at least 40 skills")
    if "snapshot" not in snapshot_note:
        raise ContractError("catalog response example must mark the count as an early-access snapshot")


def validate_community_examples(examples: dict[str, Any]) -> None:
    require_fields(examples["list-response.example.json"], ["items"], COMMUNITY_EXAMPLES / "list-response.example.json")
    require_fields(examples["search-response.example.json"], ["items"], COMMUNITY_EXAMPLES / "search-response.example.json")
    require_fields(examples["preview-response.example.json"], ["item", "included_skill_names", "install_plan", "warnings"], COMMUNITY_EXAMPLES / "preview-response.example.json")
    require_fields(examples["install-response.example.json"], ["install_plan"], COMMUNITY_EXAMPLES / "install-response.example.json")
    require_fields(examples["submission-preview.example.json"], ["metadata", "skills", "files", "warnings"], COMMUNITY_EXAMPLES / "submission-preview.example.json")
    require_fields(examples["submission-status.example.json"], ["submissions"], COMMUNITY_EXAMPLES / "submission-status.example.json")


def validate_team_examples(examples: dict[str, Any]) -> None:
    require_fields(examples["status-response.example.json"], ["team_id", "team_name", "role", "approval_mode", "limits"], TEAM_EXAMPLES / "status-response.example.json")
    require_fields(examples["members-response.example.json"], ["members"], TEAM_EXAMPLES / "members-response.example.json")
    require_fields(examples["pending-response.example.json"], ["items"], TEAM_EXAMPLES / "pending-response.example.json")
    require_fields(examples["sync-manifest.example.json"], ["team_id", "plan", "limits", "collections", "removals"], TEAM_EXAMPLES / "sync-manifest.example.json")
    require_fields(examples["sync-dry-run-output.example.json"], ["dry_run", "plan"], TEAM_EXAMPLES / "sync-dry-run-output.example.json")
    require_fields(examples["member-limit-error.example.json"], ["error"], TEAM_EXAMPLES / "member-limit-error.example.json")
    require_fields(examples["pending-approval-error.example.json"], ["error"], TEAM_EXAMPLES / "pending-approval-error.example.json")
    for item in examples["sync-manifest.example.json"]["collections"]:
        require_fields(item, ["collection", "version", "archive_url", "sha256", "format"], TEAM_EXAMPLES / "sync-manifest.example.json")


def main() -> int:
    schema_files = sorted(SCHEMAS.glob("*.json"))
    example_files = sorted(EXAMPLES.glob("*.json"))
    community_example_files = sorted(COMMUNITY_EXAMPLES.glob("*.json"))
    team_example_files = sorted(TEAM_EXAMPLES.glob("*.json"))
    if not schema_files:
        raise ContractError("No schema files found")
    if not example_files:
        raise ContractError("No registry example files found")
    if not community_example_files:
        raise ContractError("No community example files found")
    if not team_example_files:
        raise ContractError("No team example files found")

    for path in schema_files:
        load_json(path)
    examples = {path.name: load_json(path) for path in example_files}
    for name, payload in examples.items():
        validate_no_private_fields(EXAMPLES / name, payload)
    validate_examples(examples)
    community_examples = {path.name: load_json(path) for path in community_example_files}
    for name, payload in community_examples.items():
        validate_no_private_fields(COMMUNITY_EXAMPLES / name, payload)
    validate_community_examples(community_examples)
    team_examples = {path.name: load_json(path) for path in team_example_files}
    for name, payload in team_examples.items():
        validate_no_private_fields(TEAM_EXAMPLES / name, payload)
    validate_team_examples(team_examples)
    print(json.dumps({"schemas": len(schema_files), "registry_examples": len(example_files), "community_examples": len(community_example_files), "team_examples": len(team_example_files), "status": "ok"}, sort_keys=True))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except ContractError as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(2)
