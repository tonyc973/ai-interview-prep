"""Prep-session service: creation, the research->questions pipeline, retrieval.

The pipeline is offloaded with ``asyncio.to_thread`` so the (blocking, sync)
CrewAI kickoff never stalls the event loop. Services stay framework-agnostic;
the UI just awaits or backgrounds these coroutines and polls ``status``. Cost
caps are enforced before any LLM work; failures move the session to FAILED with
a user-safe message and never leak internals.
"""

from __future__ import annotations

import asyncio
import uuid

from app.agents.crews import run_questions_stage, run_research_stage
from app.agents.gateway import CostLimitExceeded, GatewayError, LLMGateway
from app.agents.schemas import QuestionBank, ResearchBrief
from app.config import Settings
from app.db.base import session_scope
from app.db.models import PrepSession
from app.db.repositories import SessionRepository
from app.domain.enums import SeniorityLevel, SessionStatus
from app.logging import get_logger
from app.services.usage_service import UsageService

_log = get_logger("session")


class SessionInputError(ValueError):
    """Invalid session-creation input. ``user_message`` is safe to display."""

    def __init__(self, user_message: str, *, field: str | None = None) -> None:
        super().__init__(user_message)
        self.user_message = user_message
        self.field = field


class SessionService:
    def __init__(
        self, settings: Settings, gateway: LLMGateway, usage_service: UsageService
    ) -> None:
        self._settings = settings
        self._gateway = gateway
        self._usage = usage_service

    # -- creation -----------------------------------------------------------
    async def create_session(
        self,
        *,
        user_id: uuid.UUID,
        target_role: str,
        target_company: str,
        seniority: SeniorityLevel,
        job_description: str,
        cv_text: str | None,
    ) -> PrepSession:
        role = _require(target_role, field="role", label="Target role", max_len=200)
        company = _require(target_company, field="company", label="Target company", max_len=200)
        jd = _require(
            job_description,
            field="job_description",
            label="Job description",
            max_len=self._settings.max_jd_chars,
        )
        cv = (cv_text or "").strip() or None
        if cv is not None and len(cv) > self._settings.max_cv_chars:
            raise SessionInputError(
                f"CV must be at most {self._settings.max_cv_chars} characters.",
                field="cv_text",
            )

        async with session_scope() as session:
            prep = await SessionRepository(session).create(
                user_id=user_id,
                target_role=role,
                target_company=company,
                seniority=seniority,
                job_description=jd,
                cv_text=cv,
                interview_total_questions=self._settings.interview_default_questions,
            )
        _log.info("session.created", session_id=str(prep.id), user_id=str(user_id))
        return prep

    # -- pipeline -----------------------------------------------------------
    async def run_pipeline(self, session_id: uuid.UUID) -> None:
        """Run research -> questions for a session. Safe to launch as a task."""
        async with session_scope() as session:
            prep = await SessionRepository(session).get(session_id)
            if prep is None:
                return
            user_id = prep.user_id
            role, company = prep.target_role, prep.target_company
            seniority, jd, cv = prep.seniority, prep.job_description, prep.cv_text

        try:
            await self._usage.assert_within_caps(user_id=user_id, session_id=session_id)
        except CostLimitExceeded as exc:
            await self._set_failed(session_id, exc.user_message)
            return

        ledger = await self._usage.new_ledger(user_id=user_id, session_id=session_id)
        await self._set_status(session_id, SessionStatus.RESEARCHING)
        try:
            brief = await asyncio.to_thread(
                run_research_stage,
                settings=self._settings,
                gateway=self._gateway,
                ledger=ledger,
                target_role=role,
                target_company=company,
                seniority=seniority,
                job_description=jd,
                cv_text=cv,
            )
            await self._store_brief(session_id, brief)

            questions = await asyncio.to_thread(
                run_questions_stage,
                settings=self._settings,
                gateway=self._gateway,
                ledger=ledger,
                target_role=role,
                target_company=company,
                seniority=seniority,
                brief=brief,
            )
            await self._store_questions(session_id, questions)
            _log.info("session.ready", session_id=str(session_id))
        except GatewayError as exc:
            _log.warning("session.pipeline_gateway_error", session_id=str(session_id))
            await self._set_failed(session_id, exc.user_message)
        except Exception:
            _log.exception("session.pipeline_failed", session_id=str(session_id))
            await self._set_failed(session_id, "Preparation failed unexpectedly. Please try again.")
        finally:
            await self._usage.persist(ledger)

    # -- retrieval ----------------------------------------------------------
    async def get_session(self, session_id: uuid.UUID, user_id: uuid.UUID) -> PrepSession | None:
        async with session_scope() as session:
            return await SessionRepository(session).get_owned(session_id, user_id)

    async def list_sessions(self, user_id: uuid.UUID) -> list[PrepSession]:
        async with session_scope() as session:
            return await SessionRepository(session).list_for_user(user_id)

    @staticmethod
    def parse_brief(prep: PrepSession) -> ResearchBrief | None:
        if prep.research_brief is None:
            return None
        return ResearchBrief.model_validate(prep.research_brief)

    @staticmethod
    def parse_questions(prep: PrepSession) -> QuestionBank | None:
        if prep.question_bank is None:
            return None
        return QuestionBank.model_validate(prep.question_bank)

    # -- internal state writes ---------------------------------------------
    async def _set_status(self, session_id: uuid.UUID, status: SessionStatus) -> None:
        async with session_scope() as session:
            prep = await SessionRepository(session).get(session_id)
            if prep is not None:
                prep.status = status
                if status != SessionStatus.FAILED:
                    prep.error_message = None

    async def _store_brief(self, session_id: uuid.UUID, brief: ResearchBrief) -> None:
        async with session_scope() as session:
            prep = await SessionRepository(session).get(session_id)
            if prep is not None:
                prep.research_brief = brief.model_dump(mode="json")
                prep.status = SessionStatus.GENERATING
                prep.error_message = None

    async def _store_questions(self, session_id: uuid.UUID, questions: QuestionBank) -> None:
        async with session_scope() as session:
            prep = await SessionRepository(session).get(session_id)
            if prep is not None:
                prep.question_bank = questions.model_dump(mode="json")
                prep.status = SessionStatus.READY
                prep.error_message = None

    async def _set_failed(self, session_id: uuid.UUID, message: str) -> None:
        async with session_scope() as session:
            prep = await SessionRepository(session).get(session_id)
            if prep is not None:
                prep.status = SessionStatus.FAILED
                prep.error_message = message


def _require(value: str, *, field: str, label: str, max_len: int) -> str:
    cleaned = (value or "").strip()
    if not cleaned:
        raise SessionInputError(f"{label} is required.", field=field)
    if len(cleaned) > max_len:
        raise SessionInputError(f"{label} must be at most {max_len} characters.", field=field)
    return cleaned
