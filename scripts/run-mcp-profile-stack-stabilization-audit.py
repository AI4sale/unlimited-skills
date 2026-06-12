"""E22: MCP profile stack stabilization audit (consistency map, read-only).

NOT a new runtime module -- a static + light-dynamic CONSISTENCY MAP of the
whole MCP profile stack (E06-E21 plus the E12B warm cache), audited over the
repository itself across six dimensions:

1. ``refusal_codes``  -- the reserved JSON-RPC code registry (-32001..-32019):
   collected from the code constants (gateway.py / profiles.py / bundles.py),
   the inspector's code->name table, the rollout/publisher name tables, and
   every docs table; asserts no duplicates, no gaps in the claimed range, and
   code -> name agreement everywhere a name is claimed.
2. ``cli_taxonomy``   -- every ``unlimited-skills mcp ...`` subcommand (the
   real argparse tree from ``build_parser``) has a docs mention and a
   CHANGELOG mention, offers ``--json`` where it makes sense, and the flag
   vocabulary stays uniform (``--out``, ``--store-dir``/``--library-dir``).
   Flag-naming inconsistencies are REPORTED, never auto-fixed.
3. ``schemas``        -- every ``schemas/mcp-*.schema.json`` is valid JSON,
   declares draft 2020-12 (older drafts are flagged as stragglers), has a
   validating example under ``examples/mcp/`` (checked with the repo's
   self-contained validator), and is referenced from at least one test and
   one doc.
4. ``docs_map``       -- every relative cross-reference in ``docs/mcp-*.md``
   resolves; every module in ``unlimited_skills/mcp/`` is mentioned by some
   doc; the boundary phrases required by ``scripts/verify-mcp-boundaries.py``
   are present (its own ``verify_static_docs`` is invoked programmatically).
5. ``audit_fields``   -- the field names the redacted audit writer and its
   call sites produce (``ts``/``tool``/``upstream``/``duration_ms``/``ok``,
   profile and bundle provenance, cache events) against what the inspector
   (E11) and replay (E17) read and what the docs describe; documented
   ``*_sha256`` fields must be exempted by the inspector's redaction
   self-check; gateway event rows must be known to the inspector.
6. ``security_boundaries`` -- the no-go invariants (no OAuth, no remote
   upstreams, no MCP resources/prompts, no hosted gateway, no telemetry) and
   fail-closed language in every bundle-layer doc; no module under
   ``unlimited_skills/mcp/`` imports a network library.

Findings carry severities ``info`` / ``warning`` / ``problem``. Exit 0 when
no problems (warnings allowed), 1 otherwise, 2 for usage errors. ``--json``
emits one machine document validating against
``schemas/mcp-stabilization-audit-report.schema.json``; ``--out DIR`` also
writes the JSON and text reports there. The audit is READ-ONLY over the
repository: it never writes outside an explicit ``--out`` directory, never
touches the user's library root, trust store, bundle library, or audit log,
and is offline by construction -- no network, no telemetry, no subprocess,
no hosted calls. ``--fixture-mode`` additionally pins determinism by
ignoring profile-affecting environment variables (the audit reads none
anyway). Report strings are repo-relative names only -- never absolute
local paths, key material, or hashes.
"""

from __future__ import annotations

import argparse
import ast
import importlib.util
import json
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

REPORT_TYPE = "mcp-stabilization-audit-report"
REPORT_SCHEMA_VERSION = 1

SEVERITY_INFO = "info"
SEVERITY_WARNING = "warning"
SEVERITY_PROBLEM = "problem"
_SEVERITY_RANK = {SEVERITY_PROBLEM: 0, SEVERITY_WARNING: 1, SEVERITY_INFO: 2}

DIMENSIONS = (
    "refusal_codes",
    "cli_taxonomy",
    "schemas",
    "docs_map",
    "audit_fields",
    "security_boundaries",
)

# The reserved gateway refusal-code range claimed by the stack docs:
# -32001..-32010 (E07/E08), -32011..-32014 (E09/E10), -32015..-32019 (E13/E14).
RESERVED_CODES = tuple(range(-32019, -32000))
CODE_PATTERN = re.compile(r"-320\d\d")

DRAFT_2020_12 = "https://json-schema.org/draft/2020-12/schema"

# Example files whose names do not follow the `<schema-stem>.example.json`
# convention but ARE the validated example of a schema.
EXAMPLE_ALIASES = {
    "mcp-upstream-config.schema.json": ("upstreams.example.json",),
}

# Long-running stdio servers: machine-readable output makes no sense there.
JSON_EXEMPT_COMMANDS = {("mcp", "serve"), ("mcp", "gateway")}

# Docs that document a signed-bundle layer MUST keep fail-closed language.
FAIL_CLOSED_DOCS = (
    "mcp-signed-profile-bundles.md",
    "mcp-trust-store.md",
    "mcp-bundle-library.md",
    "mcp-bundle-publishing.md",
    "mcp-incident-runbook.md",
    "mcp-operator-acceptance.md",
    "mcp-profile-rollout.md",
    "mcp-audit-replay.md",
)

# At least one of these no-go / locality phrases is expected in every MCP
# stack doc (the canonical phrase sets live in verify-mcp-boundaries.py).
NO_GO_PHRASES = (
    "telemetry",
    "offline",
    "no network",
    "local-only",
    "local only",
    "never spawns",
    "stdio",
)

