"""Skills context savings for the Money Saved meter (O064-R2-02).

Half A of the value model (the other half is MCP, R2-03). Progressive
disclosure collapses the WHOLE library down to one router descriptor, so the
context a session would otherwise carry is:

    baseline = Level-1 descriptor (name + description) of EVERY visible skill
    actual   = the single router descriptor that remains in context
    skills_tokens_saved (per event) = baseline_tokens - actual_router_tokens

Both sides are measured with the SAME token counter (Anthropic ``count_tokens``
for Claude; ``bytes // 4`` fallback flagged not-release-acceptable) so the
subtraction is apples-to-apples and REAL — not a byte ratio. We send only the
Level-1 descriptor text to the counter, never skill bodies or task prompts (see
:func:`unlimited_skills.token_counting.token_count_privacy`).

The skill inventory reuses the router's own :func:`iter_skills`, so "every
visible skill" here is exactly the set the router actually dedups and serves.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from .search_core import DEFAULT_ROOT, iter_skills
from .token_counting import count_tokens, token_count_privacy

# The single Level-1 descriptor that progressive disclosure leaves in context
# in place of the whole library. Measured with the same counter as the baseline
# (its token count is the "~47 tokens" actual router cost, computed not assumed).
ROUTER_DESCRIPTOR_NAME = "unlimited-skills"
ROUTER_DESCRIPTOR_DESCRIPTION = (
    "Router for a large local skill library. Given a task in a few keywords, "
    "returns the most relevant proven skills (checklists, workflows, regression "
    "recipes) on demand, instead of loading every skill description into context."
)

BASELINE_MATERIAL = "level1_name_description_for_every_visible_skill"
ACTUAL_MATERIAL = "router_descriptor"


def descriptor_line(name: str, description: str) -> str:
    """One Level-1 descriptor line: ``name: description`` (the picker unit)."""
    return f"{(name or '').strip()}: {(description or '').strip()}".strip()


def inventory_skill_descriptors(root: str | Path | None = None) -> list[tuple[str, str]]:
    """(name, description) for every visible skill, deduped by the router."""
    base = Path(root).expanduser() if root is not None else DEFAULT_ROOT
    return [(hit.name, hit.description) for hit, _body in iter_skills(base)]


def baseline_descriptor_text(descriptors: list[tuple[str, str]]) -> str:
    """The full Level-1 metadata blob that would load into context."""
    return "\n".join(descriptor_line(name, desc) for name, desc in descriptors)


def router_descriptor_text() -> str:
    return descriptor_line(ROUTER_DESCRIPTOR_NAME, ROUTER_DESCRIPTOR_DESCRIPTION)


def build_skills_savings(
    *,
    provider: str,
    model_api_id: str | None = None,
    root: str | Path | None = None,
    descriptors: list[tuple[str, str]] | None = None,
    exact_counter: Callable[[str], int] | None = None,
    event_count: int = 1,
) -> dict[str, Any]:
    """Build the ``skills_savings`` block (R2 spec §2).

    ``descriptors`` may be supplied directly (tests / cached inventory); else the
    library at ``root`` (default: the router's library) is scanned. ``event_count``
    scales ``total_tokens_saved`` — the per-event saving re-enters context on every
    session start / compaction (the events module supplies the real count).
    """
    inventory = descriptors if descriptors is not None else inventory_skill_descriptors(root)
    baseline_text = baseline_descriptor_text(inventory)
    actual_text = router_descriptor_text()

    baseline_tc = count_tokens(
        baseline_text, provider=provider, model_api_id=model_api_id, exact_counter=exact_counter
    )
    actual_tc = count_tokens(
        actual_text, provider=provider, model_api_id=model_api_id, exact_counter=exact_counter
    )
    saved_per_event = max(0, baseline_tc.tokens - actual_tc.tokens)
    events = max(1, int(event_count))

    return {
        "baseline_skill_count": len(inventory),
        "baseline_material": BASELINE_MATERIAL,
        "baseline_tokens": baseline_tc.tokens,
        "actual_material": ACTUAL_MATERIAL,
        "actual_router_tokens": actual_tc.tokens,
        "tokens_saved_per_event": saved_per_event,
        "event_count": events,
        "total_tokens_saved": saved_per_event * events,
        "token_counter": baseline_tc.descriptor(),
        "token_count_privacy": token_count_privacy(
            provider_count_tokens_used=baseline_tc.used_provider_api
        ),
    }
