"""E26: MCP registered/team distribution fixture E2E harness.

Proves the contract of docs/mcp-distribution-e2e-harness.md against
``scripts/run-mcp-profile-distribution-fixture-e2e.py`` and the thin
verifier ``scripts/verify-mcp-profile-distribution-e2e.py``:

- the fixture-mode runner executes the 23-step workflow (fixture registry
  -> signed channel/assignment -> entitlement gate -> client fetch ->
  verify -> library -> rollout/replay -> activate -> gateway -> abuse
  battery -> incident rollback -> audit/report) as ONE flow and exits 0
  with every step ok;
- the JSON report validates against
  ``schemas/mcp-distribution-e2e-report.schema.json`` and the shipped
  generated example validates and stays in sync;
- ``--step NAME`` runs and reports the workflow prefix ending at NAME;
- failure injection fails exactly the right step (a tampered fetched
  bundle fails ``library_add``; a tampered stored channel fails
  ``client_fetch``) and the failed report still validates;
- ABT-coverage consistency: every claimed ``ABT-*`` id exists in the E25
  plan (docs/mcp-distribution-abuse-test-plan.md) and the top-level
  coverage equals the union of per-step claims;
- leak-grep: no key material, full hashes, local paths, or E24
  decision-20 forbidden field names anywhere in the report, the shipped
  example, or the CLI outputs (the audit writer's own heuristics);
- containment: with an explicit ``base_dir`` the runner creates no temp
  directory of its own and never touches the repo's managed trust store,
  bundle library, or default audit log;
- the verifier passes the good report and fails prefix runs, failed
  steps, forbidden fields, and secret-shaped strings.
"""

from __future__ import annotations

import importlib.util
import json
import re
from pathlib import Path

import pytest

pytest.importorskip("cryptography")

from unlimited_skills.mcp.audit import _PATH_PATTERN as PATH_PATTERN
from unlimited_skills.mcp.audit import looks_secret

ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = ROOT / "scripts" / "run-mcp-profile-distribution-fixture-e2e.py"
VERIFIER_PATH = ROOT / "scripts" / "verify-mcp-profile-distribution-e2e.py"
SCHEMA_PATH = ROOT / "schemas" / "mcp-distribution-e2e-report.schema.json"
EXAMPLE_PATH = ROOT / "examples" / "mcp" / "distribution-e2e-report.example.json"
DOC_PATH = ROOT / "docs" / "mcp-distribution-e2e-harness.md"
PLAN_PATH = ROOT / "docs" / "mcp-distribution-abuse-test-plan.md"

STEP_NAMES = (
    "keygen",
    "trust_import",
    "publish",
    "registry_seed",
    "channel_publish",
    "assignment_issue",
    "entitlement_gate",
    "client_fetch",
    "client_verify",
    "library_add",
    "rollout_replay",
    "activate",
    "gateway_resolve",
    "abuse_tampered_channel",
    "abuse_tampered_assignment",
    "abuse_unsigned_downgrade",
    "abuse_stale_replay",
    "abuse_expired_assignment",
    "abuse_wrong_audience",
    "abuse_conflict_resolution",
    "abuse_poisoned_pointer",
    "abuse_revoked_rollback",
    "audit_report",
)

ABT_ID_RE = re.compile(r"^ABT-[0-9]{2}[a-z]$")


def _load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("UNLIMITED_SKILLS_MCP_PROFILE", raising=False)
    monkeypatch.delenv("UNLIMITED_SKILLS_MCP_AUDIENCE", raising=False)


@pytest.fixture(scope="module")
def harness():
    return _load_module(SCRIPT_PATH, "mcp_distribution_e2e_harness")


@pytest.fixture(scope="module")
def verifier():
    return _load_module(VERIFIER_PATH, "mcp_distribution_e2e_verifier")


@pytest.fixture(scope="module")
def report(harness, tmp_path_factory: pytest.TempPathFactory) -> dict:
    base = tmp_path_factory.mktemp("distribution-e2e")
    return harness.run_distribution_e2e(base_dir=base)


@pytest.fixture(scope="module")
def schema() -> dict:
    return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# The repo's minimal self-contained JSON Schema validator (same stance as