FORBIDDEN_NET_IMPORTS = frozenset(
    {
        "socket",
        "ssl",
        "http",
        "urllib",
        "urllib3",
        "requests",
        "httpx",
        "aiohttp",
        "websockets",
        "ftplib",
        "smtplib",
        "telnetlib",
        "xmlrpc",
        "webbrowser",
    }
)

MCP_DOC_GLOB = "mcp-*.md"


def _finding(severity: str, check: str, subject: str, message: str) -> dict:
    return {
        "severity": severity,
        "check": check,
        "subject": subject,
        "message": message,
    }


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def _mcp_docs(root: Path) -> dict[str, str]:
    docs: dict[str, str] = {}
    docs_dir = root / "docs"
    if docs_dir.is_dir():
        for path in sorted(docs_dir.glob(MCP_DOC_GLOB)):
            docs[path.name] = _read(path)
        extra = docs_dir / "unlimited-tools.md"
        if extra.is_file():
            docs[extra.name] = _read(extra)
    return docs


def _all_docs(root: Path) -> dict[str, str]:
    docs_dir = root / "docs"
    if not docs_dir.is_dir():
        return {}
    return {path.name: _read(path) for path in sorted(docs_dir.glob("*.md"))}


def _balanced_block(text: str, open_index: int) -> str:
    """The ``{...}`` block starting at ``open_index`` (inclusive braces)."""
    depth = 0
    for index in range(open_index, len(text)):
        char = text[index]
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return text[open_index : index + 1]
    return text[open_index:]


# ---------------------------------------------------------------------------
# Dimension 1: refusal-code registry.

_CONSTANT_RE = re.compile(r"^([A-Z][A-Z0-9_]*)\s*=\s*(-320\d\d)\b", re.MULTILINE)
_NAME_TOKEN_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]*$")


def _parse_constants(text: str) -> dict[str, int]:
    return {name: int(code) for name, code in _CONSTANT_RE.findall(text)}


def _parse_literal_assign(tree: ast.AST, name: str) -> object:
    for node in ast.walk(tree):
        target = None
        value = None
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            target, value = node.targets[0], node.value
        elif isinstance(node, ast.AnnAssign) and node.value is not None:
            target, value = node.target, node.value
        if not (isinstance(target, ast.Name) and target.id == name):
            continue
        if (
            isinstance(value, ast.Call)
            and isinstance(value.func, ast.Name)
            and value.func.id in ("frozenset", "set", "tuple", "dict")
            and len(value.args) == 1
        ):
            value = value.args[0]
        try:
            return ast.literal_eval(value)
        except (ValueError, TypeError, SyntaxError):
            return None
    return None


def _parse_named_table(text: str, varname: str) -> dict[str, str]:
    """``CONSTANT: "name"`` entries of a module-level dict literal."""
    match = re.search(
        rf"^{varname}\s*(?::[^=\n]+)?=\s*\{{", text, re.MULTILINE
    )
    if not match:
        return {}
    block = _balanced_block(text, match.end() - 1)
    return dict(re.findall(r"([A-Z][A-Z0-9_]*)\s*:\s*\"([a-z0-9_]+)\"", block))


def _doc_code_claims(text: str) -> list[tuple[int, str]]:
    """``(code, claimed_name)`` pairs from markdown table rows.

    A cell adjacent to a reserved-code cell is treated as a NAMING claim only
    when its first token is a snake_case identifier containing ``_`` (every
    refusal name does); prose cells are ignored.
    """
    claims: list[tuple[int, str]] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped.startswith("|"):
            continue
        cells = [cell.strip() for cell in stripped.strip("|").split("|")]
        for index, cell in enumerate(cells[:-1]):
            bare = cell.strip("`").strip()
            if not re.fullmatch(r"-320\d\d", bare):
                continue
            neighbor = cells[index + 1].strip()
            token = neighbor.split()[0].strip("`").strip() if neighbor else ""
            if _NAME_TOKEN_RE.fullmatch(token) and "_" in token:
                claims.append((int(bare), token))
    return claims


