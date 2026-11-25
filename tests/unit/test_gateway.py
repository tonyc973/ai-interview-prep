"""Unit tests for the LLM gateway: usage accounting, retries, error mapping,
and cost-cap enforcement. The OpenAI client is stubbed — no network."""

from __future__ import annotations

import itertools
import types
import uuid
from typing import Any, cast

import httpx
import pytest
from openai import (
    APIConnectionError,
    APITimeoutError,
    AuthenticationError,
    BadRequestError,
    RateLimitError,
)

from app.agents import gateway as gw
from app.agents.gateway import (
    CallContext,
    ContextOverflow,
    CostLimitExceeded,
    LLMGateway,
    LLMTimeout,
    RateLimited,
    UsageLedger,
)
from app.agents.schemas import ResearchBrief
from app.domain.enums import LLMOperation
from tests.conftest import make_settings
from tests.fakes import make_brief

_REQUEST = httpx.Request("POST", "https://api.openai.com/v1/chat/completions")


def _usage_obj(prompt: int = 100, completion: int = 50) -> Any:
    return types.SimpleNamespace(
        prompt_tokens=prompt,
        completion_tokens=completion,
        total_tokens=prompt + completion,
        prompt_tokens_details=types.SimpleNamespace(cached_tokens=0),
    )


def _text_response(text: str = "hello") -> Any:
    message = types.SimpleNamespace(content=text)
    return types.SimpleNamespace(
        choices=[types.SimpleNamespace(message=message)], usage=_usage_obj()
    )


def _parsed_response(parsed: Any) -> Any:
    message = types.SimpleNamespace(parsed=parsed, refusal=None)
    return types.SimpleNamespace(
        choices=[types.SimpleNamespace(message=message)], usage=_usage_obj()
    )


def _refusal_response(refusal: str = "I can't help with that.") -> Any:
    # Structured-output API returned no parsed object (e.g. a model refusal).
    message = types.SimpleNamespace(parsed=None, refusal=refusal)
    return types.SimpleNamespace(
        choices=[types.SimpleNamespace(message=message)], usage=_usage_obj()
    )


def _ledger(**over: Any) -> UsageLedger:
    return UsageLedger(
        user_id=uuid.uuid4(),
        session_id=uuid.uuid4(),
        max_cost_per_session_usd=over.get("session_cap", 1.0),
        max_cost_per_user_per_day_usd=over.get("day_cap", 5.0),
        session_spend_seed=over.get("session_seed", 0.0),
        user_day_spend_seed=over.get("day_seed", 0.0),
    )


def _ctx() -> CallContext:
    return CallContext(user_id=uuid.uuid4(), operation=LLMOperation.RESEARCH, agent_name="x")


def _make_gateway() -> LLMGateway:
    return LLMGateway(make_settings(openai_max_retries=3))


def _set_sync_client(gateway: LLMGateway, *, create: Any = None, parse: Any = None) -> None:
    completions = types.SimpleNamespace(create=create, parse=parse)
    cast(Any, gateway)._client = types.SimpleNamespace(
        chat=types.SimpleNamespace(completions=completions)
    )


def _set_async_client(gateway: LLMGateway, *, create: Any = None, parse: Any = None) -> None:
    completions = types.SimpleNamespace(create=create, parse=parse)
    cast(Any, gateway)._aclient = types.SimpleNamespace(
        chat=types.SimpleNamespace(completions=completions)
    )


# --------------------------------------------------------------------------- #
# Happy paths
# --------------------------------------------------------------------------- #
def test_complete_text_sync_records_usage() -> None:
    gateway = _make_gateway()
    _set_sync_client(gateway, create=lambda **_: _text_response("hi there"))
    ledger = _ledger()
    result = gateway.complete_text_sync(
        messages=[{"role": "user", "content": "x"}],
        model="gpt-4o-mini",
        ledger=ledger,
        context=_ctx(),
    )
    assert result.value == "hi there"
    assert result.usage.prompt_tokens == 100
    assert len(ledger.entries) == 1
    assert ledger.entries[0].cost_usd > 0