# tests/test_mcp_operator_acceptance.py: no jsonschema dependency), with $ref.

_TYPES = {
    "object": dict,
    "array": list,
    "string": str,
    "number": (int, float),
    "integer": int,
    "boolean": bool,
    "null": type(None),
}


def _check_type(value: object, expected: str, path: str) -> list[str]:
    python_type = _TYPES[expected]
    if expected in ("number", "integer") and isinstance(value, bool):
        return [f"{path}: expected {expected}, got bool"]
    if not isinstance(value, python_type):
        return [f"{path}: expected {expected}, got {type(value).__name__}"]
    return []


def validate(value: object, schema: dict, path: str = "$", root: dict | None = None) -> list[str]:
    if root is None:
        root = schema
    if "$ref" in schema:
        target: object = root
        for part in schema["$ref"].lstrip("#/").split("/"):
            target = target[part]  # type: ignore[index]
        return validate(value, target, path, root)  # type: ignore[arg-type]
    errors: list[str] = []
    if "const" in schema and value != schema["const"]:
        errors.append(f"{path}: must be const {schema['const']!r}")
    if "enum" in schema and value not in schema["enum"]:
        errors.append(f"{path}: {value!r} not in enum {schema['enum']!r}")
    if "type" in schema:
        type_errors = _check_type(value, schema["type"], path)
        if type_errors:
            return errors + type_errors
    if isinstance(value, dict):
        for key in schema.get("required", []):
            if key not in value:
                errors.append(f"{path}: missing required property {key!r}")
        properties = schema.get("properties", {})
        for key, item in value.items():
            if key in properties:
                errors.extend(validate(item, properties[key], f"{path}.{key}", root))
            elif schema.get("additionalProperties") is False:
                errors.append(f"{path}: additional property {key!r} not allowed")
    if isinstance(value, list):
        if "minItems" in schema and len(value) < schema["minItems"]:
            errors.append(f"{path}: fewer than {schema['minItems']} items")
        if "maxItems" in schema and len(value) > schema["maxItems"]:
            errors.append(f"{path}: more than {schema['maxItems']} items")
        if isinstance(schema.get("items"), dict):
            for index, item in enumerate(value):
                errors.extend(validate(item, schema["items"], f"{path}[{index}]", root))
    if isinstance(value, str):
        if "pattern" in schema and not re.search(schema["pattern"], value):
            errors.append(f"{path}: does not match pattern {schema['pattern']!r}")
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if "minimum" in schema and value < schema["minimum"]:
            errors.append(f"{path}: below minimum {schema['minimum']}")
        if "maximum" in schema and value > schema["maximum"]:
            errors.append(f"{path}: above maximum {schema['maximum']}")
    return errors


