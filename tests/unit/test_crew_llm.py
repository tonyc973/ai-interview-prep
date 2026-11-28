"""Unit tests for :class:`GatewayLLM`, the CrewAI ``BaseLLM`` adapter.

``GatewayLLM`` is the sole bridge that routes the research->questions crew's LLM
traffic through our gateway (so retries, cost caps, accounting, and logging apply
uniformly). The full-lifecycle integration test exercises it only through
CrewAI's opaque ``kickoff()`` and only ever hits the structured-output branch.
These tests pin the adapter contract directly: message coercion, routing to the
structured vs text gateway methods, model passthrough, usage recording, and the
``supports_stop_words`` capability flag.
"""

from __future__ import annotations

import uuid
from typing import Any, cast

from crewai.utilities.types import LLMMessage

from app.agents.crew_llm import GatewayLLM
from app.agents.gateway import CallContext, UsageLedger
from app.agents.schemas import ResearchBrief
from app.domain.enums import LLMOperation
from tests.fakes import FakeGateway, make_brief


def _messages(*raw: dict[str, Any]) -> list[LLMMessage]:
    # ``_coerce`` guards against messages that do not strictly match the
    # ``LLMMessage`` TypedDict at runtime (CrewAI does not enforce it), so the
    # coercion tests feed deliberately malformed dicts; cast keeps that honest.
    return cast("list[LLMMessage]", list(raw))


def _ledger() -> UsageLedger:
    return UsageLedger(
        user_id=uuid.uuid4(),
        session_id=uuid.uuid4(),
        max_cost_per_session_usd=1.0,
        max_cost_per_user_per_day_usd=5.0,
    )


def _ctx() -> CallContext:
    return CallContext(
        user_id=uuid.uuid4(),
        operation=LLMOperation.RESEARCH,
        session_id=uuid.uuid4(),
        agent_name="role-researcher",
    )


def _llm(gateway: FakeGateway, ledger: UsageLedger, *, model: str = "gpt-4o-mini") -> GatewayLLM:
    return GatewayLLM(
        model=model,
        gateway=gateway,
        ledger=ledger,
        context=_ctx(),
        temperature=0.4,
    )


# -- routing ---------------------------------------------------------------- #
def test_call_without_response_model_routes_to_text_completion() -> None:
    gateway = FakeGateway()
    ledger = _ledger()
    llm = _llm(gateway, ledger)

    result = llm.call("Summarize the role.")

    assert result == "ok"
    assert gateway.calls == [("text_sync", LLMOperation.RESEARCH.value)]
    # Usage was recorded through the gateway, like the real path.
    assert len(ledger.entries) == 1
    assert ledger.entries[0].model == "gpt-4o-mini"


def test_call_with_response_model_routes_to_structured_completion() -> None:
    gateway = FakeGateway()
    ledger = _ledger()
    llm = _llm(gateway, ledger)

    result = llm.call("Produce the brief.", response_model=ResearchBrief)

    assert isinstance(result, ResearchBrief)
    assert result == make_brief()
    assert gateway.calls == [("structured_sync", LLMOperation.RESEARCH.value)]
    assert len(ledger.entries) == 1


def test_call_passes_configured_model_through_to_the_gateway() -> None:
    gateway = FakeGateway()
    ledger = _ledger()
    llm = _llm(gateway, ledger, model="gpt-4.1-mini")

    llm.call("anything")

    assert ledger.entries[0].model == "gpt-4.1-mini"


# -- message coercion ------------------------------------------------------- #
def test_coerce_defaults_missing_role_to_user() -> None:
    coerced = GatewayLLM._coerce(_messages({"content": "hello"}))
    assert coerced == [{"role": "user", "content": "hello"}]


def test_coerce_defaults_missing_content_to_empty_string() -> None:
    coerced = GatewayLLM._coerce(_messages({"role": "system"}))
    assert coerced == [{"role": "system", "content": ""}]


def test_coerce_stringifies_non_string_content() -> None:
    # Multimodal/list content must be flattened to a plain string for our
    # text-only agents rather than passed through as a list.
    coerced = GatewayLLM._coerce(_messages({"role": "user", "content": ["a", "b"]}))
    assert coerced == [{"role": "user", "content": "['a', 'b']"}]


def test_coerce_preserves_plain_string_messages() -> None:
    messages = _messages(
        {"role": "system", "content": "You are an interviewer."},
        {"role": "user", "content": "Ask me a question."},
    )
    assert GatewayLLM._coerce(messages) == list(messages)


# -- capabilities ----------------------------------------------------------- #
def test_does_not_support_stop_words() -> None:
    assert _llm(FakeGateway(), _ledger()).supports_stop_words() is False
