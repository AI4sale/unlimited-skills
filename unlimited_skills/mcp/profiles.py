"""Permissioned tool profiles for the Unlimited Tools gateway (E09 design, E10 enforcement).

Implements docs/mcp-permissioned-tool-profiles.md: named, local, default-deny
profiles controlling which upstream tools an agent can SEE (``visible``:
filters ``tools_search``, gates ``tools_schema``) and which it can CALL
(``callable``: gates ``tools_call``). Callable is always a subset of visible.

Loading semantics (all decided here, once, at gateway startup -- there is no
hot reload):

- the profile file is validated against the shape of
  ``schemas/mcp-tool-profile.schema.json`` plus the design's static load
  checks (``extends`` exists / no self-reference / no cycle / depth <= 8,
  callable coverage, ``default_profile`` exists). Any violation is a
  :class:`ProfileLoadError` -> fail-closed ``profile_invalid`` (-32014);
- profile selection precedence: ``--profile`` CLI flag >
  ``UNLIMITED_SKILLS_MCP_PROFILE`` env var > ``default_profile`` in the file.
  Nothing resolved, or a selected name that does not exist, is fail-closed
  ``profile_not_found`` (-32013) -- never a fallback to open behavior;
- inheritance is restriction-only intersection: a child's effective sets are
  the conjunction of every declared rule list along its ``extends`` chain.
  An omitted field inherits the parent's set unchanged; a root profile with
  an omitted field denies everything (default deny has no implicit allow).

Rule evaluation matches fully qualified tool names ONLY -- the evaluator's
interface never receives call arguments, so it can never log or leak a
payload by construction (design "Redaction").
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Union

PROFILE_ENV_VAR = "UNLIMITED_SKILLS_MCP_PROFILE"

# Profile refusal codes, contiguous with the gateway's -32001..-32010 family
# (re-exported by unlimited_skills.mcp.gateway next to that family). Reserved
# by the E09 design; never reused for anything else.
TOOL_NOT_VISIBLE = -32011  # tool not in the visible set -- or nonexistent; never distinguished
TOOL_NOT_CALLABLE = -32012  # tool visible but not callable (view-only)
PROFILE_NOT_FOUND = -32013  # profile file configured but no profile resolved
PROFILE_INVALID = -32014  # profile file fails schema validation or a static load check

MAX_EXTENDS_DEPTH = 8
MAX_PROFILES = 64
MAX_RULES = 256
MAX_KEY_ID_LENGTH = 128
MAX_SIGNATURE_LENGTH = 1024

PROFILE_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]*$")
# The rule grammar IS this pattern (schemas/mcp-tool-profile.schema.json) --
# exactly two forms: exact '<upstream>.<tool>' or whole-upstream '<upstream>.*'.
RULE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]*\.(\*|[A-Za-z0-9_][A-Za-z0-9_.-]*)$")
KEY_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]*$")
SIGNATURE_VALUE_RE = re.compile(r"^[A-Za-z0-9+/]+={0,2}$")

_TOP_LEVEL_KEYS = frozenset({"schema_version", "comment", "default_profile", "signature", "profiles"})
_PROFILE_KEYS = frozenset({"comment", "extends", "visible", "callable"})
_SIGNATURE_KEYS = frozenset({"comment", "algorithm", "key_id", "value"})


class ProfileLoadError(ValueError):
    """The profile file is missing, malformed, or fails a static load check.

    Maps to the fail-closed ``profile_invalid`` (-32014) refuse-all state.
    """


@dataclass(frozen=True)
class RuleSet:
    """One declared rule list, compiled for constant-time-per-rule matching.

    ``globs`` holds upstream names granted whole (``<upstream>.*``); ``exact``
    holds full ``<upstream>.<tool>`` strings compared literally (MCP tool
    names may contain dots; the split happens at the FIRST dot only, exactly
    like ``tools_call`` addressing).
    """

    globs: frozenset[str]
    exact: frozenset[str]

    def matches(self, upstream: str, tool: str) -> bool:
        return upstream in self.globs or f"{upstream}.{tool}" in self.exact

    def names_upstream(self, upstream: str) -> bool:
        prefix = f"{upstream}."
        return upstream in self.globs or any(rule.startswith(prefix) for rule in self.exact)


def _compile_rules(rules: list[str]) -> RuleSet:
    globs: set[str] = set()
    exact: set[str] = set()
    for rule in rules:
        upstream, _, tool = rule.partition(".")
        if tool == "*":
            globs.add(upstream)
        else:
            exact.add(rule)
    return RuleSet(globs=frozenset(globs), exact=frozenset(exact))


@dataclass(frozen=True)
class ActiveProfile:
    """A resolved profile: the gateway enforces these sets for its lifetime.

    ``visible_chain`` / ``callable_chain`` are every DECLARED rule list along
    the ``extends`` chain (leaf to root). Evaluation is the intersection of
    all declared lists; an empty chain (no profile in the chain declared the
    field) denies everything. Matching never receives call arguments.
    """

    name: str
    visible_chain: tuple[RuleSet, ...]
    callable_chain: tuple[RuleSet, ...]
    file_sha256: str
    visible_rule_count: int
    callable_rule_count: int
    # Set only by unlimited_skills.mcp.bundles for verified signed bundles
    # (a BundleProvenance: hashes, key ids, audience -- non-sensitive by
    # grammar). None marks the raw local profile file path, unchanged.
    provenance: object | None = None

    def is_visible(self, upstream: str, tool: str) -> bool:
        if not self.visible_chain:
            return False
        return all(rules.matches(upstream, tool) for rules in self.visible_chain)

    def is_callable(self, upstream: str, tool: str) -> bool:
        # Structural subset guarantee (defense in depth on top of the static
        # callable-coverage load check): callable requires visible.
        if not self.callable_chain or not self.is_visible(upstream, tool):
            return False
        return all(rules.matches(upstream, tool) for rules in self.callable_chain)

    def upstream_has_visible_tools(self, upstream: str) -> bool:
        """True when at least one tool of ``upstream`` could be visible.

        Used so refreshing the index never spawns an upstream that cannot
        contribute a visible tool, and so the unknown-upstream hint never
        enumerates upstreams with nothing visible under the active profile.
        """
        if not self.visible_chain:
            return False
        allowed: set[str] | None = None  # None = unrestricted so far (globs only)
        prefix = f"{upstream}."
        for rules in self.visible_chain:
            if upstream in rules.globs:
                continue
            names = {rule[len(prefix):] for rule in rules.exact if rule.startswith(prefix)}
            allowed = names if allowed is None else allowed & names
            if not allowed:
                return False
        return True


@dataclass(frozen=True)
class FailClosedProfile:
    """Fail-closed refuse-all: the gateway serves the meta-tools but refuses
    every call with ``code`` (-32013 profile_not_found / -32014
    profile_invalid). ``requested`` is the requested profile name ('' when
    none was selected) and is stamped on every audit row.
    """

    code: int
    message: str
    requested: str = ""


ProfileState = Union[ActiveProfile, FailClosedProfile, None]


def _shape_errors(document: object) -> list[str]:
    """Structural validation mirroring schemas/mcp-tool-profile.schema.json.

    Strict: unknown keys are load errors (a typo like 'visble' fails instead
    of silently denying). The repo deliberately has no jsonschema dependency.
    """
    if not isinstance(document, dict):
        return ["document must be a JSON object"]
    errors: list[str] = []
    for key in document:
        if key not in _TOP_LEVEL_KEYS:
            errors.append(f"unknown key {key!r}")
    if document.get("schema_version") != 1:
        errors.append("schema_version must be the constant 1")
    if "comment" in document and not isinstance(document["comment"], str):
        errors.append("comment must be a string")
    default = document.get("default_profile")
    if default is not None and (not isinstance(default, str) or not PROFILE_NAME_RE.match(default)):
        errors.append("default_profile must be a profile name")
    if "signature" in document:
        errors.extend(_signature_errors(document["signature"]))
    errors.extend(_profiles_map_shape_errors(document.get("profiles")))
    return errors


def _profiles_map_shape_errors(profiles: object) -> list[str]:
    """Shape validation of one E09 profiles map (shared with the bundle
    loader in bundles.py, which embeds the same map verbatim)."""
    if not isinstance(profiles, dict):
        return ["profiles must be an object"]
    errors: list[str] = []
    if not 1 <= len(profiles) <= MAX_PROFILES:
        errors.append(f"profiles must contain between 1 and {MAX_PROFILES} entries")
    for name, profile in profiles.items():
        if not isinstance(name, str) or not PROFILE_NAME_RE.match(name):
            errors.append(f"invalid profile name {name!r}")
            continue
        if not isinstance(profile, dict):
            errors.append(f"profile {name!r} must be an object")
            continue
        for key in profile:
            if key not in _PROFILE_KEYS:
                errors.append(f"profile {name!r}: unknown key {key!r}")
        if "comment" in profile and not isinstance(profile["comment"], str):
            errors.append(f"profile {name!r}: comment must be a string")
        extends = profile.get("extends")
        if extends is not None and (not isinstance(extends, str) or not PROFILE_NAME_RE.match(extends)):
            errors.append(f"profile {name!r}: extends must be a profile name")
        for field in ("visible", "callable"):
            if field not in profile:
                continue
            rules = profile[field]
            if not isinstance(rules, list):
                errors.append(f"profile {name!r}: {field} must be an array of rule strings")
                continue
            if len(rules) > MAX_RULES:
                errors.append(f"profile {name!r}: {field} has more than {MAX_RULES} rules")
            if len(set(map(str, rules))) != len(rules):
                errors.append(f"profile {name!r}: {field} rules must be unique")
            for rule in rules:
                if not isinstance(rule, str) or not RULE_RE.match(rule):
                    errors.append(
                        f"profile {name!r}: {field} rule {rule!r} is not "
                        "'<upstream>.<tool>' or '<upstream>.*'"
                    )
    return errors


def _signature_errors(signature: object) -> list[str]:
    """Shape-only validation of the reserved detached-signature envelope.

    v1 NEVER verifies signatures -- presence grants nothing and blocks
    nothing; algorithms/keys/trust anchors belong to the future signing gate.
    """
    if not isinstance(signature, dict):
        return ["signature must be an object"]
    errors: list[str] = []
    for key in signature:
        if key not in _SIGNATURE_KEYS:
            errors.append(f"signature: unknown key {key!r}")
    for key in ("algorithm", "key_id", "value"):
        if key not in signature:
            errors.append(f"signature: missing required {key!r}")
    if "algorithm" in signature and signature["algorithm"] != "ed25519":
        errors.append("signature.algorithm must be 'ed25519' (placeholder enum)")
    key_id = signature.get("key_id")
    if key_id is not None and (
        not isinstance(key_id, str)
        or not 1 <= len(key_id) <= MAX_KEY_ID_LENGTH
        or not KEY_ID_RE.match(key_id)
    ):
        errors.append("signature.key_id must be a bounded opaque identifier")
    value = signature.get("value")
    if value is not None and (
        not isinstance(value, str)
        or not 1 <= len(value) <= MAX_SIGNATURE_LENGTH
        or not SIGNATURE_VALUE_RE.match(value)
    ):
        errors.append("signature.value must be base64 text")
    return errors


def _semantic_errors(document: dict) -> list[str]:
    """The design's static load checks beyond the schema shape."""
    errors: list[str] = []
    profiles = document["profiles"]
    default = document.get("default_profile")
    if default is not None and default not in profiles:
        errors.append(f"default_profile {default!r} does not exist")
    for name, profile in profiles.items():
        # extends: target exists, no self-reference, no cycle, depth <= 8.
        chain = [name]
        current = profile
        while "extends" in current:
            parent = current["extends"]
            if parent in chain:
                errors.append(f"profile {name!r}: extends cycle via {parent!r}")
                break
            if parent not in profiles:
                errors.append(f"profile {name!r}: extends unknown profile {parent!r}")
                break
            chain.append(parent)
            if len(chain) > MAX_EXTENDS_DEPTH:
                errors.append(f"profile {name!r}: extends chain deeper than {MAX_EXTENDS_DEPTH}")
                break
            current = profiles[parent]
        # Callable coverage: callable is always a subset of visible. When
        # visible is inherited the check is skipped here; the evaluation-time
        # conjunct in ActiveProfile.is_callable still guarantees the subset.
        visible = profile.get("visible")
        callable_rules = profile.get("callable")
        if isinstance(visible, list) and isinstance(callable_rules, list):
            for rule in callable_rules:
                if not _rule_covered(rule, visible):
                    errors.append(
                        f"profile {name!r}: callable rule {rule!r} is not covered by visible"
                    )
    return errors


