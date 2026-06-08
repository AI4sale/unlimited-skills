from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from unlimited_skills.registration import RegistrationState, register_installation
from unlimited_skills.updates import UpdateError, parse_enhancement_script, parse_updates


ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = ROOT / "examples" / "registry"
COMMUNITY_EXAMPLES = ROOT / "examples" / "community"
TEAM_EXAMPLES = ROOT / "examples" / "team"
SCHEMAS = ROOT / "schemas"


def load_example(name: str) -> dict:
    return json.loads((EXAMPLES / name).read_text(encoding="utf-8"))


def test_all_registry_schemas_and_examples_are_valid_json() -> None:
    for path in [*SCHEMAS.glob("*.json"), *EXAMPLES.glob("*.json"), *COMMUNITY_EXAMPLES.glob("*.json"), *TEAM_EXAMPLES.glob("*.json")]:
        json.loads(path.read_text(encoding="utf-8"))


def test_parse_updates_accepts_registry_update_example() -> None:
    updates = parse_updates(load_example("collection-updates-response.example.json"))

    by_collection = {item.collection: item for item in updates}
    assert {"ecc", "superpowers"}.issubset(by_collection)
    assert by_collection["ecc"].format == "skill-collection-zip-v1"
    assert by_collection["superpowers"].format == "skill-collection-zip-v1"
    assert len(by_collection["ecc"].sha256) == 64
    assert len(by_collection["superpowers"].sha256) == 64


def test_parse_updates_rejects_update_missing_sha256() -> None:
    payload = load_example("collection-updates-response.example.json")
    del payload["updates"][0]["sha256"]

    with pytest.raises(UpdateError):
        parse_updates(payload)


def test_parse_enhancement_script_accepts_registry_example() -> None:
    script = parse_enhancement_script(load_example("enhancement-script-response.example.json"))

    assert script.script_id == "local-skill-enhancer"
    assert script.version == "0.1.0"
    assert len(script.sha256) == 64


def test_registration_response_example_maps_to_registration_state(monkeypatch) -> None:
    response = load_example("registration-response.example.json")

    def fake_post_json(url, payload, **kwargs):
        return response

    monkeypatch.setattr("unlimited_skills.registration.post_json", fake_post_json)
    state = register_installation(
        RegistrationState(
            install_id="uls_inst_example_01",
            device_private_key="private",
            device_public_key="public",
            key_thumbprint=response["key_thumbprint"],
        ),
        server_url="https://unlimited.ai4.sale",
        agent="codex",
        skill_count=5,
    )

    assert state.license_token == "uls_token_example_redacted"
    assert state.plan == "registered-community"
    assert state.proof_required is True
    assert "hosted_catalog" in state.features_enabled


def test_catalog_request_example_contains_no_forbidden_private_fields() -> None:
    serialized = json.dumps(load_example("catalog-request.example.json")).lower()

    for forbidden in ["skill_body", "skill_content", "prompt", "source_code", "skill_name", "local_path", "full_path", "repo_path", "customer_name", "device_private_key"]:
        assert forbidden not in serialized


def test_catalog_response_example_uses_snapshot_count_without_skill_bodies() -> None:
    payload = load_example("catalog-response.example.json")
    serialized = json.dumps(payload).lower()

    assert payload["total_skills"] >= 267
    assert {"ecc", "superpowers"}.issubset({item["collection"] for item in payload["catalog"]["collections"]})
    assert "snapshot" in serialized
    assert "skill.md" not in serialized
    assert "```" not in serialized


def test_registry_examples_use_only_redacted_placeholders_for_tokens() -> None:
    for path in [*EXAMPLES.glob("*.json"), *COMMUNITY_EXAMPLES.glob("*.json"), *TEAM_EXAMPLES.glob("*.json")]:
        payload = json.loads(path.read_text(encoding="utf-8"))
        serialized = json.dumps(payload).lower()
        assert "private_key" not in serialized
        assert "secret" not in serialized
        if "token" in serialized:
            assert "redacted" in serialized


def test_community_examples_are_sanitized_metadata_only() -> None:
    for path in COMMUNITY_EXAMPLES.glob("*.json"):
        serialized = path.read_text(encoding="utf-8").lower()
        assert "skill.md" not in serialized
        assert "```" not in serialized
        assert "content_base64" not in serialized
        assert "c:\\" not in serialized
        assert "/users/" not in serialized


def test_team_examples_are_sanitized_metadata_only() -> None:
    for path in TEAM_EXAMPLES.glob("*.json"):
        serialized = path.read_text(encoding="utf-8").lower()
        assert "skill.md" not in serialized
        assert "```" not in serialized
        assert "team_token" not in serialized
        assert "license_token" not in serialized
        assert "device_private_key" not in serialized
        assert "c:\\" not in serialized
        assert "/users/" not in serialized


def test_registry_contract_validation_script_passes() -> None:
    completed = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "validate-registry-contract.py")],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr
    assert '"status": "ok"' in completed.stdout


def test_registry_docs_keep_signature_boundary_precise() -> None:
    docs = "\n".join(path.read_text(encoding="utf-8", errors="replace") for path in [ROOT / "docs" / "hosted-registry-api.md", ROOT / "docs" / "hosted-catalog-model.md", ROOT / "docs" / "registry-contract-tests.md", ROOT / "docs" / "team-skill-sync.md"])
    lowered = docs.lower()

    assert "registered hosted catalog" in lowered
    assert "community submissions require explicit upload confirmation" in lowered
    assert "hosted catalog/update checks do not upload local skill bodies" in lowered
    assert "no registration, no official hosted skill updates" in lowered
    assert "signed manifest envelope" in lowered
    assert "currently enforced" not in lowered.replace("not currently enforced", "")
    assert "private encrypted packs are implemented" not in lowered
    assert "enterprise skill lock is implemented" not in lowered
