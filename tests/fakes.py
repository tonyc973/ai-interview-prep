"""Deterministic fakes used by the test suite. Tests NEVER hit OpenAI.

``FakeGateway`` is a drop-in :class:`LLMGateway` subtype that returns canned,
schema-valid objects and records usage into the ledger exactly like the real
gateway (so cost caps and accounting are exercised), without any network client.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from app.agents.gateway import CallContext, LLMGateway, LLMResult, Usage, UsageLedger
from app.agents.schemas import (
    CompetencyScore,
    EvaluationReport,
    ImprovementItem,
    InterviewQuestion,
    InterviewTurn,
    ModelAnswer,
    QuestionBank,
    ResearchBrief,
)
from app.db.repositories import UsageEntry
from app.domain.enums import Difficulty, QuestionCategory

_LLMMessage = dict[str, str]


def make_brief() -> ResearchBrief:
    return ResearchBrief(
        role_summary="A backend role focused on reliable distributed services.",
        key_competencies=["System design", "Coding", "Communication"],
        likely_interview_format="Phone screen, then 4 onsite rounds.",
        company_values=["Customer obsession", "Ownership"],
        signals_to_emphasize=["Scale experience", "Pragmatism"],
        inferred_assumptions=["Assumed the team uses Python (not stated)."],
    )


def make_question(qid: str, category: QuestionCategory) -> InterviewQuestion:
    return InterviewQuestion(
        id=qid,
        category=category,
        question=f"Question {qid}?",
        difficulty=Difficulty.MEDIUM,
        target_competency="System design",
        rubric="A strong answer covers trade-offs and concrete examples.",
    )


def make_question_bank() -> QuestionBank:
    return QuestionBank(
        technical=[make_question(f"tech-{i}", QuestionCategory.TECHNICAL) for i in range(1, 5)],
        behavioral=[make_question(f"beh-{i}", QuestionCategory.BEHAVIORAL) for i in range(1, 4)],
        company=[make_question(f"comp-{i}", QuestionCategory.COMPANY) for i in range(1, 3)],
        study_plan=["Review system design fundamentals.", "Practice STAR stories."],
    )


def make_turn(closing: bool = False) -> InterviewTurn:
    return InterviewTurn(
        question="Tell me about a system you designed.",
        covers_competency="System design",
        is_followup=False,
        rationale="Probing core competency.",
        closing=closing,
    )


def make_report() -> EvaluationReport:
    return EvaluationReport(
        overall_score=3.5,
        summary="Solid fundamentals with room to deepen system-design detail.",
        competency_scores=[
            CompetencyScore(
                competency="System design",
                score=4,
                evidence=["I sharded the database by tenant id."],
                rationale="Showed concrete scaling decisions.",
            ),
            CompetencyScore(
                competency="Communication",
                score=3,
                evidence=["Um, I think it was fine."],
                rationale="Answers were sometimes vague.",
            ),
        ],
        strengths=["Concrete scaling examples."],
        gaps=["Vague trade-off discussion."],
        model_answers=[ModelAnswer(question="Design a URL shortener", strong_answer="…")],
        improvement_plan=[
            ImprovementItem(priority=1, focus_area="Trade-offs", action="Practice out loud.")
        ],
        next_steps=["Do two mock system-design sessions."],
    )


_DEFAULTS: dict[type[Any], Any] = {
    ResearchBrief: make_brief,
    QuestionBank: make_question_bank,
    InterviewTurn: make_turn,
    EvaluationReport: make_report,
}


class FakeGateway(LLMGateway):
    """LLMGateway stand-in with no network. Records usage like the real one."""

    def __init__(self, *, cost_per_call: float = 0.001) -> None:
        # Intentionally does NOT call super().__init__ (no OpenAI client).
        self.cost_per_call = cost_per_call
        self.calls: list[tuple[str, str]] = []
        self.overrides: dict[type[Any], Any] = {}

    # -- helpers ------------------------------------------------------------
    def _value(self, response_model: type[Any]) -> Any:
        if response_model in self.overrides:
            override = self.overrides[response_model]
            return override() if callable(override) else override
        factory = _DEFAULTS.get(response_model)
        if factory is None:
            raise AssertionError(f"FakeGateway has no canned value for {response_model!r}")
        return factory()

    def _usage(self) -> Usage:
        return Usage(
            prompt_tokens=10,
            completion_tokens=10,
            total_tokens=20,
            cached_tokens=0,
            cost_usd=self.cost_per_call,
        )

    def _record(self, ledger: UsageLedger, context: CallContext, model: str) -> None:
        ledger.check_budget()
        ledger.record(
            UsageEntry(
                user_id=context.user_id,
                session_id=context.session_id,
                operation=context.operation,
                agent_name=context.agent_name,
                model=model,
                prompt_tokens=10,
                completion_tokens=10,
                total_tokens=20,
                cost_usd=self.cost_per_call,
                latency_ms=1,
                success=True,
            )
        )

    # -- sync API -----------------------------------------------------------
    def complete_text_sync(
        self,
        *,
        messages: Sequence[_LLMMessage],
        model: str,
        ledger: UsageLedger,
        context: CallContext,
        temperature: float | None = None,
    ) -> LLMResult[str]:
        self._record(ledger, context, model)
        self.calls.append(("text_sync", context.operation.value))
        return LLMResult(value="ok", usage=self._usage(), model=model, latency_ms=1)

    def complete_structured_sync[T](
        self,
        *,
        messages: Sequence[_LLMMessage],
        model: str,
        response_model: type[T],
        ledger: UsageLedger,
        context: CallContext,
        temperature: float | None = None,
    ) -> LLMResult[T]:
        self._record(ledger, context, model)
        self.calls.append(("structured_sync", context.operation.value))
        return LLMResult(
            value=self._value(response_model), usage=self._usage(), model=model, latency_ms=1
        )

    # -- async API ----------------------------------------------------------
    async def acomplete_text(
        self,
        *,
        messages: Sequence[_LLMMessage],
        model: str,
        ledger: UsageLedger,
        context: CallContext,
        temperature: float | None = None,
    ) -> LLMResult[str]:
        self._record(ledger, context, model)
        self.calls.append(("text_async", context.operation.value))
        return LLMResult(value="ok", usage=self._usage(), model=model, latency_ms=1)

    async def acomplete_structured[T](
        self,
        *,
        messages: Sequence[_LLMMessage],
        model: str,
        response_model: type[T],
        ledger: UsageLedger,
        context: CallContext,
        temperature: float | None = None,
    ) -> LLMResult[T]:
        self._record(ledger, context, model)
        self.calls.append(("structured_async", context.operation.value))
        return LLMResult(
            value=self._value(response_model), usage=self._usage(), model=model, latency_ms=1
        )