def audit_refusal_codes(root: Path) -> tuple[int, list[dict]]:
    findings: list[dict] = []
    checks = 0
    mcp_dir = root / "unlimited_skills" / "mcp"
    constant_sources = ("gateway.py", "profiles.py", "bundles.py")
    code_owner: dict[int, tuple[str, str]] = {}  # code -> (constant, module)
    for module in constant_sources:
        path = mcp_dir / module
        if not path.is_file():
            findings.append(
                _finding(
                    SEVERITY_PROBLEM,
                    "constants_present",
                    f"unlimited_skills/mcp/{module}",
                    "refusal-code constant module is missing",
                )
            )
            continue
        for constant, code in sorted(_parse_constants(_read(path)).items()):
            checks += 1
            if code in code_owner:
                prior_constant, prior_module = code_owner[code]
                findings.append(
                    _finding(
                        SEVERITY_PROBLEM,
                        "duplicate_code",
                        str(code),
                        f"reserved code defined twice: {prior_constant} in "
                        f"{prior_module} and {constant} in {module}",
                    )
                )
            else:
                code_owner[code] = (constant, module)
    canonical = {code: constant.lower() for code, (constant, _) in code_owner.items()}
    for code in RESERVED_CODES:
        checks += 1
        if code not in canonical:
            findings.append(
                _finding(
                    SEVERITY_PROBLEM,
                    "range_gap",
                    str(code),
                    "reserved code inside the claimed range has no constant in "
                    "gateway.py/profiles.py/bundles.py",
                )
            )
    # The E11 inspector's local code -> (NAME, meaning) registry.
    inspector_path = mcp_dir / "audit_inspector.py"
    inspector_table: dict[int, tuple[str, str]] = {}
    if inspector_path.is_file():
        parsed = _parse_literal_assign(
            ast.parse(_read(inspector_path)), "REFUSAL_CODES"
        )
        if isinstance(parsed, dict):
            inspector_table = {
                int(code): (str(entry[0]), str(entry[1]))
                for code, entry in parsed.items()
                if isinstance(entry, (tuple, list)) and len(entry) == 2
            }
    for code, name in sorted(canonical.items()):
        checks += 1
        if code not in inspector_table:
            findings.append(
                _finding(
                    SEVERITY_PROBLEM,
                    "inspector_coverage",
                    str(code),
                    f"audit_inspector.REFUSAL_CODES cannot name reserved code "
                    f"{code} ({name}); audit-report would report 'unknown'",
                )
            )
        elif inspector_table[code][0].lower() != name:
            findings.append(
                _finding(
                    SEVERITY_PROBLEM,
                    "inspector_name_drift",
                    str(code),
                    f"audit_inspector names {code} "
                    f"'{inspector_table[code][0].lower()}' but the constant is "
                    f"'{name}'",
                )
            )
    # Partial name tables (E16 rollout, E19 publisher) must agree where defined.
    constants_by_name: dict[str, int] = {
        constant: code for code, (constant, _) in code_owner.items()
    }
    for module, varname in (
        ("profile_rollout.py", "REFUSAL_NAMES"),
        ("bundle_publisher.py", "REFUSAL_NAMES"),
    ):
        path = mcp_dir / module
        if not path.is_file():
            continue
        for constant, claimed in sorted(_parse_named_table(_read(path), varname).items()):
            checks += 1
            code = constants_by_name.get(constant)
            if code is None:
                findings.append(
                    _finding(
                        SEVERITY_PROBLEM,
                        "table_unknown_constant",
                        f"{module}:{constant}",
                        f"{varname} keys an unknown refusal constant",
                    )
                )
            elif claimed != canonical.get(code):
                findings.append(
                    _finding(
                        SEVERITY_PROBLEM,
                        "table_name_drift",
                        f"{module}:{constant}",
                        f"{varname} names {code} '{claimed}' but the constant "
                        f"is '{canonical.get(code)}'",
                    )
                )
    # Docs: naming claims must match; references must exist in code; every
    # reserved code must be documented somewhere in the stack docs.
    docs = _mcp_docs(root)
    referenced: set[int] = set()
    for doc_name, text in sorted(docs.items()):
        for raw in CODE_PATTERN.findall(text):
            referenced.add(int(raw))
        for code, claimed in _doc_code_claims(text):
            checks += 1
            if code not in canonical:
                findings.append(
                    _finding(
                        SEVERITY_PROBLEM,
                        "docs_unknown_code",
                        f"docs/{doc_name}",
                        f"documents code {code} ('{claimed}') that has no "
                        "constant in the stack modules",
                    )
                )
            elif claimed.lower() != canonical[code]:
                findings.append(
                    _finding(
                        SEVERITY_PROBLEM,
                        "docs_name_drift",
                        f"docs/{doc_name}",
                        f"names {code} '{claimed}' but the constant is "
                        f"'{canonical[code]}'",
                    )
                )
    for code in sorted(referenced):
        checks += 1
        if code not in canonical:
            findings.append(
                _finding(
                    SEVERITY_PROBLEM,
                    "docs_unknown_code",
                    str(code),
                    "reserved-range code referenced by the stack docs has no "
                    "constant in the stack modules",
                )
            )
    for code, name in sorted(canonical.items()):
        checks += 1
        if code not in referenced:
            findings.append(
                _finding(
                    SEVERITY_PROBLEM,
                    "docs_missing_code",
                    str(code),
                    f"reserved code {code} ({name}) is never referenced by "
                    "the stack docs",
                )
            )
    return checks, findings


# ---------------------------------------------------------------------------
# Dimension 2: CLI taxonomy.


def _subparsers_action(parser: argparse.ArgumentParser):
    for action in parser._actions:  # noqa: SLF001 - argparse has no public walk
        if isinstance(action, argparse._SubParsersAction):  # noqa: SLF001
            return action
    return None


def _walk_commands(path: tuple[str, ...], parser: argparse.ArgumentParser):
    sub = _subparsers_action(parser)
    if sub is None:
        flags = sorted(
            {
                option
                for action in parser._actions  # noqa: SLF001
                for option in action.option_strings
                if option.startswith("--")
            }
        )
        yield path, flags
        return
    seen: set[int] = set()
    for name in sorted(sub.choices):
        child = sub.choices[name]
        if id(child) in seen:
            continue  # alias of an already-walked parser
        seen.add(id(child))
        yield from _walk_commands(path + (name,), child)


def mcp_command_tree() -> list[tuple[tuple[str, ...], list[str]]]:
    from unlimited_skills.cli import build_parser

    parser = build_parser()
    sub = _subparsers_action(parser)
    if sub is None or "mcp" not in sub.choices:
        return []
    return list(_walk_commands(("mcp",), sub.choices["mcp"]))


