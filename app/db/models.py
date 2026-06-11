"""SQLAlchemy ORM models.

Entities: User, PrepSession, Transcript (one row per utterance), EvaluationRow,
UsageRecord, LoginAttempt. Enums are stored as non-native VARCHAR+CHECK so the
schema is identical on SQLite and Postgres. JSON columns hold the dumped Pydantic
output schemas (ResearchBrief / QuestionBank / EvaluationReport).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy import (
    Enum as SAEnum,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, utcnow
from app.domain.enums import (
    InterviewStatus,
    LLMOperation,
    MessageRole,
    SeniorityLevel,
    SessionStatus,
)


def _enum_col(enum_cls: type[StrEnum]) -> SAEnum:
    """Portable string enum column (VARCHAR + CHECK), storing the lowercase value."""
    return SAEnum(
        enum_cls,
        native_enum=False,
        length=32,
        values_callable=lambda e: [member.value for member in e],
        validate_strings=True,
    )


def _uuid_pk() -> Mapped[uuid.UUID]:
    return mapped_column(Uuid, primary_key=True, default=uuid.uuid4)


class User(Base, TimestampMixin):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = _uuid_pk()
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(512), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    dark_mode: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    sessions: Mapped[list[PrepSession]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )


class PrepSession(Base, TimestampMixin):
    __tablename__ = "prep_sessions"

    id: Mapped[uuid.UUID] = _uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )

    target_role: Mapped[str] = mapped_column(String(200), nullable=False)
    target_company: Mapped[str] = mapped_column(String(200), nullable=False)
    seniority: Mapped[SeniorityLevel] = mapped_column(_enum_col(SeniorityLevel), nullable=False)
    job_description: Mapped[str] = mapped_column(Text, nullable=False)
    cv_text: Mapped[str | None] = mapped_column(Text, nullable=True)

    status: Mapped[SessionStatus] = mapped_column(
        _enum_col(SessionStatus), default=SessionStatus.PENDING, index=True, nullable=False
    )
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    research_brief: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    question_bank: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)

    interview_status: Mapped[InterviewStatus] = mapped_column(
        _enum_col(InterviewStatus), default=InterviewStatus.NOT_STARTED, nullable=False
    )
    interview_total_questions: Mapped[int] = mapped_column(Integer, default=8, nullable=False)
    interview_current_index: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    user: Mapped[User] = relationship(back_populates="sessions")
    turns: Mapped[list[Transcript]] = relationship(
        back_populates="session",
        cascade="all, delete-orphan",
        order_by="Transcript.turn_index",
    )
    report: Mapped[EvaluationRow | None] = relationship(
        back_populates="session", cascade="all, delete-orphan", uselist=False
    )


class Transcript(Base):
    """One utterance in a mock interview (interviewer, candidate, or system)."""

    __tablename__ = "transcript_turns"
    __table_args__ = (UniqueConstraint("session_id", "turn_index"),)

    id: Mapped[uuid.UUID] = _uuid_pk()
    session_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("prep_sessions.id", ondelete="CASCADE"), index=True, nullable=False
    )
    turn_index: Mapped[int] = mapped_column(Integer, nullable=False)
    role: Mapped[MessageRole] = mapped_column(_enum_col(MessageRole), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    question_index: Mapped[int | None] = mapped_column(Integer, nullable=True)
    competency: Mapped[str | None] = mapped_column(String(200), nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=utcnow, nullable=False)

    session: Mapped[PrepSession] = relationship(back_populates="turns")


class EvaluationRow(Base):
    """Persisted EvaluationReport, one per session."""

    __tablename__ = "evaluation_reports"

    id: Mapped[uuid.UUID] = _uuid_pk()
    session_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("prep_sessions.id", ondelete="CASCADE"),
        unique=True,
        index=True,
        nullable=False,
    )
    overall_score: Mapped[float] = mapped_column(Float, nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    report: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(default=utcnow, nullable=False)

    session: Mapped[PrepSession] = relationship(back_populates="report")


class UsageRecord(Base):
    """One row per LLM call: tokens, cost, latency. Drives caps + accounting."""

    __tablename__ = "usage_records"

    id: Mapped[uuid.UUID] = _uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    session_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("prep_sessions.id", ondelete="SET NULL"), index=True, nullable=True
    )
    operation: Mapped[LLMOperation] = mapped_column(
        _enum_col(LLMOperation), index=True, nullable=False
    )
    agent_name: Mapped[str | None] = mapped_column(String(64), nullable=True)
    model: Mapped[str] = mapped_column(String(128), nullable=False)
    prompt_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    completion_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    total_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    cost_usd: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    latency_ms: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    success: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(default=utcnow, index=True, nullable=False)


class LoginAttempt(Base):
    """Persisted login attempt for per-account and per-IP throttling."""

    __tablename__ = "login_attempts"

    id: Mapped[uuid.UUID] = _uuid_pk()
    email: Mapped[str] = mapped_column(String(320), index=True, nullable=False)
    ip: Mapped[str | None] = mapped_column(String(64), index=True, nullable=True)
    success: Mapped[bool] = mapped_column(Boolean, nullable=False)
    created_at: Mapped[datetime] = mapped_column(default=utcnow, index=True, nullable=False)
