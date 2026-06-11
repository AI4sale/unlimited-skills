"""E21: MCP profile stack end-to-end operator acceptance suite.

Proves the contract of docs/mcp-operator-acceptance.md against
``scripts/run-mcp-operator-acceptance.py``:

- the fixture-mode runner executes the 12-step operator workflow (publish
  -> import key -> verify -> add -> rollout-plan -> replay-audit ->
  activate -> gateway resolve -> incident drill -> rollback ->
  audit/report) as ONE flow over the REAL modules and exits 0 with every
  step ok;
- the per-step key facts carry the composition evidence: the publish
  self-check via the real E14 path, verify-before-store at add, sensible
  rollout-plan counts, a replay recommendation, the exact ``-32017``
  revocation refusal at BOTH the library and the gateway, the walk-back to
  the prior good bundle, and an audit report with the refusal visible and
  a passing redaction self-check;
- the JSON report validates against
  ``schemas/mcp-operator-acceptance-report.schema.json`` (the repo's
  minimal self-contained validator pattern) and the shipped generated
  example validates and stays in sync;
- ``--step NAME`` runs and reports the workflow prefix ending at NAME;
- failure injection: a bundle corrupted between publish and library add
  makes exactly the ``library_add`` step fail (``bundle_signature_invalid``)
  with exit 1 and stops the workflow;
- leak-grep: every string in the report and in both CLI output modes is
  re-scanned with the audit writer's own ``looks_secret``/path heuristics
  -- no key material, no full hashes, no local paths beyond basenames;
- containment: with an explicit ``base_dir`` the runner never creates its
  own temp directory and never touches the repo's managed trust store or
  default audit log.
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
SCRIPT_PATH = ROOT / "scripts" / "run-mcp-operator-acceptance.py"
SCHEMA_PATH = ROOT / "schemas" / "mcp-operator-acceptance-report.schema.json"
EXAMPLE_PATH = ROOT / "examples" / "mcp" / "operator-acceptance-report.example.json"
DOC_PATH = ROOT / "docs" / "mcp-operator-acceptance.md"

STEP_NAMES = (
    "keygen",
    "trust_import",
    "publish",
    "verify",
    "library_add",
    "rollout_plan",
    "replay_audit",
    "activate",
    "gateway_resolve",
    "incident_drill",
    "rollback",
    "audit_report",
)


def _load_suite_module():
    spec = importlib.util.spec_from_file_location("mcp_operator_acceptance", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("UNLIMITED_SKILLS_MCP_PROFILE", raising=False)
    monkeypatch.delenv("UNLIMITED_SKILLS_MCP_AUDIENCE", raising=False)


@pytest.fixture(scope="module")
def suite():
    return _load_suite_module()


@pytest.fixture(scope="module")
def report(suite, tmp_path_factory: pytest.TempPathFactory) -> dict:
    base = tmp_path_factory.mktemp("operator-acceptance")
    return suite.run_acceptance(base_dir=base)


@pytest.fixture(scope="module")
def schema() -> dict:
    return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# The repo's minimal self-contained JSON Schema validator (same stance as
# tests/test_mcp_incident_drill.py: no jsonschema dependency), with $ref.

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
# The full 12-step workflow passes as one flow.


def test_full_run_exits_zero_with_all_12_steps_ok(report: dict) -> None:
    assert report["exit_code"] == 0
    assert report["mode"] == "fixture" and report["ed25519"] is True
    summary = report["summary"]
    assert summary == {
        "steps_total": 12,
        "steps_selected": 12,
        "steps_ok": 12,
        "all_ok": True,
    }
    assert [entry["name"] for entry in report["steps"]] == list(STEP_NAMES)
    assert [entry["step"] for entry in report["steps"]] == list(range(1, 13))
    for entry in report["steps"]:
        assert entry["ok"] is True, entry["name"]
        assert entry["duration_ms"] >= 0, entry["name"]
        assert entry["facts"], entry["name"]


def test_composition_facts_tie_the_layers_together(report: dict) -> None:
    facts = _facts_by_name(report)
    # One keypair flows from keygen through trust import.
    assert facts["keygen"]["dev_only"] is True
    assert facts["trust_import"]["fingerprint"] == facts["keygen"]["fingerprint"]
    assert facts["trust_import"]["public_keys_only"] is True
    # The ceremony self-check and the standalone verify are the real E14 path.
    assert facts["publish"]["self_check"] == "resolve_bundle_state (E14)"
    assert facts["verify"]["verified_via"] == "resolve_bundle_state (E14)"
    assert facts["verify"]["profile"] == "dev"
    # The library stored exactly the published bundles, verified first.
    assert facts["library_add"]["added"] == 2
    assert facts["library_add"]["verified_before_store"] is True
    prefixes = {entry["sha_prefix"] for entry in facts["library_add"]["entries"]}
    assert prefixes == {facts["publish"]["v1_sha_prefix"], facts["publish"]["v2_sha_prefix"]}
    # The rollout dry-run produced a sensible plan over the fixture tools.
    rollout = facts["rollout_plan"]
    assert rollout["mode"] == "enforced" and rollout["blockers"] == 0
    assert (rollout["tools_total"], rollout["visible"], rollout["callable"]) == (3, 2, 2)
    assert rollout["hidden"] == 1
    # The replay produced a recommendation over the synthetic history.
    replay = facts["replay_audit"]
    assert replay["recommendation_present"] is True
    assert replay["recommendation"] in ("safe", "safe_with_warnings")
    assert replay["replayed"] == 6 and replay["newly_denied"] == 1
    # Activation history: v1 then v2, and the gateway resolved the ACTIVE v2.
    assert facts["activate"]["active"] == "team-v2"
    assert facts["activate"]["previous_sha_prefix"] == facts["publish"]["v1_sha_prefix"]
    gateway = facts["gateway_resolve"]
    assert gateway["profile"] == "dev" and gateway["require_signed_profiles"] is True
    assert gateway["bundle_sha_prefix"] == facts["publish"]["v2_sha_prefix"]
    assert gateway["legacy_export_hidden"] is True


def test_incident_rollback_and_audit_facts(report: dict) -> None:
    facts = _facts_by_name(report)
    incident = facts["incident_drill"]
    assert incident["refusal_code"] == -32017
    assert incident["refusal_name"] == "bundle_revoked"
    assert incident["activation_refused"] is True
    assert incident["gateway_fail_closed"] is True
    assert incident["revoked_sha_prefix"] == facts["publish"]["v2_sha_prefix"]
    rollback = facts["rollback"]
    assert rollback["rolled_back_to"] == "team-v1"
    assert rollback["rolled_back_sha_prefix"] == facts["publish"]["v1_sha_prefix"]
    assert rollback["re_resolve_ok"] is True and rollback["active_profile"] == "dev"
    audit = facts["audit_report"]
    assert audit["refusal_rows"] >= 1
    assert -32017 in audit["refusal_codes_observed"]
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


# ---------------------------------------------------------------------------
# Single-step selection: the workflow prefix ending at NAME.


def test_step_selection_runs_the_prefix(suite, tmp_path: Path) -> None:
    result = suite.run_acceptance(until="trust_import", base_dir=tmp_path / "prefix")
    assert result["exit_code"] == 0
    assert [entry["name"] for entry in result["steps"]] == ["keygen", "trust_import"]
    assert result["summary"]["steps_selected"] == 2
    assert result["summary"]["steps_total"] == 12
    assert result["summary"]["all_ok"] is True


def test_unknown_step_is_a_value_error(suite, tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="unknown step"):
        suite.run_acceptance(until="no_such_step", base_dir=tmp_path)


# ---------------------------------------------------------------------------
# Failure injection: corrupting the bundle between publish and library add
# makes exactly the library_add step fail, exit 1, and stops the workflow.


def test_corrupted_bundle_fails_the_library_add_step(suite, tmp_path: Path) -> None:
    def corrupt(name: str, ctx) -> None:
        if name == "library_add":
            path = ctx.bundle_paths["team-v1"]
            document = json.loads(path.read_text(encoding="utf-8"))
            document["audience"].append("org:everyone")  # post-signing tamper
            path.write_text(json.dumps(document), encoding="utf-8")

    result = suite.run_acceptance(base_dir=tmp_path / "tampered", before_step=corrupt)
    assert result["exit_code"] == 1
    assert result["summary"]["all_ok"] is False
    assert [entry["name"] for entry in result["steps"]] == [
        "keygen",
        "trust_import",
        "publish",
        "verify",
        "library_add",
    ], "the workflow stops at the first failing step"
    failed = result["steps"][-1]
    assert failed["ok"] is False
    assert "bundle_signature_invalid" in failed["facts"]["error"]
    assert result["summary"]["steps_ok"] == 4


def test_failed_step_report_still_validates(suite, tmp_path: Path, schema: dict) -> None:
    def corrupt(name: str, ctx) -> None:
        if name == "library_add":
            path = ctx.bundle_paths["team-v1"]
            path.write_bytes(path.read_bytes() + b" ")

    result = suite.run_acceptance(base_dir=tmp_path / "tampered", before_step=corrupt)
    assert result["exit_code"] == 1
    assert validate(result, schema) == []


# ---------------------------------------------------------------------------
# Leak-grep: no key material, no full hashes, no local paths -- in the
# report, the shipped example, and both CLI output renderings (the audit
# writer's own heuristics, reused verbatim).


def test_report_has_no_secret_looking_values_or_local_paths(suite, report: dict) -> None:
    rendered = (
        list(_iter_strings(report))
        + suite.format_acceptance_report(report).splitlines()
        + json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True).splitlines()
    )
    for text in rendered:
        assert not looks_secret(text), f"secret-looking string in report: {text[:48]}..."
        assert not PATH_PATTERN.search(text), f"local path in report: {text[:48]}..."


def test_example_has_no_secret_looking_values_or_local_paths() -> None:
    example = json.loads(EXAMPLE_PATH.read_text(encoding="utf-8"))
    for text in _iter_strings(example):
        assert not looks_secret(text)
        assert not PATH_PATTERN.search(text)


# ---------------------------------------------------------------------------
# Containment: an explicit base_dir means no temp dir of its own and no
# writes anywhere near the real managed trust store or default audit log.


def test_runner_stays_inside_its_base_dir(
    suite, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def forbidden(*args, **kwargs):  # pragma: no cover - failure path
        raise AssertionError("the runner must not create temp dirs when base_dir is given")

    monkeypatch.setattr(suite.tempfile, "mkdtemp", forbidden)
    repo_store = ROOT / ".unlimited-skills-trust"
    repo_library = ROOT / ".unlimited-skills-bundles"
    repo_audit = ROOT / ".learning" / "mcp-audit.jsonl"
    before = {path: path.exists() for path in (repo_store, repo_library, repo_audit)}
    base = tmp_path / "contained"
    result = suite.run_acceptance(base_dir=base)
    assert result["exit_code"] == 0
    assert (base / "trust-store" / "trusted-keys.json").is_file()
    assert (base / "bundle-library" / "library-state.json").is_file()
    assert (base / "audit" / "mcp-audit.jsonl").is_file()
    assert (base / "history" / "mcp-audit.jsonl").is_file()
    assert (base / "keys").is_dir() and (base / "incoming").is_dir()
    for path, existed in before.items():
        assert path.exists() == existed, f"{path.name} was touched by the runner"


# ---------------------------------------------------------------------------
# CLI surface.


def test_cli_json_step_selection(suite, capsys: pytest.CaptureFixture[str]) -> None:
    code = suite.main(["--json", "--step", "publish"])
    out = capsys.readouterr().out
    assert code == 0
    document = json.loads(out)
    assert document["report_type"] == "mcp-operator-acceptance-report"
    assert [entry["name"] for entry in document["steps"]] == [
        "keygen",
        "trust_import",
        "publish",
    ]
    assert document["summary"]["all_ok"] is True
    for line in out.splitlines():
        assert not looks_secret(line)
        assert not PATH_PATTERN.search(line)


def test_cli_out_writes_json_and_text(
    suite, tmp_path: Path, capsys: pytest.CaptureFixture[str], schema: dict
) -> None:
    out_dir = tmp_path / "out"
    code = suite.main(["--step", "verify", "--out", str(out_dir)])
    captured = capsys.readouterr().out
    assert code == 0
    document = json.loads(
        (out_dir / "operator-acceptance-report.json").read_text(encoding="utf-8")
    )
    assert validate(document, schema) == []
    text = (out_dir / "operator-acceptance-report.txt").read_text(encoding="utf-8")
    assert "verify: ok" in text and "ALL OK" in text
    assert "verify: ok" in captured, "text mode prints the human report"
    for line in captured.splitlines():
        assert not looks_secret(line)
        assert not PATH_PATTERN.search(line)


def test_cli_unknown_step_exits_two(suite, capsys: pytest.CaptureFixture[str]) -> None:
    assert suite.main(["--step", "nonsense"]) == 2
    assert "unknown step" in capsys.readouterr().err


def test_text_report_lists_every_step(suite, report: dict) -> None:
    text = suite.format_acceptance_report(report)
    for index, name in enumerate(STEP_NAMES, start=1):
        assert f"[{index:>2}/12] {name}: ok" in text
    assert "ALL OK" in text


# ---------------------------------------------------------------------------
# Docs sync: the onboarding doc and the cross-referenced docs stay honest.


def test_doc_describes_every_step_and_the_boundaries(suite) -> None:
    text = DOC_PATH.read_text(encoding="utf-8")
    for name in STEP_NAMES:
        assert f"**{name}**" in text, f"doc missing step {name}"
    assert "run-mcp-operator-acceptance.py" in text
    assert "-32017" in text and "bundle_revoked" in text
    for phrase in (
        "no production signing keys",
        "no registry sync",
        "no hosted anything",
        "no OAuth upstreams",
        "no MCP resources or prompts",
    ):
        assert phrase in text, f"doc missing boundary phrase: {phrase}"


def test_cross_referenced_docs_point_at_the_suite() -> None:
    for name in ("mcp-bundle-library.md", "mcp-incident-runbook.md"):
        text = (ROOT / "docs" / name).read_text(encoding="utf-8")
        assert "run-mcp-operator-acceptance.py" in text, name
        assert "mcp-operator-acceptance.md" in text, name