def _rule_covered(rule: str, visible: list[str]) -> bool:
    """An exact rule is covered by the same exact rule or its upstream's '.*'
    rule; a '.*' rule is covered only by the same '.*' rule."""
    if rule in visible:
        return True
    upstream, _, tool = rule.partition(".")
    if tool == "*":
        return False
    return f"{upstream}.*" in visible


def load_profile_document(path: Path) -> tuple[dict, str]:
    """Read and fully validate the profile file; return (document, sha256).

    The SHA-256 is over the raw file bytes and pins WHICH version of a
    profile governed a session in the ``profile_loaded`` audit row. Read
    exactly once at startup -- changes on disk never affect a running
    gateway (restart is the revocation procedure).
    """
    path = Path(path)
    try:
        raw = path.read_bytes()
    except OSError:
        raise ProfileLoadError("profile file is missing or unreadable") from None
    sha256 = hashlib.sha256(raw).hexdigest()
    try:
        document = json.loads(raw.decode("utf-8-sig", errors="replace"))
    except json.JSONDecodeError as exc:
        raise ProfileLoadError("profile file is not valid JSON") from exc
    errors = _shape_errors(document)
    if not errors:
        errors = _semantic_errors(document)
    if errors:
        shown = "; ".join(errors[:3])
        if len(errors) > 3:
            shown += f"; and {len(errors) - 3} more"
        raise ProfileLoadError(shown)
    return document, sha256