def test_records_measured_latency_on_entry(monkeypatch: pytest.MonkeyPatch) -> None:
    # The persisted usage entry must carry the measured call latency, not a
    # placeholder zero (regression: _entry previously hardcoded latency_ms=0).
    # A monotonically increasing fake clock guarantees a positive latency without
    # depending on how many times tenacity reads the clock internally.
    gateway = _make_gateway()
    _set_sync_client(gateway, create=lambda **_: _text_response("hi"))
    ticks = itertools.count(start=10.0, step=0.5)
    monkeypatch.setattr("app.agents.gateway.time.monotonic", lambda: next(ticks))
    ledger = _ledger()
    result = gateway.complete_text_sync(
        messages=[{"role": "user", "content": "x"}],
        model="gpt-4o-mini",
        ledger=ledger,
        context=_ctx(),
    )
    assert result.latency_ms > 0
    assert ledger.entries[0].latency_ms == result.latency_ms


def test_complete_structured_sync_returns_model() -> None:
    gateway = _make_gateway()
    _set_sync_client(gateway, parse=lambda **_: _parsed_response(make_brief()))
    ledger = _ledger()
    result = gateway.complete_structured_sync(
        messages=[{"role": "user", "content": "x"}],
        model="gpt-4o-mini",
        response_model=ResearchBrief,
        ledger=ledger,
        context=_ctx(),
    )
    assert isinstance(result.value, ResearchBrief)
    assert len(ledger.entries) == 1


async def test_acomplete_text_records_usage() -> None:
    gateway = _make_gateway()

    async def _create(**_: Any) -> Any:
        return _text_response("async hi")

    _set_async_client(gateway, create=_create)
    ledger = _ledger()
    result = await gateway.acomplete_text(
        messages=[{"role": "user", "content": "x"}],
        model="gpt-4o-mini",
        ledger=ledger,
        context=_ctx(),
    )
    assert result.value == "async hi"
    assert len(ledger.entries) == 1


async def test_acomplete_structured_returns_model() -> None:
    # The async structured path drives every live interview turn and the final
    # evaluation; exercise it directly (the interview tests use a fake gateway).
    gateway = _make_gateway()

    async def _parse(**_: Any) -> Any:
        return _parsed_response(make_brief())

    _set_async_client(gateway, parse=_parse)
    ledger = _ledger()
    result = await gateway.acomplete_structured(
        messages=[{"role": "user", "content": "x"}],
        model="gpt-4o-mini",
        response_model=ResearchBrief,
        ledger=ledger,
        context=_ctx(),
        temperature=0.3,
    )
    assert isinstance(result.value, ResearchBrief)
    assert len(ledger.entries) == 1
    assert ledger.entries[0].cost_usd > 0


# --------------------------------------------------------------------------- #
# Structured-output refusal safety net (parsed is None)
# --------------------------------------------------------------------------- #
def test_complete_structured_sync_refusal_raises() -> None:
    gateway = _make_gateway()
    _set_sync_client(gateway, parse=lambda **_: _refusal_response())
    with pytest.raises(gw.GatewayError) as excinfo:
        gateway.complete_structured_sync(
            messages=[{"role": "user", "content": "x"}],
            model="gpt-4o-mini",
            response_model=ResearchBrief,
            ledger=_ledger(),
            context=_ctx(),
        )
    assert "valid response" in excinfo.value.user_message.lower()


async def test_acomplete_structured_refusal_raises() -> None:
    gateway = _make_gateway()

    async def _parse(**_: Any) -> Any:
        return _refusal_response()

    _set_async_client(gateway, parse=_parse)
    with pytest.raises(gw.GatewayError) as excinfo:
        await gateway.acomplete_structured(
            messages=[{"role": "user", "content": "x"}],
            model="gpt-4o-mini",
            response_model=ResearchBrief,
            ledger=_ledger(),
            context=_ctx(),
        )
    assert "valid response" in excinfo.value.user_message.lower()


