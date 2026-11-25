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


def test_prefix_match_picks_longest_not_first() -> None:
    # "gpt-4.1" is itself a prefix of "gpt-4.1-mini"/"gpt-4.1-nano"; a dated id must
    # resolve to the specific (cheaper) family, not the first prefix in PRICES order.
    assert pricing.price_for("gpt-4.1-mini-2025-04-14") == pricing.PRICES["gpt-4.1-mini"]
    assert pricing.price_for("gpt-4.1-nano-2025-04-14") == pricing.PRICES["gpt-4.1-nano"]
    # The bare family id still resolves to its own exact price.
    assert pricing.price_for("gpt-4.1-2025-04-14") == pricing.PRICES["gpt-4.1"]


def test_prefix_match_cost_is_not_inflated() -> None:
    # Regression: the dated mini id must not be billed at the parent gpt-4.1 rate.
    mini = pricing.cost_usd("gpt-4.1-mini-2025-04-14", prompt_tokens=1_000_000, completion_tokens=0)
    assert mini == pricing.PRICES["gpt-4.1-mini"].input_per_million
    assert mini < pricing.PRICES["gpt-4.1"].input_per_million
