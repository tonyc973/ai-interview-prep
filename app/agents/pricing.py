"""OpenAI token pricing and cost computation.

Prices are USD per 1M tokens. Unknown models fall back to the default (and the
gateway logs a warning) so cost tracking degrades gracefully rather than
crashing. Cached input tokens are billed at a discount.
"""

from __future__ import annotations

from dataclasses import dataclass

CACHED_INPUT_DISCOUNT = 0.5  # cached prompt tokens billed at half the input rate
_PER_MILLION = 1_000_000


@dataclass(frozen=True, slots=True)
class ModelPrice:
    input_per_million: float
    output_per_million: float


# Approximate public list prices (USD / 1M tokens). Adjust as OpenAI updates them.
PRICES: dict[str, ModelPrice] = {
    "gpt-4o-mini": ModelPrice(0.15, 0.60),
    "gpt-4o": ModelPrice(2.50, 10.00),
    "gpt-4.1": ModelPrice(2.00, 8.00),
    "gpt-4.1-mini": ModelPrice(0.40, 1.60),
    "gpt-4.1-nano": ModelPrice(0.10, 0.40),
    "o4-mini": ModelPrice(1.10, 4.40),
    "o3-mini": ModelPrice(1.10, 4.40),
}

DEFAULT_MODEL_PRICE = PRICES["gpt-4o-mini"]


def price_for(model: str) -> ModelPrice | None:
    """Return the price for a model, matching exact id then the longest known prefix.

    Dated/suffixed ids (e.g. ``gpt-4.1-mini-2025-04-14``) resolve to their family
    price. Matching the *longest* prefix — rather than the first in ``PRICES``
    order — keeps resolution correct and order-independent even when one known id
    is itself a prefix of another (``gpt-4.1`` vs ``gpt-4.1-mini``).
    """
    if model in PRICES:
        return PRICES[model]
    best_known: str | None = None
    for known in PRICES:
        if model.startswith(known) and (best_known is None or len(known) > len(best_known)):
            best_known = known
    return PRICES[best_known] if best_known is not None else None


def cost_usd(
    model: str,
    *,
    prompt_tokens: int,
    completion_tokens: int,
    cached_tokens: int = 0,
) -> float:
    """Compute USD cost for a call. Falls back to the default price if unknown."""
    price = price_for(model) or DEFAULT_MODEL_PRICE
    billable_prompt = max(prompt_tokens - cached_tokens, 0)
    input_cost = (
        billable_prompt * price.input_per_million
        + cached_tokens * price.input_per_million * CACHED_INPUT_DISCOUNT
    ) / _PER_MILLION
    output_cost = completion_tokens * price.output_per_million / _PER_MILLION
    return round(input_cost + output_cost, 8)


def is_known_model(model: str) -> bool:
    return price_for(model) is not None