# --------------------------------------------------------------------------- #
# Cost caps
# --------------------------------------------------------------------------- #
def test_session_cap_blocks_before_call() -> None:
    gateway = _make_gateway()
    called = {"n": 0}

    def _create(**_: Any) -> Any:
        called["n"] += 1
        return _text_response()

    _set_sync_client(gateway, create=_create)
    ledger = _ledger(session_cap=0.001, session_seed=0.001)  # already at cap
    with pytest.raises(CostLimitExceeded):
        gateway.complete_text_sync(
            messages=[{"role": "user", "content": "x"}],
            model="gpt-4o-mini",
            ledger=ledger,
            context=_ctx(),
        )
    assert called["n"] == 0  # never reached the API


def test_day_cap_blocks() -> None:
    ledger = _ledger(day_cap=0.5, day_seed=0.5)
    with pytest.raises(CostLimitExceeded):
        ledger.check_budget()


# --------------------------------------------------------------------------- #
# Retries + error mapping
# --------------------------------------------------------------------------- #
def test_retries_transient_then_succeeds() -> None:
    gateway = _make_gateway()
    attempts = {"n": 0}

    def _create(**_: Any) -> Any:
        attempts["n"] += 1
        if attempts["n"] == 1:
            raise APIConnectionError(request=_REQUEST)
        return _text_response("recovered")

    _set_sync_client(gateway, create=_create)
    result = gateway.complete_text_sync(
        messages=[{"role": "user", "content": "x"}],
        model="gpt-4o-mini",
        ledger=_ledger(),
        context=_ctx(),
    )
    assert result.value == "recovered"
    assert attempts["n"] == 2


async def test_async_retries_transient_then_succeeds() -> None:
    # The async retry controller (AsyncRetrying + `with attempt:`) is a distinct
    # code path from the sync one and must retry transient errors too.
    gateway = _make_gateway()
    attempts = {"n": 0}

    async def _create(**_: Any) -> Any:
        attempts["n"] += 1
        if attempts["n"] == 1:
            raise APITimeoutError(request=_REQUEST)
        return _text_response("async recovered")

    _set_async_client(gateway, create=_create)
    result = await gateway.acomplete_text(
        messages=[{"role": "user", "content": "x"}],
        model="gpt-4o-mini",
        ledger=_ledger(),
        context=_ctx(),
    )
    assert result.value == "async recovered"
    assert attempts["n"] == 2


async def test_async_error_mapped_after_retry_exhaustion() -> None:
    gateway = _make_gateway()
    attempts = {"n": 0}

    async def _create(**_: Any) -> Any:
        attempts["n"] += 1
        raise RateLimitError("slow down", response=httpx.Response(429, request=_REQUEST), body=None)

    _set_async_client(gateway, create=_create)
    with pytest.raises(RateLimited):
        await gateway.acomplete_text(
            messages=[{"role": "user", "content": "x"}],
            model="gpt-4o-mini",
            ledger=_ledger(),
            context=_ctx(),
        )
    assert attempts["n"] == 3  # exhausted all attempts (openai_max_retries=3)


def test_bad_request_mapped_to_gateway_error() -> None:
    gateway = _make_gateway()

    def _create(**_: Any) -> Any:
        raise BadRequestError(
            "context_length_exceeded",
            response=httpx.Response(400, request=_REQUEST),
            body=None,
        )

    _set_sync_client(gateway, create=_create)
    with pytest.raises(ContextOverflow):
        gateway.complete_text_sync(
            messages=[{"role": "user", "content": "x"}],
            model="gpt-4o-mini",
            ledger=_ledger(),
            context=_ctx(),
        )


def test_error_mapping_classification() -> None:
    rate = RateLimitError("slow down", response=httpx.Response(429, request=_REQUEST), body=None)
    timeout = APITimeoutError(request=_REQUEST)
    auth = AuthenticationError("nope", response=httpx.Response(401, request=_REQUEST), body=None)
    assert isinstance(LLMGateway._map_error(rate), RateLimited)
    assert isinstance(LLMGateway._map_error(timeout), LLMTimeout)
    mapped_auth = LLMGateway._map_error(auth)
    assert isinstance(mapped_auth, gw.GatewayError)
    assert "support" in mapped_auth.user_message.lower()
