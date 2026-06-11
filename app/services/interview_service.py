"""Mock-interview service: a stateful, turn-by-turn loop + final evaluation.

Per the architecture invariant this is NOT a single ``crew.kickoff()``. Turn
state lives in the database; each candidate answer triggers exactly one
interviewer LLM call. Every LLM call seeds a fresh :class:`UsageLedger` from
persisted spend (so cost caps hold across the whole multi-request interview) and
persists its entry afterward.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from app.agents import prompts as prompts_bridge
from app.agents.gateway import CallContext, LLMGateway
from app.agents.schemas import EvaluationReport, InterviewQuestion, InterviewTurn, QuestionBank
from app.config import Settings
from app.db.base import session_scope
from app.db.repositories import ReportRepository, SessionRepository, TranscriptRepository
from app.domain.enums import (
    AgentName,
    InterviewStatus,
    LLMOperation,
    MessageRole,
    SeniorityLevel,
    SessionStatus,
)
from app.logging import get_logger
from app.services.usage_service import UsageService

_log = get_logger("interview")


class InterviewStateError(RuntimeError):
    """The interview is not in a state that allows the requested action."""

    def __init__(self, user_message: str) -> None:
        super().__init__(user_message)
        self.user_message = user_message


@dataclass(frozen=True, slots=True)
class TurnView:
    role: MessageRole
    content: str
    question_index: int | None


@dataclass(frozen=True, slots=True)
class InterviewState:
    status: InterviewStatus
    total_questions: int
    asked_questions: int
    turns: list[TurnView]
    awaiting_answer: bool
    finished: bool

    @property
    def progress_label(self) -> str:
        shown = min(self.asked_questions, self.total_questions)
        return f"Question {shown} of {self.total_questions}"


class InterviewService:
    def __init__(
        self, settings: Settings, gateway: LLMGateway, usage_service: UsageService
    ) -> None:
        self._settings = settings
        self._gateway = gateway
        self._usage = usage_service

    # -- lifecycle ----------------------------------------------------------
    async def start(self, session_id: uuid.UUID, user_id: uuid.UUID) -> InterviewState:
        async with session_scope() as session:
            prep = await SessionRepository(session).get_owned(session_id, user_id)
            if prep is None:
                raise InterviewStateError("Session not found.")
            if prep.status != SessionStatus.READY or prep.question_bank is None:
                raise InterviewStateError("This session is not ready for an interview yet.")
            if prep.interview_status in (
                InterviewStatus.IN_PROGRESS,
                InterviewStatus.COMPLETED,
                InterviewStatus.EVALUATING,
                InterviewStatus.EVALUATED,
            ):
                return await self._state(session_id, user_id)
            prep.interview_status = InterviewStatus.IN_PROGRESS
            prep.interview_current_index = 0

        await self._ask_next(session_id, user_id, question_number=1)
        return await self._state(session_id, user_id)

    async def submit_answer(
        self, session_id: uuid.UUID, user_id: uuid.UUID, answer: str
    ) -> InterviewState:
        answer = (answer or "").strip()
        if not answer:
            raise InterviewStateError("Please enter an answer before submitting.")

        async with session_scope() as session:
            transcripts = TranscriptRepository(session)
            prep = await SessionRepository(session).get_owned(session_id, user_id)
            if prep is None:
                raise InterviewStateError("Session not found.")
            if prep.interview_status != InterviewStatus.IN_PROGRESS:
                raise InterviewStateError("This interview is not in progress.")
            next_index = await transcripts.next_turn_index(session_id)
            await transcripts.add_turn(
                session_id=session_id,
                turn_index=next_index,
                role=MessageRole.CANDIDATE,
                content=answer,
            )
            asked = prep.interview_current_index
            total = prep.interview_total_questions
            completed = asked >= total
            if completed:
                prep.interview_status = InterviewStatus.COMPLETED

        if not completed:
            await self._ask_next(session_id, user_id, question_number=asked + 1)
        return await self._state(session_id, user_id)

    async def evaluate(self, session_id: uuid.UUID, user_id: uuid.UUID) -> EvaluationReport:
        async with session_scope() as session:
            prep = await SessionRepository(session).get_owned(session_id, user_id)
            if prep is None:
                raise InterviewStateError("Session not found.")
            if prep.interview_status not in (
                InterviewStatus.COMPLETED,
                InterviewStatus.EVALUATED,
                InterviewStatus.EVALUATING,
            ):
                raise InterviewStateError("Finish the interview before requesting feedback.")
            questions = QuestionBank.model_validate(prep.question_bank or {})
            competencies = _competencies(prep.research_brief, questions)
            model = self._settings.model_for_agent(AgentName.EVALUATOR)
            prep.interview_status = InterviewStatus.EVALUATING

        transcript = await self._transcript_tuples(session_id)
        messages = prompts_bridge.evaluator_messages(
            target_role=await self._role(session_id),
            target_company=await self._company(session_id),
            seniority=await self._seniority(session_id),
            competencies=competencies,
            rubric_block=_rubric_block(questions),
            transcript=transcript,
        )
        try:
            report = await self._structured_call(
                user_id=user_id,
                session_id=session_id,
                operation=LLMOperation.EVALUATION,
                agent=AgentName.EVALUATOR,
                model=model,
                messages=messages,
                response_model=EvaluationReport,
            )
        except Exception:
            await self._set_interview_status(session_id, InterviewStatus.COMPLETED)
            raise

        async with session_scope() as session:
            await ReportRepository(session).upsert(
                session_id=session_id,
                overall_score=report.overall_score,
                summary=report.summary,
                report=report.model_dump(mode="json"),
            )
            prep = await SessionRepository(session).get(session_id)
            if prep is not None:
                prep.interview_status = InterviewStatus.EVALUATED
        _log.info("interview.evaluated", session_id=str(session_id))
        return report

    # -- views --------------------------------------------------------------
    async def get_state(self, session_id: uuid.UUID, user_id: uuid.UUID) -> InterviewState | None:
        async with session_scope() as session:
            prep = await SessionRepository(session).get_owned(session_id, user_id)
            if prep is None:
                return None
        return await self._state(session_id, user_id)

    async def get_report(
        self, session_id: uuid.UUID, user_id: uuid.UUID
    ) -> EvaluationReport | None:
        async with session_scope() as session:
            prep = await SessionRepository(session).get_owned(session_id, user_id)
            if prep is None:
                return None
            row = await ReportRepository(session).get_for_session(session_id)
            if row is None:
                return None
            return EvaluationReport.model_validate(row.report)

    # -- internals ----------------------------------------------------------
    async def _ask_next(
        self, session_id: uuid.UUID, user_id: uuid.UUID, *, question_number: int
    ) -> None:
        async with session_scope() as session:
            prep = await SessionRepository(session).get_owned(session_id, user_id)
            if prep is None:
                return
            questions = QuestionBank.model_validate(prep.question_bank or {})
            total = prep.interview_total_questions
            brief_raw = prep.research_brief
            role, company, seniority = prep.target_role, prep.target_company, prep.seniority

        backbones = _backbone_questions(questions, total)
        planned = backbones[question_number - 1] if question_number <= len(backbones) else None
        competencies = _competencies(brief_raw, questions)
        transcript = await self._transcript_tuples(session_id)

        messages = prompts_bridge.interviewer_messages(
            target_role=role,
            target_company=company,
            seniority=seniority,
            brief_summary=_brief_summary(brief_raw),
            competencies=competencies,
            planned_question=planned.question if planned else None,
            transcript=transcript,
            question_number=question_number,
            total_questions=total,
            is_final=question_number >= total,
        )
        turn = await self._structured_call(
            user_id=user_id,
            session_id=session_id,
            operation=LLMOperation.INTERVIEW_TURN,
            agent=AgentName.MOCK_INTERVIEWER,
            model=self._settings.model_for_agent(AgentName.MOCK_INTERVIEWER),
            messages=messages,
            response_model=InterviewTurn,
        )

        async with session_scope() as session:
            transcripts = TranscriptRepository(session)
            prep = await SessionRepository(session).get_owned(session_id, user_id)
            if prep is None:
                return
            next_index = await transcripts.next_turn_index(session_id)
            await transcripts.add_turn(
                session_id=session_id,
                turn_index=next_index,
                role=MessageRole.INTERVIEWER,
                content=turn.question,
                question_index=question_number,
                competency=turn.covers_competency,
            )
            prep.interview_current_index = question_number

    async def _structured_call[T](
        self,
        *,
        user_id: uuid.UUID,
        session_id: uuid.UUID,
        operation: LLMOperation,
        agent: AgentName,
        model: str,
        messages: list[dict[str, str]],
        response_model: type[T],
    ) -> T:
        ledger = await self._usage.new_ledger(user_id=user_id, session_id=session_id)
        try:
            result = await self._gateway.acomplete_structured(
                messages=messages,
                model=model,
                response_model=response_model,
                ledger=ledger,
                context=CallContext(
                    user_id=user_id,
                    session_id=session_id,
                    operation=operation,
                    agent_name=agent.value,
                ),
                temperature=0.5,
            )
            return result.value
        finally:
            await self._usage.persist(ledger)

    async def _state(self, session_id: uuid.UUID, user_id: uuid.UUID) -> InterviewState:
        async with session_scope() as session:
            prep = await SessionRepository(session).get_owned(session_id, user_id)
            if prep is None:
                raise InterviewStateError("Session not found.")
            turn_rows = await TranscriptRepository(session).list_for_session(session_id)
            status = prep.interview_status
            total = prep.interview_total_questions
            asked = prep.interview_current_index

        turns = [
            TurnView(role=t.role, content=t.content, question_index=t.question_index)
            for t in turn_rows
            if t.role != MessageRole.SYSTEM
        ]
        awaiting = status == InterviewStatus.IN_PROGRESS and (
            not turns or turns[-1].role == MessageRole.INTERVIEWER
        )
        finished = status in (
            InterviewStatus.COMPLETED,
            InterviewStatus.EVALUATING,
            InterviewStatus.EVALUATED,
        )
        return InterviewState(
            status=status,
            total_questions=total,
            asked_questions=asked,
            turns=turns,
            awaiting_answer=awaiting,
            finished=finished,
        )

    async def _transcript_tuples(self, session_id: uuid.UUID) -> list[tuple[str, str]]:
        async with session_scope() as session:
            rows = await TranscriptRepository(session).list_for_session(session_id)
        return [(row.role.value, row.content) for row in rows if row.role != MessageRole.SYSTEM]

    async def _set_interview_status(self, session_id: uuid.UUID, status: InterviewStatus) -> None:
        async with session_scope() as session:
            prep = await SessionRepository(session).get(session_id)
            if prep is not None:
                prep.interview_status = status

    async def _role(self, session_id: uuid.UUID) -> str:
        return await self._scalar(session_id, "target_role")

    async def _company(self, session_id: uuid.UUID) -> str:
        return await self._scalar(session_id, "target_company")

    async def _seniority(self, session_id: uuid.UUID) -> SeniorityLevel:
        async with session_scope() as session:
            prep = await SessionRepository(session).get(session_id)
            assert prep is not None
            return prep.seniority

    async def _scalar(self, session_id: uuid.UUID, attr: str) -> str:
        async with session_scope() as session:
            prep = await SessionRepository(session).get(session_id)
            assert prep is not None
            return str(getattr(prep, attr))


# --------------------------------------------------------------------------- #
# Pure helpers
# --------------------------------------------------------------------------- #
def _backbone_questions(qb: QuestionBank, n: int) -> list[InterviewQuestion]:
    """Round-robin across categories so the interview is varied, capped at n."""
    buckets = [list(qb.technical), list(qb.behavioral), list(qb.company)]
    ordered: list[InterviewQuestion] = []
    index = 0
    while len(ordered) < n and any(b[index:] for b in buckets):
        for bucket in buckets:
            if index < len(bucket):
                ordered.append(bucket[index])
                if len(ordered) >= n:
                    break
        index += 1
    return ordered


def _competencies(brief_raw: dict[str, object] | None, qb: QuestionBank) -> list[str]:
    comps_raw = brief_raw.get("key_competencies") if brief_raw else None
    if isinstance(comps_raw, list):
        comps = [str(c) for c in comps_raw]
        if comps:
            return comps
    seen: list[str] = []
    for q in qb.all_questions():
        if q.target_competency not in seen:
            seen.append(q.target_competency)
    return seen or ["General competency"]


def _brief_summary(brief_raw: dict[str, object] | None) -> str:
    if brief_raw and isinstance(brief_raw.get("role_summary"), str):
        return str(brief_raw["role_summary"])
    return "No role summary available."


def _rubric_block(qb: QuestionBank) -> str:
    lines = [f"[{q.id}] {q.question}\n  Rubric: {q.rubric}" for q in qb.all_questions()]
    return "\n".join(lines)