def _iter_strings(value: object):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for key, item in value.items():
            yield str(key)
            yield from _iter_strings(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            yield from _iter_strings(item)


def _facts_by_name(report: dict) -> dict[str, dict]:
    return {entry["name"]: entry["facts"] for entry in report["steps"]}


# ---------------------------------------------------------------------------
# The full 23-step workflow passes as one flow.


def test_full_run_exits_zero_with_all_23_steps_ok(report: dict) -> None:
    assert report["exit_code"] == 0
    assert report["mode"] == "fixture" and report["ed25519"] is True
    summary = report["summary"]
    assert summary["steps_total"] == 23
    assert summary["steps_selected"] == 23
    assert summary["steps_ok"] == 23
    assert summary["all_ok"] is True
    assert [entry["name"] for entry in report["steps"]] == list(STEP_NAMES)
    assert [entry["step"] for entry in report["steps"]] == list(range(1, 24))
    for entry in report["steps"]:
        assert entry["ok"] is True, entry["name"]
        assert entry["duration_ms"] >= 0, entry["name"]
        assert entry["facts"], entry["name"]


def test_composition_facts_tie_the_layers_together(report: dict) -> None:
    facts = _facts_by_name(report)
    # The carrier key never enters the member's capability trust store.
    assert facts["trust_import"]["carrier_key_in_trust_store"] is False
    # The channel's current pointer, the client's resolution, the gateway's
    # provenance, and the revoked sha are all the SAME published bundle.
    v2 = facts["publish"]["v2_sha_prefix"]
    v1 = facts["publish"]["v1_sha_prefix"]
    assert facts["channel_publish"]["current_sha_prefix"] == v2
    assert facts["client_fetch"]["resolved_sha_prefix"] == v2
    assert facts["activate"]["active_sha_prefix"] == v2
    assert facts["activate"]["previous_sha_prefix"] == v1
    assert facts["gateway_resolve"]["bundle_sha_prefix"] == v2
    assert facts["abuse_revoked_rollback"]["revoked_sha_prefix"] == v2
    assert facts["abuse_revoked_rollback"]["rolled_back_to_prefix"] == v1
    # The entitlement gate produced the exact E24 reason codes.
    gate = facts["entitlement_gate"]
    assert gate["entitled_reason"] == "ok"
    assert gate["unentitled_reason"] == "no_profile_sync_entitlement"
    assert gate["unknown_member_reason"] == "not_registered"
    assert gate["anti_oracle_reason"] == "unknown_or_unauthorized"
    assert gate["denied_body_bytes_moved"] is False
    # Rollout/replay ran BEFORE activation (operator due diligence).
    assert facts["rollout_replay"]["before_activation"] is True
    assert facts["rollout_replay"]["hidden"] == 1


def test_abuse_battery_refusals_are_exact(report: dict) -> None:
    facts = _facts_by_name(report)
    assert facts["abuse_tampered_channel"]["refused"] == "routing_signature_invalid"
    assert facts["abuse_tampered_assignment"]["refused"] == "routing_signature_invalid"
    downgrade = facts["abuse_unsigned_downgrade"]["refused"]
    assert downgrade["channel_stripped"] == "routing_unsigned"
    assert downgrade["summary_unsigned"] == "unsigned_artifact_rejected"
    assert downgrade["summary_forbidden_field"] == "forbidden_field_rejected"
    assert downgrade["channel_version_2"] == "schema_invalid"
    stale = facts["abuse_stale_replay"]
    assert stale["stale_replay_refused"] == "routing_revision_regression"
    assert stale["squatting_refused"] == "channel_identity_mismatch"
    assert facts["abuse_expired_assignment"]["injected_clock_refusal_code"] == -32016
    assert facts["abuse_wrong_audience"]["forced_refusal_code"] == -32018
    assert facts["abuse_poisoned_pointer"]["poisoned_refusal_code"] == -32015
    incident = facts["abuse_revoked_rollback"]
    assert incident["refusal_code"] == -32017
    assert incident["channel_status_never_trust_input"] is True
    assert incident["rollback_with_carrier_offline"] is True
    tie = facts["abuse_conflict_resolution"]
    assert tie["tie_refused_loudly"] == ["tie-a", "tie-b"]
    assert tie["library_state_unchanged"] is True
    audit = facts["audit_report"]
    for code in (-32015, -32016, -32017, -32018):
        assert code in audit["refusal_codes_observed"]
    assert audit["redaction_self_check"] == "PASS"


# ---------------------------------------------------------------------------
# Schema: the live report and the shipped generated example both validate.


def test_report_validates_against_schema(report: dict, schema: dict) -> None:
    assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    assert schema["additionalProperties"] is False
    assert validate(report, schema) == []


def test_shipped_example_validates_and_stays_in_sync(schema: dict) -> None:
    example = json.loads(EXAMPLE_PATH.read_text(encoding="utf-8"))
    assert validate(example, schema) == []
    assert [entry["name"] for entry in example["steps"]] == list(STEP_NAMES)
    assert example["exit_code"] == 0
    assert example["summary"]["all_ok"] is True
    assert all(entry["ok"] is True for entry in example["steps"])
    assert example["abt_coverage"], "the example must claim ABT coverage"


# ---------------------------------------------------------------------------
# ABT-coverage consistency with the E25 abuse-case test plan.


def test_every_claimed_abt_id_exists_in_the_plan(report: dict) -> None:
    plan_text = PLAN_PATH.read_text(encoding="utf-8")
    claimed = set(report["abt_coverage"])
    for entry in report["steps"]:
        claimed.update(entry["abt"])
    assert claimed, "the run must claim ABT coverage"
    for abt_id in sorted(claimed):
        assert ABT_ID_RE.match(abt_id), f"malformed ABT id {abt_id!r}"
        assert abt_id in plan_text, f"{abt_id} is not in the E25 abuse-case test plan"


def test_abt_coverage_equals_the_union_of_step_claims(report: dict) -> None:
    union = sorted({abt_id for entry in report["steps"] for abt_id in entry["abt"]})
    assert report["abt_coverage"] == union
    assert report["summary"]["abt_claimed"] == len(union)
    example = json.loads(EXAMPLE_PATH.read_text(encoding="utf-8"))
    example_union = sorted({abt_id for entry in example["steps"] for abt_id in entry["abt"]})
    assert example["abt_coverage"] == example_union


# ---------------------------------------------------------------------------
# Single-step selection: the workflow prefix ending at NAME.


def test_step_selection_runs_the_prefix(harness, tmp_path: Path) -> None:
    result = harness.run_distribution_e2e(until="publish", base_dir=tmp_path / "prefix")
    assert result["exit_code"] == 0
    assert [entry["name"] for entry in result["steps"]] == [
        "keygen",
        "trust_import",
        "publish",
    ]
    assert result["summary"]["steps_selected"] == 3
    assert result["summary"]["steps_total"] == 23
    assert result["summary"]["all_ok"] is True


def test_unknown_step_is_a_value_error(harness, tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="unknown step"):
        harness.run_distribution_e2e(until="no_such_step", base_dir=tmp_path)


# ---------------------------------------------------------------------------
# Failure injection: each tamper fails exactly the right step, exit 1, and
# the workflow stops there.


def test_tampered_fetched_bundle_fails_the_library_add_step(
    harness, tmp_path: Path
) -> None:
    def corrupt(name: str, ctx) -> None:
        if name == "library_add":
            path = ctx.fetched_paths["team-v1"]
            document = json.loads(path.read_text(encoding="utf-8"))
            document["audience"].append("org:everyone")  # post-signing tamper
            path.write_text(json.dumps(document), encoding="utf-8")

    result = harness.run_distribution_e2e(
        base_dir=tmp_path / "tampered-bundle", before_step=corrupt
    )
    assert result["exit_code"] == 1
    assert result["summary"]["all_ok"] is False
    assert [entry["name"] for entry in result["steps"]] == list(STEP_NAMES[:10]), (
        "the workflow stops at the first failing step"
    )
    failed = result["steps"][-1]
    assert failed["name"] == "library_add" and failed["ok"] is False
    assert "bundle_signature_invalid" in failed["facts"]["error"]


def test_tampered_stored_channel_fails_the_client_fetch_step(
    harness, tmp_path: Path
) -> None:
    def corrupt(name: str, ctx) -> None:
        if name == "client_fetch":
            path = next(ctx.registry.channels_dir.glob("*.channel.json"))
            document = json.loads(path.read_text(encoding="utf-8"))
            document["revision"] = 9  # edited after signing
            path.write_text(json.dumps(document), encoding="utf-8")

    result = harness.run_distribution_e2e(
        base_dir=tmp_path / "tampered-channel", before_step=corrupt
    )
    assert result["exit_code"] == 1
    failed = result["steps"][-1]
    assert failed["name"] == "client_fetch" and failed["ok"] is False
    assert "signature" in failed["facts"]["error"]


def test_failed_step_report_still_validates(harness, tmp_path: Path, schema: dict) -> None:
    def corrupt(name: str, ctx) -> None:
        if name == "library_add":
            path = ctx.fetched_paths["team-v1"]
            path.write_bytes(path.read_bytes() + b" ")

    result = harness.run_distribution_e2e(
        base_dir=tmp_path / "tampered", before_step=corrupt
    )
    assert result["exit_code"] == 1
    assert validate(result, schema) == []


# ---------------------------------------------------------------------------
# Leak-grep: no key material, no full hashes, no local paths, no forbidden
# field names -- in the report, the shipped example, and the CLI outputs.


def test_report_has_no_secret_looking_values_or_local_paths(harness, report: dict) -> None:
    rendered = (
        list(_iter_strings(report))
        + harness.format_distribution_report(report).splitlines()
        + json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True).splitlines()
    )
    for text in rendered:
        assert not looks_secret(text), f"secret-looking string in report: {text[:48]}..."
        assert not PATH_PATTERN.search(text), f"local path in report: {text[:48]}..."


