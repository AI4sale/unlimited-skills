"""Token counting for the Money Saved meter (O064-R2-02 / R2-03).

The Money Saved value model is denominated in REAL tokens, not bytes. For the
Claude path the truth source is Anthropic's ``count_tokens`` API — Opus 4.7+
uses a tokenizer that can emit up to ~35% more tokens than ``bytes // 4``, so
the old byte heuristic systematically *undercounts* Claude context and is
FORBIDDEN as the primary method (the R2 release gate fails on it).

Two methods, in priority order:

1. ``anthropic_count_tokens`` — exact for the bound Claude model. Requires the
   ``anthropic`` SDK and an API key; sends only the Level-1 descriptor / tool
   schema text (never raw prompts or skill bodies — see :func:`token_count_privacy`).
   ``exact_for_model=True`` and ``release_acceptable=True``.
2. ``bytes_divided_by_4`` — offline approximation fallback. ``exact_for_model=False``
   and ``release_acceptable=False``: usable for a quick local estimate, but it
   CANNOT close the R2 release for a Claude model.

Callers may inject an ``exact_counter`` (a ``Callable[[str], int]``) to supply an
exact count from any tokenizer — tests use this for determinism, and a non-Claude
provider can plug in its own native counter the same way.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Callable

ANTHROPIC_COUNTER = "anthropic_count_tokens"
PROVIDER_COUNTER = "provider_count_tokens"
FALLBACK_NAME = "bytes_divided_by_4"
APPROX_BYTES_PER_TOKEN = 4


@dataclass(frozen=True)
class TokenCount:
    tokens: int
    provider: str
    method: str  # anthropic_count_tokens | provider_count_tokens | bytes_divided_by_4
    exact_for_model: bool
    release_acceptable: bool
    model_api_id: str | None = None

    @property
    def used_provider_api(self) -> bool:
        return self.method in (ANTHROPIC_COUNTER, PROVIDER_COUNTER)

    def descriptor(self) -> dict[str, Any]:
        """The ``token_counter`` block embedded in every savings report."""
        return {
            "provider": self.provider,
            "method": self.method,
            "exact_for_model": self.exact_for_model,
            "release_acceptable": self.release_acceptable,
        }


def bytes_divided_by_4(text: str) -> int:
    """Offline byte heuristic (~4 bytes/token for English JSON/markdown)."""
    return len((text or "").encode("utf-8")) // APPROX_BYTES_PER_TOKEN


def make_anthropic_counter(model_api_id: str, *, api_key: str | None = None) -> Callable[[str], int] | None:
    """Build an exact Claude token counter, or ``None`` if unavailable offline.

    Returns ``None`` (so callers fall back to the byte heuristic) when the
    ``anthropic`` SDK is not importable or no API key is configured. The counter
    itself may still raise at call time (network/auth) — :func:`count_tokens`
    catches that and falls back.
    """
    try:
        import anthropic  # type: ignore
    except ImportError:
        return None
    key = api_key or os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        return None
    client = anthropic.Anthropic(api_key=key)

    def _count(text: str) -> int:
        resp = client.messages.count_tokens(
            model=model_api_id,
            messages=[{"role": "user", "content": text}],
        )
        return int(resp.input_tokens)

    return _count


def count_tokens(
    text: str,
    *,
    provider: str,
    model_api_id: str | None = None,
    exact_counter: Callable[[str], int] | None = None,
    prefer: str = "auto",
) -> TokenCount:
    """Count tokens in ``text`` for ``provider``/``model_api_id``.

    ``prefer="auto"`` (default): try the exact path (injected ``exact_counter``,
    or the Anthropic API for ``provider == 'anthropic'``); on any failure fall
    back to ``bytes_divided_by_4``. ``prefer="bytes"`` forces the heuristic.
    """
    if prefer != "bytes":
        # An injected exact counter wins for any provider (tests + native counters).
        if exact_counter is not None:
            try:
                method = ANTHROPIC_COUNTER if provider == "anthropic" else PROVIDER_COUNTER
                return TokenCount(int(exact_counter(text)), provider, method, True, True, model_api_id)
            except Exception:
                pass
        elif provider == "anthropic" and model_api_id:
            counter = make_anthropic_counter(model_api_id)
            if counter is not None:
                try:
                    return TokenCount(int(counter(text)), provider, ANTHROPIC_COUNTER, True, True, model_api_id)
                except Exception:
                    pass
    return TokenCount(bytes_divided_by_4(text), provider, FALLBACK_NAME, False, False, model_api_id)


def token_count_privacy(*, provider_count_tokens_used: bool) -> dict[str, Any]:
    """The user-visible disclosure for what exact token counting sends.

    Exact counting POSTs the Level-1 descriptor / tool-schema text to the
    provider's ``count_tokens`` endpoint. It NEVER sends raw task prompts or
    skill bodies. No silent upload: this block is surfaced in every report so
    the user can see exactly what left the machine.
    """
    return {
        "provider_count_tokens_used": bool(provider_count_tokens_used),
        "sent_material": "level1_skill_descriptions_and_mcp_tool_schemas",
        "raw_prompts_sent": False,
        "skill_bodies_sent": False,
        "requires_provider_api": True,
    }