def audit_cli_taxonomy(root: Path) -> tuple[int, list[dict]]:
    findings: list[dict] = []
    checks = 0
    commands = mcp_command_tree()
    docs = _all_docs(root)
    changelog_path = root / "CHANGELOG.md"
    changelog = _read(changelog_path) if changelog_path.is_file() else ""
    all_flags: dict[str, list[str]] = {}
    for path, flags in commands:
        command = " ".join(path)
        parent = " ".join(path[:-1])
        leaf = path[-1]
        for flag in flags:
            all_flags.setdefault(flag, []).append(command)
        # Docs mention: a doc carrying the parent path and the leaf token
        # (covers the `a|b|c` pipe style the stack docs use).
        checks += 1
        leaf_re = re.compile(rf"\b{re.escape(leaf)}\b")
        documented = any(
            (parent in text or command in text) and leaf_re.search(text)
            for text in docs.values()
        )
        if not documented:
            findings.append(
                _finding(
                    SEVERITY_PROBLEM,
                    "docs_mention",
                    command,
                    "no doc under docs/ mentions this mcp subcommand",
                )
            )
        # CHANGELOG mention of the leaf token.
        checks += 1
        if not leaf_re.search(changelog):
            findings.append(
                _finding(
                    SEVERITY_WARNING,
                    "changelog_mention",
                    command,
                    "CHANGELOG.md never mentions this subcommand name",
                )
            )
        # --json everywhere it makes sense.
        checks += 1
        if path not in JSON_EXEMPT_COMMANDS and "--json" not in flags:
            findings.append(
                _finding(
                    SEVERITY_WARNING,
                    "json_flag",
                    command,
                    "subcommand offers no --json machine output "
                    "(reported, not auto-fixed)",
                )
            )
    # Flag vocabulary uniformity (reported, never fixed here).
    checks += 1
    if "--out-dir" in all_flags and "--out" in all_flags:
        findings.append(
            _finding(
                SEVERITY_WARNING,
                "out_flag_uniformity",
                "--out-dir",
                "both --out and --out-dir exist across mcp subcommands; the "
                "stack convention is --out DIR",
            )
        )
    checks += 1
    directory_flags = sorted(
        flag for flag in all_flags if flag.endswith("-dir") or flag.endswith("dir")
    )
    for flag in directory_flags:
        if not flag.endswith("-dir"):
            findings.append(
                _finding(
                    SEVERITY_WARNING,
                    "dir_flag_naming",
                    flag,
                    "directory flag does not follow the --<thing>-dir "
                    "convention (--store-dir / --library-dir)",
                )
            )
    findings.append(
        _finding(
            SEVERITY_INFO,
            "inventory",
            "mcp",
            f"{len(commands)} mcp subcommands, "
            f"{len(all_flags)} distinct long flags, directory flags: "
            f"{', '.join(directory_flags) if directory_flags else 'none'}",
        )
    )
    return checks, findings


# ---------------------------------------------------------------------------
# Dimension 3: schema inventory (self-contained validator, no jsonschema dep).

_TYPES = {
    "object": dict,
    "array": list,
    "string": str,
    "number": (int, float),
    "integer": int,
    "boolean": bool,
    "null": type(None),
}


def _type_ok(value: object, expected: str) -> bool:
    python_type = _TYPES.get(expected)
    if python_type is None:
        return True
    if expected in ("number", "integer") and isinstance(value, bool):
        return False
    return isinstance(value, python_type)


