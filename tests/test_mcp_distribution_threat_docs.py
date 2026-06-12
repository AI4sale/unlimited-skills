"""E25 docs-consistency gate: distribution threat model vs abuse-case test plan.

E25 is design-only (no implementation, nothing hosted): the deliverables are
``docs/mcp-distribution-threat-model.md`` (threat classes ``DT-01``..``DT-23``
covering the E23 client design AND the E24 registry contract) and
``docs/mcp-distribution-abuse-test-plan.md`` (the consolidated abuse-case test
plan with ids ``ABT-NNx``). These tests keep the two documents honest:

- every threat class in the model has a matching test-plan section and vice
  versa, with the required fields present in each;
- attacker positions and test owners stay within their fixed vocabularies;
- abuse-case test ids agree between the two documents, match their threat
  numbers, and the traceability table covers every threat exactly once;
- every cited refusal/reason code belongs to a known family: the reserved
  client codes ``-32001``..``-32019`` (numeric and by name) or the E24
  registry reason-code names — and the plan's coverage table is complete;
- no TODO/TBD markers survive in either document.

No network, no signing, no implementation behavior — pure document parsing.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODEL_PATH = ROOT / "docs" / "mcp-distribution-threat-model.md"
PLAN_PATH = ROOT / "docs" / "mcp-distribution-abuse-test-plan.md"

MODEL_TEXT = MODEL_PATH.read_text(encoding="utf-8")
PLAN_TEXT = PLAN_PATH.read_text(encoding="utf-8")

EXPECTED_THREAT_IDS = [f"DT-{index:02d}" for index in range(1, 24)]

ATTACKER_POSITIONS = {
    "malicious publisher",
    "compromised key",
    "malicious registry",
    "network MitM",
    "malicious teammate",
    "compromised client",
    "insider-operator",
}

OWNER_VOCABULARY = (
    "client suite",
    "future registry suite",
    "end-to-end (E21-style)",
)

MODEL_FIELDS = (
    "- **Attacker position:**",
    "- **Description:**",
    "- **Impact:**",
    "- **Existing mitigation:**",
    "- **Residual risk:**",
    "- **Abuse-case test",
)

PLAN_FIELDS = (
    "- **Test IDs:**",
    "- **Fixtures:**",
    "- **Pass criteria:**",
    "- **Owner:**",
)

# Reserved client refusal codes: -32001..-32019 (E07..E14 families).
CLIENT_CODE_RANGE = set(range(-32019, -32000))

KNOWN_CLIENT_CODE_NAMES = {
    "tool_not_visible",
    "tool_not_callable",
    "profile_not_found",
    "profile_invalid",
    "bundle_signature_invalid",
    "bundle_expired",
    "bundle_revoked",
    "bundle_audience_mismatch",
    "bundle_key_missing",
}

# The E24 registry contract's reason-code vocabulary (access-check subset
# plus publish/request codes), as the contract document states it.
KNOWN_REGISTRY_CODES = {
    "ok",
    "not_registered",
    "device_proof_invalid",
    "no_profile_sync_entitlement",
    "unauthorized_install",
    "audience_mismatch",
    "assignment_expired",
    "assignment_revoked",
    "bundle_revoked",
    "retention_expired",
    "unknown_or_unauthorized",
    "publisher_not_authorized",
    "unsigned_artifact_rejected",
    "owner_key_mismatch",
    "schema_invalid",
    "forbidden_field_rejected",
    "revision_regression",
}

# Backticked identifiers that legitimately contain code-like marker words but
# are NOT refusal codes (fixture/scenario/CRL-field names cited by the docs).
NON_CODE_IDENTIFIER_ALLOWLIST = {
    "revoked_key_ids",
    "revoked_bundles",
    "scenario_revoked_bundle",
    "scenario_crl_outage",
}

CODE_MARKERS = (
    "invalid",
    "revoked",
    "expired",
    "mismatch",
    "rejected",
    "regression",
    "entitlement",
    "authorized",
    "registered",
    "missing",
    "denied",
    "not_found",
)

HEADING_RE = re.compile(r"^### (DT-\d{2}) — (.+)$", re.MULTILINE)
ABT_ID_RE = re.compile(r"ABT-(\d{2})([a-z])")
NUMERIC_CODE_RE = re.compile(r"-32\d{3}")
BACKTICK_TOKEN_RE = re.compile(r"`([a-z][a-z0-9_]+)`")


def split_threat_blocks(text: str) -> dict[str, str]:
    """Map DT-id -> the text of its ### block (up to the next heading)."""
    blocks: dict[str, str] = {}
    matches = list(HEADING_RE.finditer(text))
    boundaries = [
        match.start() for match in re.finditer(r"^#{2,3} ", text, re.MULTILINE)
    ]
    for match in matches:
        start = match.end()
        following = [b for b in boundaries if b > match.start()]
        end = following[0] if following else len(text)
        assert match.group(1) not in blocks, f"duplicate heading {match.group(1)}"
        blocks[match.group(1)] = text[start:end]
    return blocks


