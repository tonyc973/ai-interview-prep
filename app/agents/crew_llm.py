"""GatewayLLM — a CrewAI ``BaseLLM`` that routes every completion through our gateway.

CrewAI 1.x lets you supply a custom ``BaseLLM`` to an agent. We use that hook so
the research->questions crew's LLM traffic flows through the same gateway as the
rest of the app (retries, cost caps, accounting, logging) instead of CrewAI's
own OpenAI client. Our agents use no tools, so ``call`` only needs to handle a
plain completion plus optional structured output.
"""

from __future__ import annotations

from typing import Any

from crewai import BaseLLM
from crewai.utilities.types import LLMMessage
from pydantic import PrivateAttr

from app.agents.gateway import CallContext, LLMGateway, UsageLedger


class GatewayLLM(BaseLLM):
    """Adapter: CrewAI -> LLMGateway. One instance per agent per pipeline run."""

    _gateway: LLMGateway = PrivateAttr()
    _ledger: UsageLedger = PrivateAttr()
    _ctx: CallContext = PrivateAttr()

    def __init__(
        self,
        *,
        model: str,
        gateway: LLMGateway,
        ledger: UsageLedger,
        context: CallContext,
        temperature: float | None = None,
    ) -> None:
        super().__init__(model=model, temperature=temperature)
        self._gateway = gateway
        self._ledger = ledger
        self._ctx = context

    @staticmethod
    def _coerce(messages: list[LLMMessage]) -> list[dict[str, str]]:
        """Force message content to plain strings (our agents are text-only)."""
        coerced: list[dict[str, str]] = []
        for msg in messages:
            content = msg.get("content", "")
            text = content if isinstance(content, str) else str(content)
            coerced.append({"role": str(msg.get("role", "user")), "content": text})
        return coerced

    def call(
        self,
        messages: str | list[LLMMessage],
        tools: list[Any] | None = None,
        callbacks: list[Any] | None = None,
        available_functions: dict[str, Any] | None = None,
        from_task: Any | None = None,
        from_agent: Any | None = None,
        response_model: type[Any] | None = None,
    ) -> Any:
        formatted = self._coerce(self._format_messages(messages))
        if response_model is not None:
            result = self._gateway.complete_structured_sync(
                messages=formatted,
                model=self.model,
                response_model=response_model,
                ledger=self._ledger,
                context=self._ctx,
                temperature=self.temperature,
            )
            return result.value
        result = self._gateway.complete_text_sync(
            messages=formatted,
            model=self.model,
            ledger=self._ledger,
            context=self._ctx,
            temperature=self.temperature,
        )
        return result.value

    def supports_stop_words(self) -> bool:
        return False