def test_report_carries_no_forbidden_field_names(harness, verifier, report: dict) -> None:
    assert harness.FORBIDDEN_FIELDS == verifier.FORBIDDEN_FIELDS, (
        "the harness and the verifier must encode the SAME E24 denylist"
    )
    assert harness.forbidden_field_names(report) == set()
    example = json.loads(EXAMPLE_PATH.read_text(encoding="utf-8"))
    assert harness.forbidden_field_names(example) == set()


def test_example_has_no_secret_looking_values_or_local_paths() -> None:
    example = json.loads(EXAMPLE_PATH.read_text(encoding="utf-8"))
    for text in _iter_strings(example):
        assert not looks_secret(text)
        assert not PATH_PATTERN.search(text)


# ---------------------------------------------------------------------------
# Containment: an explicit base_dir means no temp dir of its own and no
# writes anywhere near the real managed trust store or default audit log.


def test_runner_stays_inside_its_base_dir(
    harness, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def forbidden(*args, **kwargs):  # pragma: no cover - failure path
        raise AssertionError("the runner must not create temp dirs when base_dir is given")

    monkeypatch.setattr(harness.tempfile, "mkdtemp", forbidden)
    repo_store = ROOT / ".unlimited-skills-trust"
    repo_library = ROOT / ".unlimited-skills-bundles"
    repo_audit = ROOT / ".learning" / "mcp-audit.jsonl"
    before = {path: path.exists() for path in (repo_store, repo_library, repo_audit)}
    base = tmp_path / "contained"
    result = harness.run_distribution_e2e(base_dir=base)
    assert result["exit_code"] == 0
    assert (base / "trust-store" / "trusted-keys.json").is_file()
    assert (base / "bundle-library" / "library-state.json").is_file()
    assert (base / "audit" / "mcp-audit.jsonl").is_file()
    assert (base / "fixture-registry" / "entitlements.json").is_file()
    assert (base / "fixture-registry" / "bundles").is_dir()
    assert (base / "fixture-registry" / "summaries").is_dir()
    for path, existed in before.items():
        assert path.exists() == existed, f"{path.name} was touched by the runner"


# ---------------------------------------------------------------------------
# CLI surface.


def test_cli_json_step_selection(harness, capsys: pytest.CaptureFixture[str]) -> None:
    code = harness.main(["--json", "--fixture-mode", "--step", "trust_import"])
    out = capsys.readouterr().out
    assert code == 0
    document = json.loads(out)
    assert document["report_type"] == "mcp-distribution-e2e-report"
    assert [entry["name"] for entry in document["steps"]] == ["keygen", "trust_import"]
    assert document["summary"]["all_ok"] is True
    for line in out.splitlines():
        assert not looks_secret(line)
        assert not PATH_PATTERN.search(line)


def test_cli_out_writes_json_and_text(
    harness, tmp_path: Path, capsys: pytest.CaptureFixture[str], schema: dict
) -> None:
    out_dir = tmp_path / "out"
    code = harness.main(["--step", "publish", "--out", str(out_dir)])
    captured = capsys.readouterr().out
    assert code == 0
    document = json.loads(
        (out_dir / "distribution-e2e-report.json").read_text(encoding="utf-8")
    )
    assert validate(document, schema) == []
    text = (out_dir / "distribution-e2e-report.txt").read_text(encoding="utf-8")
    assert "publish: ok" in text
    assert "publish: ok" in captured, "text mode prints the human report"
    for line in captured.splitlines():
        assert not looks_secret(line)
        assert not PATH_PATTERN.search(line)


def test_cli_unknown_step_exits_two(harness, capsys: pytest.CaptureFixture[str]) -> None:
    assert harness.main(["--step", "nonsense"]) == 2
    assert "unknown step" in capsys.readouterr().err


def test_text_report_lists_every_step(harness, report: dict) -> None:
    text = harness.format_distribution_report(report)
    for index, name in enumerate(STEP_NAMES, start=1):
        assert f"[{index:>2}/23] {name}: ok" in text
    assert "ALL OK" in text
    assert "ABT coverage" in text


# ---------------------------------------------------------------------------
# The thin verifier: passes the good report, fails the broken ones.


def test_verifier_passes_the_good_report(
    verifier, report: dict, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = tmp_path / "report.json"
    path.write_text(json.dumps(report, sort_keys=True), encoding="utf-8")
    assert verifier.main([str(path)]) == 0
    assert "verified" in capsys.readouterr().out


def test_verifier_fails_a_prefix_run(harness, verifier, tmp_path: Path, schema: dict) -> None:
    prefix = harness.run_distribution_e2e(until="publish", base_dir=tmp_path / "p")
    findings = verifier.verify_report_document(prefix, schema)
    assert any("FULL workflow" in finding for finding in findings)


def test_verifier_fails_broken_reports(verifier, report: dict, schema: dict) -> None:
    good = json.loads(json.dumps(report, sort_keys=True))
    assert verifier.verify_report_document(good, schema) == []
    failed_step = json.loads(json.dumps(good))
    failed_step["steps"][0]["ok"] = False
    assert any(
        "not ok" in finding
        for finding in verifier.verify_report_document(failed_step, schema)
    )
    forbidden = json.loads(json.dumps(good))
    forbidden["steps"][0]["facts"]["private_key"] = "should never appear"
    assert any(
        "forbidden field" in finding
        for finding in verifier.verify_report_document(forbidden, schema)
    )
    secret = json.loads(json.dumps(good))
    secret["steps"][0]["facts"]["note"] = "a1b2c3d4" * 5  # 40-char hex-like blob
    assert any(
        "secret-shaped" in finding
        for finding in verifier.verify_report_document(secret, schema)
    )
    drained = json.loads(json.dumps(good))
    for entry in drained["steps"]:
        entry["abt"] = []
    drained["abt_coverage"] = []
    drained["summary"]["abt_claimed"] = 0
    assert any(
        "abt_coverage is empty" in finding
        for finding in verifier.verify_report_document(drained, schema)
    )
    out_of_sync = json.loads(json.dumps(good))
    out_of_sync["abt_coverage"] = out_of_sync["abt_coverage"][:-1]
    out_of_sync["summary"]["abt_claimed"] -= 1
    assert any(
        "union" in finding
        for finding in verifier.verify_report_document(out_of_sync, schema)
    )


def test_verifier_cli_missing_file_exits_two(verifier, capsys) -> None:
    assert verifier.main([str(ROOT / "no-such-report.json")]) == 2
    assert "missing or unreadable" in capsys.readouterr().err


# ---------------------------------------------------------------------------
# Docs sync: the harness doc and the cross-referenced docs stay honest.


def test_doc_describes_every_step_and_the_boundaries() -> None:
    text = DOC_PATH.read_text(encoding="utf-8")
    for name in STEP_NAMES:
        assert name in text, f"doc missing step {name}"
    assert "run-mcp-profile-distribution-fixture-e2e.py" in text
    assert "verify-mcp-profile-distribution-e2e.py" in text
    assert "mcp-distribution-e2e-report.schema.json" in text
    assert "distribution-e2e-report.example.json" in text
    for phrase in (
        "no hosted calls",
        "no real entitlement service",
        "no production signing keys",
        "no network",
        "fail-closed",
    ):
        assert phrase in text, f"doc missing boundary phrase: {phrase}"


def test_cross_referenced_docs_point_at_the_harness() -> None:
    for name in ("mcp-bundle-distribution.md", "mcp-distribution-abuse-test-plan.md"):
        text = (ROOT / "docs" / name).read_text(encoding="utf-8")
        assert "run-mcp-profile-distribution-fixture-e2e.py" in text, name
        assert "mcp-distribution-e2e-harness.md" in text, name
