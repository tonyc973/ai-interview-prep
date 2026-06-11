"""Repositories: the only place that builds SQL. Services depend on these.

Each repository wraps an :class:`AsyncSession`. Methods return ORM objects or
plain scalars; they never contain business rules (those live in services).
Flushing (not committing) is done where an id is needed immediately; the
surrounding ``session_scope`` owns the commit/rollback.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    EvaluationRow,
    LoginAttempt,
    PrepSession,
    Transcript,
    UsageRecord,
    User,
)
from app.domain.enums import (
    InterviewStatus,
    LLMOperation,
    MessageRole,
    SeniorityLevel,
    SessionStatus,
)


# --------------------------------------------------------------------------- #
# Users
# --------------------------------------------------------------------------- #
class UserRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, *, email: str, password_hash: str) -> User:
        user = User(email=email, password_hash=password_hash)
        self._session.add(user)
        await self._session.flush()
        return user

    async def get_by_id(self, user_id: uuid.UUID) -> User | None:
        return await self._session.get(User, user_id)

    async def get_by_email(self, email: str) -> User | None:
        stmt = select(User).where(User.email == email.lower())
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def set_password_hash(self, user: User, password_hash: str) -> None:
        user.password_hash = password_hash
        await self._session.flush()

    async def set_dark_mode(self, user: User, enabled: bool) -> None:
        user.dark_mode = enabled
        await self._session.flush()


# --------------------------------------------------------------------------- #
# Prep sessions
# --------------------------------------------------------------------------- #
class SessionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(
        self,
        *,
        user_id: uuid.UUID,
        target_role: str,
        target_company: str,
        seniority: SeniorityLevel,
        job_description: str,
        cv_text: str | None,
        interview_total_questions: int,
    ) -> PrepSession:
        prep = PrepSession(
            user_id=user_id,
            target_role=target_role,
            target_company=target_company,
            seniority=seniority,
            job_description=job_description,
            cv_text=cv_text,
            status=SessionStatus.PENDING,
            interview_status=InterviewStatus.NOT_STARTED,
            interview_total_questions=interview_total_questions,
        )
        self._session.add(prep)
        await self._session.flush()
        return prep

    async def get(self, session_id: uuid.UUID) -> PrepSession | None:
        return await self._session.get(PrepSession, session_id)

    async def get_owned(self, session_id: uuid.UUID, user_id: uuid.UUID) -> PrepSession | None:
        prep = await self._session.get(PrepSession, session_id)
        if prep is None or prep.user_id != user_id:
            return None
        return prep

    async def list_for_user(self, user_id: uuid.UUID) -> list[PrepSession]:
        stmt = (
            select(PrepSession)
            .where(PrepSession.user_id == user_id)
            .order_by(PrepSession.created_at.desc())
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())


# --------------------------------------------------------------------------- #
# Transcript turns
# --------------------------------------------------------------------------- #
class TranscriptRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add_turn(
        self,
        *,
        session_id: uuid.UUID,
        turn_index: int,
        role: MessageRole,
        content: str,
        question_index: int | None = None,
        competency: str | None = None,
    ) -> Transcript:
        turn = Transcript(
            session_id=session_id,
            turn_index=turn_index,
            role=role,
            content=content,
            question_index=question_index,
            competency=competency,
        )
        self._session.add(turn)
        await self._session.flush()
        return turn

    async def list_for_session(self, session_id: uuid.UUID) -> list[Transcript]:
        stmt = (
            select(Transcript)
            .where(Transcript.session_id == session_id)
            .order_by(Transcript.turn_index)
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def next_turn_index(self, session_id: uuid.UUID) -> int:
        stmt = select(func.max(Transcript.turn_index)).where(Transcript.session_id == session_id)
        result = await self._session.execute(stmt)
        current = result.scalar_one_or_none()
        return 0 if current is None else current + 1


# --------------------------------------------------------------------------- #
# Evaluation reports
# --------------------------------------------------------------------------- #
class ReportRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_for_session(self, session_id: uuid.UUID) -> EvaluationRow | None:
        stmt = select(EvaluationRow).where(EvaluationRow.session_id == session_id)
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def upsert(
        self,
        *,
        session_id: uuid.UUID,
        overall_score: float,
        summary: str,
        report: dict[str, object],
    ) -> EvaluationRow:
        existing = await self.get_for_session(session_id)
        if existing is not None:
            existing.overall_score = overall_score
            existing.summary = summary
            existing.report = report
            await self._session.flush()
            return existing
        row = EvaluationRow(
            session_id=session_id,
            overall_score=overall_score,
            summary=summary,
            report=report,
        )
        self._session.add(row)
        await self._session.flush()
        return row


# --------------------------------------------------------------------------- #
# Usage / cost accounting
# --------------------------------------------------------------------------- #
@dataclass(frozen=True, slots=True)
class UsageEntry:
    """A single LLM-call usage record to persist (gateway -> repository)."""

    user_id: uuid.UUID
    session_id: uuid.UUID | None
    operation: LLMOperation
    agent_name: str | None
    model: str
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    cost_usd: float
    latency_ms: int
    success: bool


class UsageRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, entry: UsageEntry) -> UsageRecord:
        record = UsageRecord(
            user_id=entry.user_id,
            session_id=entry.session_id,
            operation=entry.operation,
            agent_name=entry.agent_name,
            model=entry.model,
            prompt_tokens=entry.prompt_tokens,
            completion_tokens=entry.completion_tokens,
            total_tokens=entry.total_tokens,
            cost_usd=entry.cost_usd,
            latency_ms=entry.latency_ms,
            success=entry.success,
        )
        self._session.add(record)
        await self._session.flush()
        return record

    async def add_many(self, entries: Sequence[UsageEntry]) -> None:
        for entry in entries:
            await self.add(entry)

    async def session_cost(self, session_id: uuid.UUID) -> float:
        stmt = select(func.coalesce(func.sum(UsageRecord.cost_usd), 0.0)).where(
            UsageRecord.session_id == session_id
        )
        result = await self._session.execute(stmt)
        return float(result.scalar_one())

    async def user_cost_since(self, user_id: uuid.UUID, since: datetime) -> float:
        stmt = select(func.coalesce(func.sum(UsageRecord.cost_usd), 0.0)).where(
            UsageRecord.user_id == user_id,
            UsageRecord.created_at >= since,
        )
        result = await self._session.execute(stmt)
        return float(result.scalar_one())


# --------------------------------------------------------------------------- #
# Login attempts (throttling)
# --------------------------------------------------------------------------- #
class LoginAttemptRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def record(self, *, email: str, ip: str | None, success: bool) -> None:
        attempt = LoginAttempt(email=email.lower(), ip=ip, success=success)
        self._session.add(attempt)
        await self._session.flush()

    async def failures_for_email_since(self, email: str, since: datetime) -> int:
        stmt = select(func.count(LoginAttempt.id)).where(
            LoginAttempt.email == email.lower(),
            LoginAttempt.success.is_(False),
            LoginAttempt.created_at >= since,
        )
        result = await self._session.execute(stmt)
        return int(result.scalar_one())

    async def failures_for_ip_since(self, ip: str, since: datetime) -> int:
        stmt = select(func.count(LoginAttempt.id)).where(
            LoginAttempt.ip == ip,
            LoginAttempt.success.is_(False),
            LoginAttempt.created_at >= since,
        )
        result = await self._session.execute(stmt)
        return int(result.scalar_one())

    async def last_success_at(self, email: str) -> datetime | None:
        stmt = (
            select(LoginAttempt.created_at)
            .where(
                LoginAttempt.email == email.lower(),
                LoginAttempt.success.is_(True),
            )
            .order_by(LoginAttempt.created_at.desc())
            .limit(1)
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def last_failure_at_email(self, email: str) -> datetime | None:
        stmt = (
            select(LoginAttempt.created_at)
            .where(
                LoginAttempt.email == email.lower(),
                LoginAttempt.success.is_(False),
            )
            .order_by(LoginAttempt.created_at.desc())
            .limit(1)
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def last_failure_at_ip(self, ip: str) -> datetime | None:
        stmt = (
            select(LoginAttempt.created_at)
            .where(
                LoginAttempt.ip == ip,
                LoginAttempt.success.is_(False),
            )
            .order_by(LoginAttempt.created_at.desc())
            .limit(1)
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()