def validate_instance(
    value: object, schema: object, path: str = "$", root: dict | None = None
) -> list[str]:
    """Minimal self-contained JSON Schema check (the repo's test stance)."""
    if not isinstance(schema, dict):
        return []
    if root is None:
        root = schema
    if "$ref" in schema:
        target: object = root
        for part in str(schema["$ref"]).lstrip("#/").split("/"):
            if not isinstance(target, dict) or part not in target:
                return [f"{path}: unresolvable $ref {schema['$ref']!r}"]
            target = target[part]
        merged = {key: item for key, item in schema.items() if key != "$ref"}
        errors = validate_instance(value, target, path, root)
        if merged:
            errors.extend(validate_instance(value, merged, path, root))
        return errors
    errors: list[str] = []
    if "const" in schema and value != schema["const"]:
        errors.append(f"{path}: must be const {schema['const']!r}")
    if "enum" in schema and value not in schema["enum"]:
        errors.append(f"{path}: {value!r} not in enum")
    expected_type = schema.get("type")
    if isinstance(expected_type, str):
        if not _type_ok(value, expected_type):
            return errors + [
                f"{path}: expected {expected_type}, got {type(value).__name__}"
            ]
    elif isinstance(expected_type, list):
        if not any(_type_ok(value, option) for option in expected_type):
            return errors + [f"{path}: type not in {expected_type!r}"]
    for keyword, mode in (("allOf", "all"), ("anyOf", "any"), ("oneOf", "any")):
        branches = schema.get(keyword)
        if isinstance(branches, list) and branches:
            results = [
                validate_instance(value, branch, path, root) for branch in branches
            ]
            if mode == "all":
                for result in results:
                    errors.extend(result)
            elif all(result for result in results):
                errors.append(f"{path}: no {keyword} branch matched")
    if isinstance(value, dict):
        for key in schema.get("required", []):
            if key not in value:
                errors.append(f"{path}: missing required property {key!r}")
        if "minProperties" in schema and len(value) < schema["minProperties"]:
            errors.append(f"{path}: fewer than {schema['minProperties']} properties")
        if "maxProperties" in schema and len(value) > schema["maxProperties"]:
            errors.append(f"{path}: more than {schema['maxProperties']} properties")
        properties = schema.get("properties", {})
        pattern_properties = schema.get("patternProperties", {})
        additional = schema.get("additionalProperties", True)
        for key, item in value.items():
            matched = False
            if key in properties:
                matched = True
                errors.extend(
                    validate_instance(item, properties[key], f"{path}.{key}", root)
                )
            for pattern, subschema in pattern_properties.items():
                if re.search(pattern, key):
                    matched = True
                    errors.extend(
                        validate_instance(item, subschema, f"{path}.{key}", root)
                    )
            if not matched:
                if additional is False:
                    errors.append(f"{path}: additional property {key!r} not allowed")
                elif isinstance(additional, dict):
                    errors.extend(
                        validate_instance(item, additional, f"{path}.{key}", root)
                    )
    if isinstance(value, list):
        if "minItems" in schema and len(value) < schema["minItems"]:
            errors.append(f"{path}: fewer than {schema['minItems']} items")
        if "maxItems" in schema and len(value) > schema["maxItems"]:
            errors.append(f"{path}: more than {schema['maxItems']} items")
        if isinstance(schema.get("items"), dict):
            for index, item in enumerate(value):
                errors.extend(
                    validate_instance(item, schema["items"], f"{path}[{index}]", root)
                )
    if isinstance(value, str):
        if "pattern" in schema and not re.search(schema["pattern"], value):
            errors.append(f"{path}: does not match pattern")
        if "minLength" in schema and len(value) < schema["minLength"]:
            errors.append(f"{path}: shorter than {schema['minLength']}")
        if "maxLength" in schema and len(value) > schema["maxLength"]:
            errors.append(f"{path}: longer than {schema['maxLength']}")
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if "minimum" in schema and value < schema["minimum"]:
            errors.append(f"{path}: below minimum {schema['minimum']}")
        if "maximum" in schema and value > schema["maximum"]:
            errors.append(f"{path}: above maximum {schema['maximum']}")
        if "exclusiveMinimum" in schema and value <= schema["exclusiveMinimum"]:
            errors.append(f"{path}: not above {schema['exclusiveMinimum']}")
        if "exclusiveMaximum" in schema and value >= schema["exclusiveMaximum"]:
            errors.append(f"{path}: not below {schema['exclusiveMaximum']}")
    return errors


def audit_schemas(root: Path) -> tuple[int, list[dict]]:
    findings: list[dict] = []
    checks = 0
    schemas_dir = root / "schemas"
    examples_dir = root / "examples" / "mcp"
    tests_dir = root / "tests"
    docs = _all_docs(root)
    docs_blob = "\n".join(docs.values())
    test_blob = ""
    if tests_dir.is_dir():
        test_blob = "\n".join(
            _read(path) for path in sorted(tests_dir.rglob("*.py"))
        )
    example_names = (
        {path.name for path in examples_dir.glob("*.example.json")}
        if examples_dir.is_dir()
        else set()
    )
    mapped_examples: set[str] = set()
    for schema_path in sorted(schemas_dir.glob("mcp-*.schema.json")):
        rel = f"schemas/{schema_path.name}"
        checks += 1
        try:
            schema = json.loads(_read(schema_path))
        except json.JSONDecodeError as exc:
            findings.append(
                _finding(
                    SEVERITY_PROBLEM,
                    "schema_valid_json",
                    rel,
                    f"schema file is not valid JSON (line {exc.lineno})",
                )
            )
            continue
        checks += 1
        declared = str(schema.get("$schema", ""))
        if declared != DRAFT_2020_12:
            # The declared URI is summarized, never embedded verbatim: raw
            # `x://` URIs trip the audit writer's drive-letter path heuristic
            # the leak-grep tests reuse.
            label = declared.rstrip("#").rsplit("/", 2)[-2] if "/" in declared else "none"
            findings.append(
                _finding(
                    SEVERITY_WARNING,
                    "schema_draft",
                    rel,
                    f"declares JSON Schema {label or 'none'} instead of "
                    "draft 2020-12 (straggler)",
                )
            )
        stem = schema_path.name[: -len(".schema.json")]
        candidates = [f"{stem[len('mcp-'):]}.example.json"]
        candidates.extend(EXAMPLE_ALIASES.get(schema_path.name, ()))
        present = [name for name in candidates if name in example_names]
        mapped_examples.update(present)
        checks += 1
        if not present:
            findings.append(
                _finding(
                    SEVERITY_WARNING,
                    "schema_example",
                    rel,
                    "no example under examples/mcp/ maps to this schema",
                )
            )
        for example_name in present:
            checks += 1
            example_rel = f"examples/mcp/{example_name}"
            try:
                instance = json.loads(_read(examples_dir / example_name))
            except json.JSONDecodeError as exc:
                findings.append(
                    _finding(
                        SEVERITY_PROBLEM,
                        "example_valid_json",
                        example_rel,
                        f"example file is not valid JSON (line {exc.lineno})",
                    )
                )
                continue
            errors = validate_instance(instance, schema)
            if errors:
                findings.append(
                    _finding(
                        SEVERITY_PROBLEM,
                        "example_validates",
                        example_rel,
                        f"example fails its schema: {errors[0]}"
                        + (f" (+{len(errors) - 1} more)" if len(errors) > 1 else ""),
                    )
                )
        checks += 1
        if schema_path.name not in test_blob:
            findings.append(
                _finding(
                    SEVERITY_WARNING,
                    "schema_test_reference",
                    rel,
                    "no test under tests/ references this schema by name",
                )
            )
        checks += 1
        if schema_path.name not in docs_blob:
            findings.append(
                _finding(
                    SEVERITY_WARNING,
                    "schema_doc_reference",
                    rel,
                    "no doc under docs/ references this schema by name",
                )
            )
    for example_name in sorted(example_names - mapped_examples):
        findings.append(
            _finding(
                SEVERITY_INFO,
                "unmapped_example",
                f"examples/mcp/{example_name}",
                "example does not map to an mcp-*.schema.json by name "
                "(request fixtures and legacy examples)",
            )
        )
    return checks, findings


