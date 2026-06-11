"""Shared pytest fixtures. Tests run against an in-memory SQLite DB and a fake
LLM gateway — they never touch OpenAI or the real configured database.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from typing import Any

import pytest
import pytest_asyncio

# Keep CrewAI quiet/offline during tests.
os.environ.setdefault("CREWAI_DISABLE_TELEMETRY", "true")
os.environ.setdefault("OTEL_SDK_DISABLED", "true")
os.environ.setdefault("CREWAI_TRACING_ENABLED", "false")

from app.config import Settings
from app.container import Container, build_container
from app.db.base import create_all, dispose_engine, init_engine, session_scope
from app.db.models import User
from app.db.repositories import UserRepository
from app.services import security
from tests.fakes import FakeGateway


def make_settings(**overrides: Any) -> Settings:
    base: dict[str, Any] = {
        "openai_api_key": "sk-test-not-a-real-key",
        "storage_secret": "t" * 48,
        "database_url": "sqlite+aiosqlite:///:memory:",
        "env": "test",
        "openai_max_retries": 2,
        "interview_default_questions": 3,
        "max_cost_per_session_usd": 0.50,
        "max_cost_per_user_per_day_usd": 5.00,
        "password_min_length": 12,
        "password_min_zxcvbn_score": 3,
        "login_max_failures": 3,
        "login_lockout_base_seconds": 2,
        "login_lockout_max_seconds": 60,
    }
    base.update(overrides)
    return Settings(**base)


@pytest.fixture
def settings() -> Settings:
    return make_settings()


@pytest_asyncio.fixture
async def db(settings: Settings) -> AsyncIterator[None]:
    init_engine(settings.database_url)
    await create_all()
    try:
        yield
    finally:
        await dispose_engine()


@pytest.fixture
def fake_gateway() -> FakeGateway:
    return FakeGateway()


@pytest.fixture
def container(settings: Settings, fake_gateway: FakeGateway, db: None) -> Container:
    return build_container(settings, gateway=fake_gateway)


@pytest_asyncio.fixture
async def user(db: None) -> User:
    async with session_scope() as session:
        return await UserRepository(session).create(
            email="candidate@example.com",
            password_hash=security.hash_password("correct horse battery staple"),
        )
