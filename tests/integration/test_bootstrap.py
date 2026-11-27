"""The bootstrap path runs real Alembic migrations to provision the schema."""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import text

from app.db import bootstrap
from app.db.base import dispose_engine, session_scope
from app.db.bootstrap import init_database


def test_ensure_sqlite_dir_preserves_dotted_relative_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A relative SQLite path is resolved under the project root verbatim.

    Regression: a leading-dot directory (``.var``) must survive. A naive
    ``lstrip("./")`` strips the dot and provisions the wrong directory, so the
    engine later fails to open the DB file.
    """
    monkeypatch.setattr(bootstrap, "PROJECT_ROOT", tmp_path)
    bootstrap._ensure_sqlite_dir("sqlite+aiosqlite:///.var/data/app.db")
    assert (tmp_path / ".var" / "data").is_dir()
    assert not (tmp_path / "var" / "data").exists()


def test_ensure_sqlite_dir_resolves_dot_slash_prefix(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The default ``./data/app.db`` form still resolves under the project root."""
    monkeypatch.setattr(bootstrap, "PROJECT_ROOT", tmp_path)
    bootstrap._ensure_sqlite_dir("sqlite+aiosqlite:///./data/app.db")
    assert (tmp_path / "data").is_dir()


def test_ensure_sqlite_dir_noop_for_memory_and_non_sqlite(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """In-memory and non-SQLite URLs create nothing on disk."""
    monkeypatch.setattr(bootstrap, "PROJECT_ROOT", tmp_path)
    bootstrap._ensure_sqlite_dir("sqlite+aiosqlite:///:memory:")
    bootstrap._ensure_sqlite_dir("postgresql+asyncpg://user:pass@host:5432/db")
    assert list(tmp_path.iterdir()) == []


async def test_init_database_applies_migrations(tmp_path: Path) -> None:
    url = f"sqlite+aiosqlite:///{tmp_path / 'app.db'}"
    await init_database(url)
    try:
        async with session_scope() as session:
            result = await session.execute(
                text("SELECT name FROM sqlite_master WHERE type='table'")
            )
            tables = {row[0] for row in result}
        assert {"users", "prep_sessions", "usage_records", "alembic_version"} <= tables
    finally:
        await dispose_engine()