# ---------------------------------------------------------------------------
# Dimension 4: docs map.

_LINK_RE = re.compile(r"\[[^\]]*\]\(([^)\s]+)\)")


def _load_boundary_verifier():
    path = Path(__file__).resolve().parent / "verify-mcp-boundaries.py"
    scripts_dir = str(path.parent)
    if scripts_dir not in sys.path:
        sys.path.insert(0, scripts_dir)
    spec = importlib.util.spec_from_file_location("verify_mcp_boundaries", path)
    if spec is None or spec.loader is None:
        return None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def audit_docs_map(root: Path) -> tuple[int, list[dict]]:
    findings: list[dict] = []
    checks = 0
    docs_dir = root / "docs"
    docs = _mcp_docs(root)
    for doc_name, text in sorted(docs.items()):
        for target in _LINK_RE.findall(text):
            if target.startswith(("http://", "https://", "mailto:", "#")):
                continue
            checks += 1
            relative = target.split("#", 1)[0]
            if not relative:
                continue
            resolved = (docs_dir / relative).resolve()
            if not resolved.exists():
                findings.append(
                    _finding(
                        SEVERITY_PROBLEM,
                        "cross_reference",
                        f"docs/{doc_name}",
                        f"relative link '{relative}' does not resolve",
                    )
                )
    docs_blob = "\n".join(_all_docs(root).values())
    mcp_pkg = root / "unlimited_skills" / "mcp"
    if mcp_pkg.is_dir():
        for module_path in sorted(mcp_pkg.glob("*.py")):
            if module_path.name == "__init__.py":
                continue
            checks += 1
            if module_path.name not in docs_blob:
                findings.append(
                    _finding(
                        SEVERITY_WARNING,
                        "module_doc_mention",
                        f"unlimited_skills/mcp/{module_path.name}",
                        "no doc under docs/ mentions this MCP module by name",
                    )
                )
    verifier = _load_boundary_verifier()
    checks += 1
    if verifier is None:
        findings.append(
            _finding(
                SEVERITY_PROBLEM,
                "boundary_phrases",
                "scripts/verify-mcp-boundaries.py",
                "boundary verifier could not be loaded",
            )
        )
    else:
        for failure in verifier.verify_static_docs(root):
            findings.append(
                _finding(
                    SEVERITY_PROBLEM,
                    "boundary_phrases",
                    "scripts/verify-mcp-boundaries.py",
                    f"verify_static_docs: {failure}",
                )
            )
    return checks, findings


# ---------------------------------------------------------------------------
# Dimension 5: audit field names.

_ROW_GET_RE = re.compile(r"row\.get\(\s*\"([a-z][a-z0-9_]*)\"")
_FIELD_KEY_RE = re.compile(r"\"([a-z][a-z0-9_]*)\"\s*:")


def _collect_writer_fields(root: Path) -> tuple[set[str], set[str], set[str]]:
    """``(base_fields, extra_fields, event_tools)`` from the writer side."""
    mcp_dir = root / "unlimited_skills" / "mcp"
    audit_text = _read(mcp_dir / "audit.py") if (mcp_dir / "audit.py").is_file() else ""
    gateway_text = (
        _read(mcp_dir / "gateway.py") if (mcp_dir / "gateway.py").is_file() else ""
    )
    bundles_text = (
        _read(mcp_dir / "bundles.py") if (mcp_dir / "bundles.py").is_file() else ""
    )
    base: set[str] = set()
    match = re.search(r"row:\s*dict\[str,\s*Any\]\s*=\s*\{", audit_text)
    if match:
        base |= set(_FIELD_KEY_RE.findall(_balanced_block(audit_text, match.end() - 1)))
    base |= set(re.findall(r"row\[\s*\"([a-z][a-z0-9_]*)\"\s*\]", audit_text))
    extra: set[str] = set()
    for match in re.finditer(
        r"extra(?::\s*dict\[[^\]]+\])?\s*=\s*\{", gateway_text
    ):
        extra |= set(
            _FIELD_KEY_RE.findall(_balanced_block(gateway_text, match.end() - 1))
        )
    extra |= set(re.findall(r"extra\[\s*\"([a-z][a-z0-9_]*)\"\s*\]", gateway_text))
    fields_match = re.search(
        r"def audit_fields\(self\).*?return fields", bundles_text, re.DOTALL
    )
    if fields_match:
        extra |= set(_FIELD_KEY_RE.findall(fields_match.group(0)))
        extra |= set(
            re.findall(r"fields\[\s*\"([a-z][a-z0-9_]*)\"\s*\]", fields_match.group(0))
        )
    event_tools = set(re.findall(r"tool=\"([a-z][a-z0-9_]*)\"", gateway_text))
    return base, extra, event_tools


