"""Tests for the usage/cost service (DB seeding + persistence + caps)."""

from __future__ import annotations

import uuid

import pytest

from app.agents.gateway import CostLimitExceeded
from app.config import Settings
from app.db.base import session_scope
from app.db.repositories import (
    SessionRepository,
    UsageEntry,
    UsageRepository,
    UserRepository,
)
from app.domain.enums import LLMOperation, SeniorityLevel
from app.services import security
from app.services.usage_service import UsageService
from tests.conftest import make_settings


async def _seed_user_and_session() -> tuple[uuid.UUID, uuid.UUID]:
    async with session_scope() as session:
        user = await UserRepository(session).create(
            email="u@example.com", password_hash=security.hash_password("x" * 14)
        )
        prep = await SessionRepository(session).create(
            user_id=user.id,
            target_role="r",
            target_company="c",
            seniority=SeniorityLevel.MID,
            job_description="jd",
            cv_text=None,
            interview_total_questions=3,
        )
        return user.id, prep.id


def _entry(user_id: uuid.UUID, session_id: uuid.UUID, cost: float) -> UsageEntry:
    return UsageEntry(
        user_id=user_id,
        session_id=session_id,
        operation=LLMOperation.RESEARCH,
        agent_name="a",
        model="gpt-4o-mini",
        prompt_tokens=10,
        completion_tokens=10,
        total_tokens=20,
        cost_usd=cost,
        latency_ms=1,
        success=True,
    )


async def test_new_ledger_seeds_from_db(settings: Settings, db: None) -> None:
    user_id, session_id = await _seed_user_and_session()
    async with session_scope() as session:
        await UsageRepository(session).add(_entry(user_id, session_id, 0.02))
    ledger = await UsageService(settings).new_ledger(user_id=user_id, session_id=session_id)
    assert ledger.session_spend_seed == pytest.approx(0.02)
    assert ledger.user_day_spend_seed == pytest.approx(0.02)


async def test_persist_then_costs(settings: Settings, db: None) -> None:
    user_id, session_id = await _seed_user_and_session()
    usage = UsageService(settings)
    ledger = await usage.new_ledger(user_id=user_id, session_id=session_id)
    ledger.record(_entry(user_id, session_id, 0.01))
    await usage.persist(ledger)
    assert await usage.session_cost(session_id) == pytest.approx(0.01)
    assert await usage.user_daily_cost(user_id) == pytest.approx(0.01)


async def test_assert_within_caps_raises_when_over(db: None) -> None:
    user_id, session_id = await _seed_user_and_session()
    async with session_scope() as session:
        await UsageRepository(session).add(_entry(user_id, session_id, 0.02))
    tiny = make_settings(max_cost_per_user_per_day_usd=0.001)
    with pytest.raises(CostLimitExceeded):
        await UsageService(tiny).assert_within_caps(user_id=user_id, session_id=session_id)