MODEL_BLOCKS = split_threat_blocks(MODEL_TEXT)
PLAN_BLOCKS = split_threat_blocks(PLAN_TEXT)


def abt_ids(text: str) -> set[str]:
    return {f"ABT-{num}{letter}" for num, letter in ABT_ID_RE.findall(text)}


def plan_text_before_coverage() -> str:
    index = PLAN_TEXT.index("## Refusal-code coverage")
    return PLAN_TEXT[:index]


def coverage_table_rows() -> list[str]:
    section_start = PLAN_TEXT.index("## Refusal-code coverage")
    section = PLAN_TEXT[section_start:]
    next_heading = re.search(r"^## (?!Refusal)", section, re.MULTILINE)
    if next_heading:
        section = section[: next_heading.start()]
    return [
        line
        for line in section.splitlines()
        if line.startswith("| `") and not line.startswith("| Code")
    ]


def coverage_codes() -> tuple[set[int], set[str]]:
    """(numeric client codes, registry reason-code names) from the table."""
    numeric: set[int] = set()
    registry_names: set[str] = set()
    for row in coverage_table_rows():
        cells = [cell.strip() for cell in row.strip().strip("|").split("|")]
        assert len(cells) == 3, f"coverage row needs 3 cells: {row!r}"
        code_cell, family_cell = cells[0], cells[1]
        numbers = NUMERIC_CODE_RE.findall(code_cell)
        if numbers:
            assert family_cell.startswith("client"), (
                f"numeric code row must be client-family: {row!r}"
            )
            numeric.update(int(value) for value in numbers)
        else:
            assert family_cell == "registry (E24)", (
                f"name-only code row must be registry-family: {row!r}"
            )
            tokens = BACKTICK_TOKEN_RE.findall(code_cell)
            assert tokens, f"no code token in coverage row: {row!r}"
            registry_names.update(tokens)
    return numeric, registry_names


def test_threat_ids_match_and_are_contiguous() -> None:
    assert sorted(MODEL_BLOCKS) == EXPECTED_THREAT_IDS
    assert sorted(PLAN_BLOCKS) == EXPECTED_THREAT_IDS


def test_threat_titles_agree_between_documents() -> None:
    model_titles = dict(HEADING_RE.findall(MODEL_TEXT))
    plan_titles = dict(HEADING_RE.findall(PLAN_TEXT))
    assert model_titles == plan_titles


def test_model_blocks_have_required_fields() -> None:
    for threat_id, block in MODEL_BLOCKS.items():
        for field in MODEL_FIELDS:
            assert field in block, f"{threat_id}: missing field {field!r}"


def test_model_attacker_positions_use_the_vocabulary() -> None:
    for threat_id, block in MODEL_BLOCKS.items():
        match = re.search(r"- \*\*Attacker position:\*\* (.+)", block)
        assert match, f"{threat_id}: no attacker-position line"
        positions = [part.strip() for part in match.group(1).split(";")]
        assert positions, f"{threat_id}: empty attacker position"
        for position in positions:
            assert position in ATTACKER_POSITIONS, (
                f"{threat_id}: unknown attacker position {position!r}"
            )


def test_model_abuse_cases_are_given_when_then() -> None:
    for threat_id, block in MODEL_BLOCKS.items():
        start = block.index("- **Abuse-case test")
        abuse_text = block[start:]
        assert "Given" in abuse_text, f"{threat_id}: abuse case lacks Given"
        assert re.search(r"\bwhen\b", abuse_text), (
            f"{threat_id}: abuse case lacks when"
        )
        assert re.search(r"\bthen\b", abuse_text), (
            f"{threat_id}: abuse case lacks then"
        )


def test_plan_blocks_have_required_fields() -> None:
    for threat_id, block in PLAN_BLOCKS.items():
        for field in PLAN_FIELDS:
            assert field in block, f"{threat_id}: missing field {field!r}"


def test_plan_owners_use_the_vocabulary() -> None:
    for threat_id, block in PLAN_BLOCKS.items():
        match = re.search(r"- \*\*Owner:\*\* (.+?)(?=\n\n|\n### |\Z)", block, re.DOTALL)
        assert match, f"{threat_id}: no owner line"
        owner_text = " ".join(match.group(1).split())
        segments = [part.strip() for part in owner_text.split(";")]
        for segment in segments:
            assert segment.startswith(OWNER_VOCABULARY), (
                f"{threat_id}: owner segment {segment!r} not in vocabulary"
            )