def audit_audit_fields(root: Path) -> tuple[int, list[dict]]:
    findings: list[dict] = []
    checks = 0
    mcp_dir = root / "unlimited_skills" / "mcp"
    base, extra, event_tools = _collect_writer_fields(root)
    inspector_path = mcp_dir / "audit_inspector.py"
    replay_path = mcp_dir / "audit_replay.py"
    inspector_text = _read(inspector_path) if inspector_path.is_file() else ""
    replay_text = _read(replay_path) if replay_path.is_file() else ""
    inspector_reads = set(_ROW_GET_RE.findall(inspector_text))
    replay_reads = set(_ROW_GET_RE.findall(replay_text))
    docs_blob = "\n".join(_mcp_docs(root).values())
    required_base = ("ts", "tool", "upstream", "duration_ms", "ok")
    for field in required_base:
        checks += 1
        if field not in base:
            findings.append(
                _finding(
                    SEVERITY_PROBLEM,
                    "writer_base_fields",
                    field,
                    "base audit field is missing from the writer's row",
                )
            )
        checks += 1
        if field not in inspector_reads:
            findings.append(
                _finding(
                    SEVERITY_PROBLEM,
                    "inspector_reads_base",
                    field,
                    "base audit field is never read by the inspector",
                )
            )
    for field in ("tool", "ok"):
        checks += 1
        if field not in replay_reads:
            findings.append(
                _finding(
                    SEVERITY_PROBLEM,
                    "replay_reads_base",
                    field,
                    "base audit field is never read by the replay simulator",
                )
            )
    writer_fields = sorted(base | extra)
    for field in writer_fields:
        checks += 1
        if not re.search(rf"\b{re.escape(field)}\b", docs_blob):
            findings.append(
                _finding(
                    SEVERITY_WARNING,
                    "field_documented",
                    field,
                    "audit field written by the gateway is not named by any "
                    "stack doc",
                )
            )
    # Documented hash-valued fields must be exempt in the inspector's
    # redaction self-check, or audit-report flags its own documented fields.
    known_hashes = _parse_literal_assign(
        ast.parse(inspector_text) if inspector_text else ast.parse(""),
        "KNOWN_HASH_KEYS",
    )
    known_hashes = set(known_hashes) if isinstance(known_hashes, (set, frozenset, list, tuple)) else set()
    for field in sorted(field for field in writer_fields if field.endswith("_sha256")):
        checks += 1
        if field not in known_hashes:
            findings.append(
                _finding(
                    SEVERITY_PROBLEM,
                    "hash_field_exempt",
                    field,
                    "documented SHA-256 audit field is not in the inspector's "
                    "KNOWN_HASH_KEYS; the redaction self-check would flag it",
                )
            )
    # Gateway event rows must be known to the inspector (excluded from the
    # meta-tool call summary) and documented.
    for event in sorted(event_tools):
        checks += 1
        if f'"{event}"' not in inspector_text:
            findings.append(
                _finding(
                    SEVERITY_PROBLEM,
                    "event_known_to_inspector",
                    event,
                    "gateway audit event row is unknown to the inspector and "
                    "would be counted as a meta-tool call",
                )
            )
        checks += 1
        if not re.search(rf"\b{re.escape(event)}\b", docs_blob):
            findings.append(
                _finding(
                    SEVERITY_WARNING,
                    "event_documented",
                    event,
                    "gateway audit event is not named by any stack doc",
                )
            )
    for field in sorted((inspector_reads | replay_reads) - set(writer_fields)):
        findings.append(
            _finding(
                SEVERITY_INFO,
                "reader_only_field",
                field,
                "read by the inspector/replay but never written by the "
                "gateway writer (forward-compatible accessor)",
            )
        )
    return checks, findings


# ---------------------------------------------------------------------------
# Dimension 6: security boundary consistency.


def _imported_roots(tree: ast.AST) -> set[str]:
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                roots.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            roots.add(node.module.split(".")[0])
    return roots


