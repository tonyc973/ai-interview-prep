"""Unit tests for token pricing."""

from __future__ import annotations

from app.agents import pricing


def test_known_model_cost() -> None:
    cost = pricing.cost_usd("gpt-4o-mini", prompt_tokens=1_000_000, completion_tokens=0)
    assert cost == 0.15  # $0.15 / 1M input


def test_output_cost_added() -> None:
    cost = pricing.cost_usd("gpt-4o-mini", prompt_tokens=0, completion_tokens=1_000_000)
    assert cost == 0.60


def test_cached_tokens_discounted() -> None:
    full = pricing.cost_usd("gpt-4o-mini", prompt_tokens=1_000_000, completion_tokens=0)
    cached = pricing.cost_usd(
        "gpt-4o-mini", prompt_tokens=1_000_000, completion_tokens=0, cached_tokens=1_000_000
    )
    assert cached < full
    assert cached == full * pricing.CACHED_INPUT_DISCOUNT


def test_unknown_model_falls_back_to_default() -> None:
    assert not pricing.is_known_model("some-future-model")
    cost = pricing.cost_usd("some-future-model", prompt_tokens=1_000_000, completion_tokens=0)
    assert cost == pricing.DEFAULT_MODEL_PRICE.input_per_million / 1.0 / 1_000_000 * 1_000_000


def test_prefix_match() -> None:
    assert pricing.price_for("gpt-4o-mini-2024-07-18") == pricing.PRICES["gpt-4o-mini"]
