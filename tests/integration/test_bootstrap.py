"""The bootstrap path runs real Alembic migrations to provision the schema."""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import text

from app.db.base import dispose_engine, session_scope
from app.db.bootstrap import init_database


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