def test_abuse_ids_match_their_threat_numbers() -> None:
    for blocks in (MODEL_BLOCKS, PLAN_BLOCKS):
        for threat_id, block in blocks.items():
            ids = abt_ids(block)
            assert ids, f"{threat_id}: no ABT test ids"
            expected_prefix = f"ABT-{threat_id[3:]}"
            for test_id in ids:
                assert test_id.startswith(expected_prefix), (
                    f"{threat_id}: test id {test_id} numbered for another threat"
                )


def test_model_and_plan_abuse_ids_agree_per_threat() -> None:
    for threat_id in EXPECTED_THREAT_IDS:
        model_ids = abt_ids(MODEL_BLOCKS[threat_id])
        plan_ids = abt_ids(PLAN_BLOCKS[threat_id])
        assert model_ids == plan_ids, (
            f"{threat_id}: model ids {sorted(model_ids)} != plan ids "
            f"{sorted(plan_ids)}"
        )


def traceability_rows() -> dict[str, tuple[str, set[str], str]]:
    rows: dict[str, tuple[str, set[str], str]] = {}
    for line in PLAN_TEXT.splitlines():
        if not re.match(r"^\| DT-\d{2} \|", line):
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        assert len(cells) == 4, f"traceability row needs 4 cells: {line!r}"
        threat_id, mitigation, ids_cell, owner_cell = cells
        assert threat_id not in rows, f"duplicate traceability row {threat_id}"
        rows[threat_id] = (mitigation, abt_ids(ids_cell), owner_cell)
    return rows


def test_traceability_table_is_complete() -> None:
    rows = traceability_rows()
    assert sorted(rows) == EXPECTED_THREAT_IDS
    for threat_id, (mitigation, row_ids, owner_cell) in rows.items():
        assert mitigation, f"{threat_id}: empty mitigation cell"
        section_ids = abt_ids(PLAN_BLOCKS[threat_id])
        assert row_ids == section_ids, (
            f"{threat_id}: table ids {sorted(row_ids)} != section ids "
            f"{sorted(section_ids)}"
        )
        segments = [part.strip() for part in owner_cell.split(";")]
        for segment in segments:
            assert segment.startswith(OWNER_VOCABULARY), (
                f"{threat_id}: table owner {segment!r} not in vocabulary"
            )


def cited_numeric_codes() -> set[int]:
    scan_text = MODEL_TEXT + plan_text_before_coverage()
    return {int(value) for value in NUMERIC_CODE_RE.findall(scan_text)}


def test_every_cited_numeric_code_is_in_the_client_family() -> None:
    table_numeric, _ = coverage_codes()
    for code in cited_numeric_codes() | table_numeric:
        assert code in CLIENT_CODE_RANGE, f"unknown client code {code}"


def test_coverage_table_matches_cited_numeric_codes() -> None:
    table_numeric, _ = coverage_codes()
    assert table_numeric == cited_numeric_codes()


def test_registry_codes_are_known_and_fully_covered() -> None:
    table_numeric, table_registry = coverage_codes()
    assert table_registry <= KNOWN_REGISTRY_CODES, (
        f"unknown registry codes in table: "
        f"{sorted(table_registry - KNOWN_REGISTRY_CODES)}"
    )
    scan_text = MODEL_TEXT + plan_text_before_coverage()
    cited = set(BACKTICK_TOKEN_RE.findall(scan_text)) & KNOWN_REGISTRY_CODES
    assert cited == table_registry, (
        f"coverage table out of sync with cited registry codes: "
        f"cited-not-covered {sorted(cited - table_registry)}, "
        f"covered-not-cited {sorted(table_registry - cited)}"
    )
    assert table_numeric, "coverage table lost its client-code rows"


def test_code_like_identifiers_belong_to_a_known_family() -> None:
    known = (
        KNOWN_CLIENT_CODE_NAMES
        | KNOWN_REGISTRY_CODES
        | NON_CODE_IDENTIFIER_ALLOWLIST
    )
    for name, text in (("model", MODEL_TEXT), ("plan", PLAN_TEXT)):
        for token in set(BACKTICK_TOKEN_RE.findall(text)):
            if any(marker in token for marker in CODE_MARKERS):
                assert token in known, (
                    f"{name}: code-like identifier {token!r} is not a known "
                    f"client code name, registry reason code, or allowlisted "
                    f"fixture name"
                )


def test_no_unfinished_markers_remain() -> None:
    for name, text in (("model", MODEL_TEXT), ("plan", PLAN_TEXT)):
        for marker in ("TODO", "TBD", "FIXME"):
            assert marker not in text, f"{name}: contains {marker}"


def test_documents_state_branch_lineage() -> None:
    lineage = "docs/v04-e23-mcp-bundle-distribution-design-v1"
    branch = "docs/v04-e25-mcp-distribution-threat-model-abuse-cases"
    for name, text in (("model", MODEL_TEXT), ("plan", PLAN_TEXT)):
        assert lineage in text, f"{name}: missing base-branch lineage"
        assert branch in text, f"{name}: missing own branch name"
