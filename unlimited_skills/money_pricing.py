"""API price resolution + the money formula for the Money Saved meter (R2).

Loads the in-package price DB (``model_prices.json``, schema ``model-prices-v1``)
and turns a token count into API-equivalent dollars at a chosen cache price class.

Money formula (Hermes R2 spec):

    estimated_money_saved_usd = total_tokens_saved / 1_000_000 * price_per_1m_input_tokens

Price classes mirror Anthropic's input price classes: ``base_input``,
``cache_write_5m``, ``cache_write_1h``, ``cache_hit_refresh``. Providers without a
separate cache-write premium leave those fields ``null``; the engine then falls
back to ``base_input`` for that class. ``status='todo'`` models are not selectable
for money unless the caller explicitly opts in (``allow_todo=True``).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

PRICE_DB_SCHEMA_VERSION = "model-prices-v1"

PRICE_CLASSES = ("base_input", "cache_write_5m", "cache_write_1h", "cache_hit_refresh")
_PRICE_FIELD = {
    "base_input": "base_input_per_1m",
    "cache_write_5m": "cache_write_5m_per_1m",
    "cache_write_1h": "cache_write_1h_per_1m",
    "cache_hit_refresh": "cache_hit_refresh_per_1m",
}


class PriceError(ValueError):
    """Raised when a model cannot be priced (unknown / todo / missing base rate)."""


@dataclass(frozen=True)
class ModelPrice:
    provider: str
    model: str
    aliases: tuple[str, ...]
    currency: str
    base_input_per_1m: float | None
    cache_write_5m_per_1m: float | None
    cache_write_1h_per_1m: float | None
    cache_hit_refresh_per_1m: float | None
    output_per_1m: float | None
    source_url: str
    source_date: str
    status: str

    @property
    def key(self) -> str:
        return f"{self.provider}:{self.model}"


def prices_path() -> Path:
    return Path(__file__).with_name("model_prices.json")


def load_price_db(path: Path | None = None) -> dict[str, Any]:
    data = json.loads((path or prices_path()).read_text(encoding="utf-8"))
    if not isinstance(data, dict) or data.get("schema_version") != PRICE_DB_SCHEMA_VERSION:
        raise PriceError(f"price DB is not {PRICE_DB_SCHEMA_VERSION}")
    return data


def _to_price(record: dict[str, Any]) -> ModelPrice:
    def num(key: str) -> float | None:
        value = record.get(key)
        return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None

    aliases = tuple(str(a) for a in record.get("aliases", []) if isinstance(a, str))
    return ModelPrice(
        provider=str(record.get("provider", "")),
        model=str(record.get("model", "")),
        aliases=aliases,
        currency=str(record.get("currency", "USD")),
        base_input_per_1m=num("base_input_per_1m"),
        cache_write_5m_per_1m=num("cache_write_5m_per_1m"),
        cache_write_1h_per_1m=num("cache_write_1h_per_1m"),
        cache_hit_refresh_per_1m=num("cache_hit_refresh_per_1m"),
        output_per_1m=num("output_per_1m"),
        source_url=str(record.get("source_url", "")),
        source_date=str(record.get("source_date", "")),
        status=str(record.get("status", "active")),
    )


def iter_prices(db: dict[str, Any] | None = None) -> list[ModelPrice]:
    db = db or load_price_db()
    return [_to_price(rec) for rec in db.get("prices", []) if isinstance(rec, dict)]


def _norm(text: str) -> str:
    return text.strip().lower()


def resolve_model(spec: str, db: dict[str, Any] | None = None, *, allow_todo: bool = False) -> ModelPrice | None:
    """Resolve ``provider:model`` / ``model`` / alias to a ModelPrice, or None.

    Matching (case-insensitive): exact ``provider:model`` first, then exact model
    name, then aliases. A ``status='todo'`` record is only returned when
    ``allow_todo`` is set (otherwise it is treated as not selectable).
    """
    if not spec:
        return None
    prices = iter_prices(db)
    want_provider = ""
    want = _norm(spec)
    if ":" in spec:
        want_provider, want = (_norm(part) for part in spec.split(":", 1))

    def ok(price: ModelPrice) -> bool:
        return allow_todo or price.status != "todo"

    if want_provider:
        for price in prices:
            if _norm(price.provider) == want_provider and _norm(price.model) == want and ok(price):
                return price
        for price in prices:
            if _norm(price.provider) == want_provider and want in {_norm(a) for a in price.aliases} and ok(price):
                return price
        return None
    for price in prices:
        if _norm(price.model) == want and ok(price):
            return price
    for price in prices:
        if want in {_norm(a) for a in price.aliases} and ok(price):
            return price
    return None


def price_per_1m(price: ModelPrice, price_class: str = "base_input") -> float:
    """Per-1M input-token rate for ``price_class`` (null class falls back to base)."""
    if price_class not in _PRICE_FIELD:
        raise PriceError(f"unknown price class: {price_class!r}")
    value = getattr(price, _PRICE_FIELD[price_class])
    if value is None:
        value = price.base_input_per_1m
    if value is None:
        raise PriceError(f"{price.key} has no base input rate (status={price.status}); not selectable for money")
    return float(value)


def money_for_tokens(tokens: int | float, price: ModelPrice, price_class: str = "base_input") -> float:
    """API-equivalent dollars for ``tokens`` at ``price_class``."""
    return (float(tokens) / 1_000_000.0) * price_per_1m(price, price_class)


def pricing_basis(price: ModelPrice, price_class: str = "base_input") -> dict[str, Any]:
    """The pricing-basis block embedded in every money report."""
    return {
        "currency": price.currency,
        "source": "official_provider_pricing_snapshot",
        "source_url": price.source_url,
        "source_date": price.source_date,
        "price_class": price_class,
        "price_per_1m_input_tokens": price_per_1m(price, price_class),
    }