def audit_security_boundaries(root: Path) -> tuple[int, list[dict]]:
    findings: list[dict] = []
    checks = 0
    docs = _mcp_docs(root)
    for doc_name in FAIL_CLOSED_DOCS:
        checks += 1
        text = docs.get(doc_name, "").lower()
        if not text:
            findings.append(
                _finding(
                    SEVERITY_PROBLEM,
                    "fail_closed_language",
                    f"docs/{doc_name}",
                    "bundle-layer doc is missing",
                )
            )
        elif "fail-closed" not in text and "fails closed" not in text:
            findings.append(
                _finding(
                    SEVERITY_PROBLEM,
                    "fail_closed_language",
                    f"docs/{doc_name}",
                    "bundle-layer doc carries no fail-closed language",
                )
            )
    for doc_name, text in sorted(docs.items()):
        checks += 1
        lowered = text.lower()
        if not any(phrase in lowered for phrase in NO_GO_PHRASES):
            findings.append(
                _finding(
                    SEVERITY_WARNING,
                    "no_go_language",
                    f"docs/{doc_name}",
                    "stack doc carries none of the no-go/locality phrases "
                    "(telemetry/offline/no network/local-only/stdio)",
                )
            )
    mcp_pkg = root / "unlimited_skills" / "mcp"
    if mcp_pkg.is_dir():
        for module_path in sorted(mcp_pkg.glob("*.py")):
            checks += 1
            try:
                tree = ast.parse(_read(module_path))
            except SyntaxError:
                findings.append(
                    _finding(
                        SEVERITY_PROBLEM,
                        "network_imports",
                        f"unlimited_skills/mcp/{module_path.name}",
                        "module does not parse",
                    )
                )
                continue
            offending = sorted(_imported_roots(tree) & FORBIDDEN_NET_IMPORTS)
            if offending:
                findings.append(
                    _finding(
                        SEVERITY_PROBLEM,
                        "network_imports",
                        f"unlimited_skills/mcp/{module_path.name}",
                        f"imports network-capable modules: {', '.join(offending)}",
                    )
                )
    return checks, findings


# ---------------------------------------------------------------------------
# Orchestration.

_DIMENSION_FUNCS = {
    "refusal_codes": audit_refusal_codes,
    "cli_taxonomy": audit_cli_taxonomy,
    "schemas": audit_schemas,
    "docs_map": audit_docs_map,
    "audit_fields": audit_audit_fields,
    "security_boundaries": audit_security_boundaries,
}


def _sorted_findings(findings: list[dict]) -> list[dict]:
    return sorted(
        findings,
        key=lambda item: (
            _SEVERITY_RANK[item["severity"]],
            item["check"],
            item["subject"],
            item["message"],
        ),
    )


def run_audit(repo_root: Path | None = None, fixture_mode: bool = False) -> dict:
    root = Path(repo_root) if repo_root is not None else ROOT
    dimensions = []
    totals = {SEVERITY_INFO: 0, SEVERITY_WARNING: 0, SEVERITY_PROBLEM: 0}
    checks_total = 0
    findings_total = 0
    for name in DIMENSIONS:
        checks, findings = _DIMENSION_FUNCS[name](root)
        findings = _sorted_findings(findings)
        counts = {SEVERITY_INFO: 0, SEVERITY_WARNING: 0, SEVERITY_PROBLEM: 0}
        for finding in findings:
            counts[finding["severity"]] += 1
            totals[finding["severity"]] += 1
        checks_total += checks
        findings_total += len(findings)
        dimensions.append(
            {
                "name": name,
                "checks": checks,
                "counts": counts,
                "findings": findings,
            }
        )
    ok = totals[SEVERITY_PROBLEM] == 0
    return {
        "report_type": REPORT_TYPE,
        "schema_version": REPORT_SCHEMA_VERSION,
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "mode": "fixture" if fixture_mode else "repo",
        "dimensions": dimensions,
        "summary": {
            "dimensions": len(dimensions),
            "checks_total": checks_total,
            "findings_total": findings_total,
            "info": totals[SEVERITY_INFO],
            "warning": totals[SEVERITY_WARNING],
            "problem": totals[SEVERITY_PROBLEM],
            "ok": ok,
        },
        "exit_code": 0 if ok else 1,
    }


def render_text(report: dict) -> str:
    lines = [
        "MCP profile stack stabilization audit",
        f"mode: {report['mode']}  generated_at: {report['generated_at']}",
        "",
    ]
    for dimension in report["dimensions"]:
        counts = dimension["counts"]
        lines.append(
            f"[{dimension['name']}] checks: {dimension['checks']}  "
            f"problems: {counts['problem']}  warnings: {counts['warning']}  "
            f"info: {counts['info']}"
        )
        for finding in dimension["findings"]:
            lines.append(
                f"  {finding['severity'].upper():7s} {finding['check']} "
                f"{finding['subject']}: {finding['message']}"
            )
        lines.append("")
    summary = report["summary"]
    verdict = "OK (no problems)" if summary["ok"] else "PROBLEMS FOUND"
    lines.append(
        f"summary: {verdict} -- {summary['checks_total']} checks, "
        f"{summary['problem']} problems, {summary['warning']} warnings, "
        f"{summary['info']} info"
    )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Read-only consistency audit of the MCP profile stack: refusal "
            "codes, CLI taxonomy, schemas, docs map, audit field names, "
            "security boundaries."
        )
    )
    parser.add_argument(
        "--fixture-mode",
        action="store_true",
        help=(
            "Pin determinism for CI/fixtures. The audit is read-only either "
            "way: nothing outside an explicit --out directory is written and "
            "user directories are never touched."
        ),
    )
    parser.add_argument(
        "--json", action="store_true", help="Print the machine JSON report."
    )
    parser.add_argument(
        "--out",
        default="",
        metavar="DIR",
        help="Also write stabilization-audit-report.json/.txt into DIR.",
    )
    args = parser.parse_args(argv)
    report = run_audit(fixture_mode=args.fixture_mode)
    if args.out:
        out_dir = Path(args.out).expanduser()
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "stabilization-audit-report.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        (out_dir / "stabilization-audit-report.txt").write_text(
            render_text(report) + "\n", encoding="utf-8"
        )
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print(render_text(report))
    return report["exit_code"]


if __name__ == "__main__":
    raise SystemExit(main())
