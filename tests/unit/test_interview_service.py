"""Edge-case / guard-rail tests for the interview service."""

from __future__ import annotations

import uuid

import pytest

from app.agents.schemas import EvaluationReport
from app.container import Container
from app.db.models import User
from app.domain.enums import InterviewStatus, SeniorityLevel
from app.services.interview_service import InterviewStateError
from tests.fakes import FakeGateway


async def _ready_session(container: Container, user: User) -> uuid.UUID:
    prep = await container.sessions.create_session(
        user_id=user.id,
        target_role="Backend Engineer",
        target_company="Acme",
        seniority=SeniorityLevel.MID,
        job_description="Build scalable services in Python.",
        cv_text=None,
    )
    await container.sessions.run_pipeline(prep.id)
    return prep.id


async def test_start_rejects_not_ready_session(container: Container, user: User) -> None:
    prep = await container.sessions.create_session(
        user_id=user.id,
        target_role="r",
        target_company="c",
        seniority=SeniorityLevel.MID,
        job_description="jd here long enough",
        cv_text=None,
    )  # still PENDING, no question bank
    with pytest.raises(InterviewStateError):
        await container.interviews.start(prep.id, user.id)


async def test_get_state_none_for_unknown(container: Container, user: User) -> None:
    assert await container.interviews.get_state(uuid.uuid4(), user.id) is None


async def test_get_report_none_before_eval(container: Container, user: User) -> None:
    session_id = await _ready_session(container, user)
    assert await container.interviews.get_report(session_id, user.id) is None


async def test_evaluate_before_complete_raises(container: Container, user: User) -> None:
    session_id = await _ready_session(container, user)
    await container.interviews.start(session_id, user.id)  # IN_PROGRESS, not finished
    with pytest.raises(InterviewStateError):
        await container.interviews.evaluate(session_id, user.id)


async def test_start_is_idempotent(container: Container, user: User) -> None:
    session_id = await _ready_session(container, user)
    first = await container.interviews.start(session_id, user.id)
    again = await container.interviews.start(session_id, user.id)
    # No duplicate first question; same number of interviewer turns.
    assert again.asked_questions == first.asked_questions


async def test_submit_empty_answer_rejected(container: Container, user: User) -> None:
    session_id = await _ready_session(container, user)
    await container.interviews.start(session_id, user.id)
    with pytest.raises(InterviewStateError):
        await container.interviews.submit_answer(session_id, user.id, "   ")


async def test_evaluate_failure_rolls_back_to_completed(
    container: Container, user: User, fake_gateway: FakeGateway
) -> None:
    """A failing evaluator call must leave the session re-evaluable.

    The interview is rolled back from EVALUATING to COMPLETED and no partial
    report is persisted, so the user can simply retry rather than being stranded.
    """
    session_id = await _ready_session(container, user)
    state = await container.interviews.start(session_id, user.id)
    for _ in range(state.total_questions):
        state = await container.interviews.submit_answer(session_id, user.id, "An answer.")
    assert state.status == InterviewStatus.COMPLETED

    def _boom() -> EvaluationReport:
        raise RuntimeError("evaluator exploded")

    fake_gateway.overrides[EvaluationReport] = _boom

    with pytest.raises(RuntimeError, match="evaluator exploded"):
        await container.interviews.evaluate(session_id, user.id)

    after = await container.interviews.get_state(session_id, user.id)
    assert after is not None
    assert after.status == InterviewStatus.COMPLETED
    assert await container.interviews.get_report(session_id, user.id) is None
