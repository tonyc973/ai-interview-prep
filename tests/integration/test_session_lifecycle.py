"""Full lifecycle integration test: create -> prep pipeline (real CrewAI crew
driven by the fake gateway) -> live interview -> evaluation. No network."""

from __future__ import annotations

import pytest

from app.agents.schemas import EvaluationReport
from app.container import Container
from app.db.models import User
from app.domain.enums import InterviewStatus, SeniorityLevel, SessionStatus
from app.services.session_service import SessionInputError, SessionService
from app.services.usage_service import UsageService
from tests.conftest import make_settings
from tests.fakes import FakeGateway

_JD = "Build and operate scalable Python backend services. Strong on system design."


async def test_full_session_to_report(container: Container, user: User) -> None:
    # 1. Create the prep session.
    prep = await container.sessions.create_session(
        user_id=user.id,
        target_role="Backend Engineer",
        target_company="Acme",
        seniority=SeniorityLevel.SENIOR,
        job_description=_JD,
        cv_text="Five years of Python and distributed systems.",
    )
    assert prep.status == SessionStatus.PENDING

    # 2. Run the research -> questions pipeline (real crew + fake LLM).
    await container.sessions.run_pipeline(prep.id)
    ready = await container.sessions.get_session(prep.id, user.id)
    assert ready is not None
    assert ready.status == SessionStatus.READY
    assert container.sessions.parse_brief(ready) is not None
    questions = container.sessions.parse_questions(ready)
    assert questions is not None and questions.technical

    # Usage was recorded for the two pipeline calls.
    assert await container.usage.session_cost(prep.id) > 0

    # 3. Live interview: first question is asked on start.
    state = await container.interviews.start(prep.id, user.id)
    assert state.status == InterviewStatus.IN_PROGRESS
    assert state.awaiting_answer
    assert len(state.turns) == 1
    assert "Question 1 of" in state.progress_label

    # 4. Answer every question.
    for _ in range(state.total_questions):
        state = await container.interviews.submit_answer(
            prep.id, user.id, "I designed a sharded, multi-tenant service."
        )
    assert state.finished
    assert state.status == InterviewStatus.COMPLETED
    # interviewer turns == total questions; candidate turns == total questions
    interviewer_turns = [t for t in state.turns if t.role.value == "interviewer"]
    assert len(interviewer_turns) == state.total_questions

    # 5. Evaluate.
    report = await container.interviews.evaluate(prep.id, user.id)
    assert isinstance(report, EvaluationReport)
    assert report.competency_scores

    persisted = await container.interviews.get_report(prep.id, user.id)
    assert persisted is not None
    final = await container.sessions.get_session(prep.id, user.id)
    assert final is not None
    assert final.interview_status == InterviewStatus.EVALUATED


async def test_pipeline_marks_failed_when_cost_cap_exceeded(user: User, db: None) -> None:
    # A session cap below one call's cost forces a failure mid-pipeline.
    settings = make_settings(max_cost_per_session_usd=0.0001)
    fake = FakeGateway(cost_per_call=0.001)
    usage = UsageService(settings)
    sessions = SessionService(settings, fake, usage)

    prep = await sessions.create_session(
        user_id=user.id,
        target_role="Backend Engineer",
        target_company="Acme",
        seniority=SeniorityLevel.MID,
        job_description=_JD,
        cv_text=None,
    )
    await sessions.run_pipeline(prep.id)
    failed = await sessions.get_session(prep.id, user.id)
    assert failed is not None
    assert failed.status == SessionStatus.FAILED
    assert failed.error_message


async def test_create_session_validation(container: Container, user: User) -> None:
    with pytest.raises(SessionInputError):
        await container.sessions.create_session(
            user_id=user.id,
            target_role="",
            target_company="Acme",
            seniority=SeniorityLevel.MID,
            job_description=_JD,
            cv_text=None,
        )
