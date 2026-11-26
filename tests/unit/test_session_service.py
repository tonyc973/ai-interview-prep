"""Unit tests for SessionService: input validation, ownership isolation, and the
pipeline's failure-handling invariants.

The happy path (create -> research -> questions -> READY) is exercised by the
full lifecycle integration test. These tests lock in the behaviours that are
easy to regress and costly if broken: failures must move a session to FAILED
with a *user-safe* message that never leaks internals, a pre-exhausted cost cap
must refuse before any LLM work happens, and a user may only read their own
sessions.
"""

from __future__ import annotations

import uuid

import pytest

from app.db.base import session_scope
from app.db.models import User
from app.db.repositories import UsageEntry, UsageRepository, UserRepository
from app.domain.enums import LLMOperation, SeniorityLevel, SessionStatus
from app.services import security
from app.services.session_service import SessionInputError, SessionService
from app.services.usage_service import UsageService
from tests.conftest import make_settings
from tests.fakes import FakeGateway

_JD = "Build and operate scalable Python backend services. Strong on system design."


def _service(**setting_overrides: float) -> tuple[SessionService, FakeGateway]:
    settings = make_settings(**setting_overrides)
    fake = FakeGateway()
    return SessionService(settings, fake, UsageService(settings)), fake


async def _create(service: SessionService, user: User, *, cv_text: str | None = None) -> uuid.UUID:
    prep = await service.create_session(
        user_id=user.id,
        target_role="Backend Engineer",
        target_company="Acme",
        seniority=SeniorityLevel.MID,
        job_description=_JD,
        cv_text=cv_text,
    )
    return prep.id


async def test_create_session_rejects_overlong_cv(user: User) -> None:
    service, _ = _service(max_cv_chars=10)
    with pytest.raises(SessionInputError) as excinfo:
        await service.create_session(
            user_id=user.id,
            target_role="Backend Engineer",
            target_company="Acme",
            seniority=SeniorityLevel.MID,
            job_description=_JD,
            cv_text="x" * 11,
        )
    assert excinfo.value.field == "cv_text"


async def test_pipeline_unexpected_error_marks_failed_without_leaking_internals(
    user: User, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A non-gateway crash must fail the session with a generic message only.

    The internal exception text (which could carry secrets or stack detail) must
    never reach the user-facing ``error_message``.
    """
    service, _ = _service()
    session_id = await _create(service, user)

    secret = "connect postgres://admin:hunter2@db internal-detail"

    def _boom(**_kwargs: object) -> object:
        raise RuntimeError(secret)

    monkeypatch.setattr("app.services.session_service.run_research_stage", _boom)

    await service.run_pipeline(session_id)

    failed = await service.get_session(session_id, user.id)
    assert failed is not None
    assert failed.status == SessionStatus.FAILED
    assert failed.error_message == "Preparation failed unexpectedly. Please try again."
    assert "hunter2" not in (failed.error_message or "")


async def test_pipeline_surfaces_gateway_user_message_on_failure(
    user: User, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A GatewayError's user-safe message (not its raw detail) is shown to the user."""
    from app.agents.gateway import GatewayError

    service, _ = _service()
    session_id = await _create(service, user)

    def _boom(**_kwargs: object) -> object:
        raise GatewayError("raw internal detail", user_message="The AI service is busy. Retry.")

    monkeypatch.setattr("app.services.session_service.run_research_stage", _boom)

    await service.run_pipeline(session_id)

    failed = await service.get_session(session_id, user.id)
    assert failed is not None
    assert failed.status == SessionStatus.FAILED
    assert failed.error_message == "The AI service is busy. Retry."


async def test_pipeline_rejects_when_session_cap_already_reached(user: User) -> None:
    """If persisted spend already meets the cap, the pipeline fails up front and
    performs no LLM work at all."""
    service, fake = _service(max_cost_per_session_usd=0.01)
    session_id = await _create(service, user)

    # Seed persisted spend at/over the cap for this session.
    async with session_scope() as session:
        await UsageRepository(session).add(
            UsageEntry(
                user_id=user.id,
                session_id=session_id,
                operation=LLMOperation.RESEARCH,
                agent_name="role_researcher",
                model="gpt-4o-mini",
                prompt_tokens=100,
                completion_tokens=100,
                total_tokens=200,
                cost_usd=0.02,
                latency_ms=1,
                success=True,
            )
        )

    await service.run_pipeline(session_id)

    failed = await service.get_session(session_id, user.id)
    assert failed is not None
    assert failed.status == SessionStatus.FAILED
    assert failed.error_message  # a user-safe cost-cap message
    assert fake.calls == []  # no interviewer/researcher calls were attempted


async def test_run_pipeline_noops_for_unknown_session(user: User) -> None:
    service, fake = _service()
    await service.run_pipeline(uuid.uuid4())  # must not raise
    assert fake.calls == []


async def test_get_session_enforces_ownership(user: User) -> None:
    service, _ = _service()
    session_id = await _create(service, user)

    async with session_scope() as session:
        other = await UserRepository(session).create(
            email="intruder@example.com",
            password_hash=security.hash_password("correct horse battery staple"),
        )

    assert await service.get_session(session_id, other.id) is None
    assert await service.get_session(session_id, user.id) is not None


async def test_list_sessions_returns_newest_first(user: User) -> None:
    service, _ = _service()
    first = await _create(service, user)
    second = await _create(service, user)

    listed = await service.list_sessions(user.id)
    assert [s.id for s in listed] == [second, first]


async def test_parse_helpers_return_none_when_unpopulated(user: User) -> None:
    service, _ = _service()
    session_id = await _create(service, user)
    prep = await service.get_session(session_id, user.id)
    assert prep is not None
    assert service.parse_brief(prep) is None
    assert service.parse_questions(prep) is None