def select_profile_name(cli_name: str | None, env_name: str | None, default_name: str | None) -> str:
    """Selection precedence: CLI flag > env var > file default ('' = nothing).

    CLI beats env beats file because that is the order of explicitness and
    proximity to the invocation. A selected name is never silently replaced
    by a fallback -- resolution failures are fail-closed, decided upstream.
    """
    for candidate in (cli_name, env_name, default_name):
        candidate = (candidate or "").strip()
        if candidate:
            return candidate
    return ""


def resolve_profile_state(
    path: Path,
    cli_name: str | None = None,
    env_name: str | None = None,
) -> ActiveProfile | FailClosedProfile:
    """Load the profile file and resolve the active profile, fail-closed.

    ``env_name=None`` reads ``UNLIMITED_SKILLS_MCP_PROFILE`` from the real
    environment ('' counts as unset). Never returns ``None``: configuring a
    profile file IS the opt-in to default-deny, so every failure here is a
    refuse-all state, never a fallback to open behavior.
    """
    if env_name is None:
        env_name = os.environ.get(PROFILE_ENV_VAR, "")
    try:
        document, sha256 = load_profile_document(path)
    except ProfileLoadError as exc:
        return FailClosedProfile(
            code=PROFILE_INVALID,
            message=(
                f"The configured profile file is invalid: {exc}; every call is "
                "refused (profile_invalid). Fix the profile file and restart the gateway."
            ),
            requested=select_profile_name(cli_name, env_name, None),
        )
    selected = select_profile_name(cli_name, env_name, document.get("default_profile"))
    if not selected:
        return FailClosedProfile(
            code=PROFILE_NOT_FOUND,
            message=(
                "No profile selected and the profile file has no default_profile; "
                "every call is refused (profile_not_found). Fix --profile, "
                f"{PROFILE_ENV_VAR}, or default_profile."
            ),
            requested="",
        )
    if selected not in document["profiles"]:
        return FailClosedProfile(
            code=PROFILE_NOT_FOUND,
            message=(
                f"Profile '{selected}' does not exist in the configured profile file; "
                "every call is refused (profile_not_found). Fix --profile, "
                f"{PROFILE_ENV_VAR}, or default_profile."
            ),
            requested=selected,
        )
    return _resolve_active(document, selected, sha256)


def _resolve_active(document: dict, name: str, sha256: str) -> ActiveProfile:
    """Compile the ``extends`` chain (already validated acyclic and bounded)."""
    profiles = document["profiles"]
    visible_chain: list[RuleSet] = []
    callable_chain: list[RuleSet] = []
    visible_count = 0
    callable_count = 0
    current: str | None = name
    while current is not None:
        spec = profiles[current]
        if "visible" in spec:
            visible_chain.append(_compile_rules(spec["visible"]))
            visible_count += len(spec["visible"])
        if "callable" in spec:
            callable_chain.append(_compile_rules(spec["callable"]))
            callable_count += len(spec["callable"])
        current = spec.get("extends")
    return ActiveProfile(
        name=name,
        visible_chain=tuple(visible_chain),
        callable_chain=tuple(callable_chain),
        file_sha256=sha256,
        visible_rule_count=visible_count,
        callable_rule_count=callable_count,
    )
