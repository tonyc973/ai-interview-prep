"""The LLM gateway — the single chokepoint for all OpenAI traffic.

Nothing else in the codebase imports ``openai``. The gateway owns:

* the OpenAI sync + async clients,
* retries with exponential backoff + jitter (tenacity) on transient errors,
* request timeouts,
* per-call token/cost accounting recorded into a :class:`UsageLedger`,
* hard cost-cap enforcement (per session and per user/day) checked before each call,
* structured logging of every call (model, latency, tokens, cost, ids) — never
  the prompt contents at INFO (DEBUG only, opt-in).

The gateway never touches the database. It enforces caps against a ledger that
the **service layer** seeds with already-persisted spend and persists afterward.
This keeps the gateway pure and trivially testable with a fake.
"""

from __future__ import annotations

import time
import uuid
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, TypeVar

from openai import (
    APIConnectionError,
    APITimeoutError,
    AsyncOpenAI,
    AuthenticationError,
    BadRequestError,
    InternalServerError,
    OpenAI,
    RateLimitError,
)
from tenacity import (
    AsyncRetrying,
    Retrying,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential_jitter,
)

from app.agents import pricing
from app.domain.enums import LLMOperation
from app.logging import get_logger

if TYPE_CHECKING:
    from app.config import Settings
    from app.db.repositories import UsageEntry

_log = get_logger("llm.gateway")

T = TypeVar("T")

_RETRYABLE = (RateLimitError, APITimeoutError, APIConnectionError, InternalServerError)
_LLMMessage = dict[str, str]


# --------------------------------------------------------------------------- #
# Errors (each carries a user-safe message; raw detail stays in logs)
# --------------------------------------------------------------------------- #
class GatewayError(RuntimeError):
    """Base gateway error. ``user_message`` is safe to show end users."""

    user_message = "The AI service is temporarily unavailable. Please try again."

    def __init__(self, detail: str, *, user_message: str | None = None) -> None:
        super().__init__(detail)
        if user_message is not None:
            self.user_message = user_message


class RateLimited(GatewayError):
    user_message = "The AI service is busy right now. Please try again in a moment."


class LLMTimeout(GatewayError):
    user_message = "The AI service took too long to respond. Please try again."


class ContextOverflow(GatewayError):
    user_message = "The provided text is too long for the model. Please shorten it."


class LLMUnavailable(GatewayError):
    user_message = "The AI service is temporarily unavailable. Please try again."


class CostLimitExceeded(GatewayError):
    """A configured cost cap would be exceeded; the call is refused."""

    user_message = (
        "This action would exceed the configured AI usage budget. "
        "Please try again later or contact support."
    )


# --------------------------------------------------------------------------- #
# Accounting
# --------------------------------------------------------------------------- #
@dataclass(frozen=True, slots=True)
class CallContext:
    """Who/what a call belongs to, for accounting + logging."""

    user_id: uuid.UUID
    operation: LLMOperation
    session_id: uuid.UUID | None = None
    agent_name: str | None = None


@dataclass(frozen=True, slots=True)
class Usage:
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    cached_tokens: int
    cost_usd: float


@dataclass(frozen=True, slots=True)
class LLMResult[T]:
    value: T
    usage: Usage
    model: str
    latency_ms: int


@dataclass
class UsageLedger:
    """In-memory budget tracker for one operation.

    Seeded by the service with spend already persisted in the DB, then handed to
    the gateway, which checks caps and appends an entry per call. The service
    persists ``entries`` afterward.
    """

    user_id: uuid.UUID
    session_id: uuid.UUID | None
    max_cost_per_session_usd: float
    max_cost_per_user_per_day_usd: float
    session_spend_seed: float = 0.0
    user_day_spend_seed: float = 0.0
    entries: list[UsageEntry] = field(default_factory=list)
    _session_spent: float = 0.0
    _user_day_spent: float = 0.0

    @property
    def session_total(self) -> float:
        return self.session_spend_seed + self._session_spent

    @property
    def user_day_total(self) -> float:
        return self.user_day_spend_seed + self._user_day_spent

    def check_budget(self) -> None:
        """Raise CostLimitExceeded if a cap is already met or exceeded."""
        if self.session_id is not None and self.session_total >= self.max_cost_per_session_usd:
            raise CostLimitExceeded(
                f"session spend {self.session_total:.4f} >= cap {self.max_cost_per_session_usd:.4f}"
            )
        if self.user_day_total >= self.max_cost_per_user_per_day_usd:
            raise CostLimitExceeded(
                f"user/day spend {self.user_day_total:.4f} >= cap "
                f"{self.max_cost_per_user_per_day_usd:.4f}"
            )

    def record(self, entry: UsageEntry) -> None:
        self.entries.append(entry)
        self._session_spent += entry.cost_usd
        self._user_day_spent += entry.cost_usd


# --------------------------------------------------------------------------- #
# Gateway
# --------------------------------------------------------------------------- #
class LLMGateway:
    """Single entry point for every OpenAI completion in the app."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        api_key = settings.openai_api_key.get_secret_value()
        # max_retries=0: we own retries via tenacity for uniform backoff + logging.
        self._client = OpenAI(
            api_key=api_key, timeout=settings.openai_request_timeout_s, max_retries=0
        )
        self._aclient = AsyncOpenAI(
            api_key=api_key, timeout=settings.openai_request_timeout_s, max_retries=0
        )
        self._max_attempts = max(1, settings.openai_max_retries)

    # -- retry controllers --------------------------------------------------
    def _sync_retrying(self) -> Retrying:
        return Retrying(
            retry=retry_if_exception_type(_RETRYABLE),
            wait=wait_exponential_jitter(initial=1, max=20),
            stop=stop_after_attempt(self._max_attempts),
            reraise=True,
        )

    def _async_retrying(self) -> AsyncRetrying:
        return AsyncRetrying(
            retry=retry_if_exception_type(_RETRYABLE),
            wait=wait_exponential_jitter(initial=1, max=20),
            stop=stop_after_attempt(self._max_attempts),
            reraise=True,
        )

    # -- error mapping ------------------------------------------------------
    @staticmethod
    def _map_error(exc: Exception) -> GatewayError:
        if isinstance(exc, RateLimitError):
            return RateLimited(f"OpenAI rate limited: {exc}")
        if isinstance(exc, APITimeoutError):
            return LLMTimeout(f"OpenAI timeout: {exc}")
        if isinstance(exc, BadRequestError):
            msg = str(exc).lower()
            if "context_length" in msg or "maximum context" in msg or "too many tokens" in msg:
                return ContextOverflow(f"OpenAI context overflow: {exc}")
            return GatewayError(f"OpenAI bad request: {exc}")
        if isinstance(exc, AuthenticationError):
            return GatewayError(
                f"OpenAI auth failed: {exc}",
                user_message="The AI service is misconfigured. Please contact support.",
            )
        if isinstance(exc, _RETRYABLE):
            return LLMUnavailable(f"OpenAI unavailable: {exc}")
        return LLMUnavailable(f"OpenAI call failed: {exc}")

    # -- usage extraction ---------------------------------------------------
    @staticmethod
    def _usage_from_response(model: str, response: Any) -> Usage:
        raw = getattr(response, "usage", None)
        prompt = int(getattr(raw, "prompt_tokens", 0) or 0)
        completion = int(getattr(raw, "completion_tokens", 0) or 0)
        total = int(getattr(raw, "total_tokens", 0) or (prompt + completion))
        cached = 0
        details = getattr(raw, "prompt_tokens_details", None)
        if details is not None:
            cached = int(getattr(details, "cached_tokens", 0) or 0)
        cost = pricing.cost_usd(
            model, prompt_tokens=prompt, completion_tokens=completion, cached_tokens=cached
        )
        return Usage(
            prompt_tokens=prompt,
            completion_tokens=completion,
            total_tokens=total,
            cached_tokens=cached,
            cost_usd=cost,
        )

    def _entry(self, ctx: CallContext, usage: Usage, model: str, *, success: bool) -> UsageEntry:
        from app.db.repositories import UsageEntry

        return UsageEntry(
            user_id=ctx.user_id,
            session_id=ctx.session_id,
            operation=ctx.operation,
            agent_name=ctx.agent_name,
            model=model,
            prompt_tokens=usage.prompt_tokens,
            completion_tokens=usage.completion_tokens,
            total_tokens=usage.total_tokens,
            cost_usd=usage.cost_usd,
            latency_ms=0,
            success=success,
        )

    def _log_call(
        self, ctx: CallContext, model: str, usage: Usage, latency_ms: int, *, structured: bool
    ) -> None:
        if not pricing.is_known_model(model):
            _log.warning("llm.unknown_model_pricing", model=model)
        _log.info(
            "llm.call",
            operation=ctx.operation.value,
            agent=ctx.agent_name,
            model=model,
            structured=structured,
            prompt_tokens=usage.prompt_tokens,
            completion_tokens=usage.completion_tokens,
            total_tokens=usage.total_tokens,
            cached_tokens=usage.cached_tokens,
            cost_usd=usage.cost_usd,
            latency_ms=latency_ms,
            session_id=str(ctx.session_id) if ctx.session_id else None,
            user_id=str(ctx.user_id),
        )

    # -- sync API (used by CrewAI's GatewayLLM in a worker thread) ----------
    def complete_text_sync(
        self,
        *,
        messages: Sequence[_LLMMessage],
        model: str,
        ledger: UsageLedger,
        context: CallContext,
        temperature: float | None = None,
    ) -> LLMResult[str]:
        ledger.check_budget()
        params: dict[str, Any] = {"model": model, "messages": list(messages)}
        if temperature is not None:
            params["temperature"] = temperature
        response, latency_ms = self._run_sync(
            lambda: self._client.chat.completions.create(**params), ctx=context
        )
        usage = self._usage_from_response(model, response)
        self._finish(ledger, context, usage, model, latency_ms, structured=False)
        text = response.choices[0].message.content or ""
        return LLMResult(value=text, usage=usage, model=model, latency_ms=latency_ms)

    def complete_structured_sync(
        self,
        *,
        messages: Sequence[_LLMMessage],
        model: str,
        response_model: type[T],
        ledger: UsageLedger,
        context: CallContext,
        temperature: float | None = None,
    ) -> LLMResult[T]:
        ledger.check_budget()
        params: dict[str, Any] = {
            "model": model,
            "messages": list(messages),
            "response_format": response_model,
        }
        if temperature is not None:
            params["temperature"] = temperature
        response, latency_ms = self._run_sync(
            lambda: self._client.chat.completions.parse(**params), ctx=context
        )
        usage = self._usage_from_response(model, response)
        self._finish(ledger, context, usage, model, latency_ms, structured=True)
        parsed = response.choices[0].message.parsed
        if parsed is None:
            refusal = response.choices[0].message.refusal
            raise GatewayError(
                f"structured parse returned no object (refusal={refusal})",
                user_message="The AI could not produce a valid response. Please try again.",
            )
        return LLMResult(value=parsed, usage=usage, model=model, latency_ms=latency_ms)

    # -- async API (used by interviewer/evaluator services) -----------------
    async def acomplete_text(
        self,
        *,
        messages: Sequence[_LLMMessage],
        model: str,
        ledger: UsageLedger,
        context: CallContext,
        temperature: float | None = None,
    ) -> LLMResult[str]:
        ledger.check_budget()
        params: dict[str, Any] = {"model": model, "messages": list(messages)}
        if temperature is not None:
            params["temperature"] = temperature
        response, latency_ms = await self._run_async(
            lambda: self._aclient.chat.completions.create(**params), ctx=context
        )
        usage = self._usage_from_response(model, response)
        self._finish(ledger, context, usage, model, latency_ms, structured=False)
        text = response.choices[0].message.content or ""
        return LLMResult(value=text, usage=usage, model=model, latency_ms=latency_ms)

    async def acomplete_structured(
        self,
        *,
        messages: Sequence[_LLMMessage],
        model: str,
        response_model: type[T],
        ledger: UsageLedger,
        context: CallContext,
        temperature: float | None = None,
    ) -> LLMResult[T]:
        ledger.check_budget()
        params: dict[str, Any] = {
            "model": model,
            "messages": list(messages),
            "response_format": response_model,
        }
        if temperature is not None:
            params["temperature"] = temperature
        response, latency_ms = await self._run_async(
            lambda: self._aclient.chat.completions.parse(**params), ctx=context
        )
        usage = self._usage_from_response(model, response)
        self._finish(ledger, context, usage, model, latency_ms, structured=True)
        parsed = response.choices[0].message.parsed
        if parsed is None:
            refusal = response.choices[0].message.refusal
            raise GatewayError(
                f"structured parse returned no object (refusal={refusal})",
                user_message="The AI could not produce a valid response. Please try again.",
            )
        return LLMResult(value=parsed, usage=usage, model=model, latency_ms=latency_ms)

    # -- internals ----------------------------------------------------------
    def _run_sync(self, fn: Callable[[], T], *, ctx: CallContext) -> tuple[T, int]:
        start = time.monotonic()
        try:
            result = self._sync_retrying()(fn)
        except Exception as exc:
            self._log_failure(ctx, exc)
            raise self._map_error(exc) from exc
        latency_ms = int((time.monotonic() - start) * 1000)
        return result, latency_ms

    async def _run_async(self, fn: Callable[[], Any], *, ctx: CallContext) -> tuple[Any, int]:
        start = time.monotonic()
        result: Any = None
        try:
            async for attempt in self._async_retrying():
                with attempt:
                    result = await fn()
        except Exception as exc:
            self._log_failure(ctx, exc)
            raise self._map_error(exc) from exc
        latency_ms = int((time.monotonic() - start) * 1000)
        return result, latency_ms

    def _finish(
        self,
        ledger: UsageLedger,
        ctx: CallContext,
        usage: Usage,
        model: str,
        latency_ms: int,
        *,
        structured: bool,
    ) -> None:
        ledger.record(self._entry(ctx, usage, model, success=True))
        self._log_call(ctx, model, usage, latency_ms, structured=structured)

    def _log_failure(self, ctx: CallContext, exc: Exception) -> None:
        _log.warning(
            "llm.call_failed",
            operation=ctx.operation.value,
            agent=ctx.agent_name,
            session_id=str(ctx.session_id) if ctx.session_id else None,
            user_id=str(ctx.user_id),
            error_type=type(exc).__name__,
        )
