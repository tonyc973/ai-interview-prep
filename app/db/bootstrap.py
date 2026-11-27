"""Database bootstrap for the running app: engine init + Alembic migrations.

Production schema is owned by Alembic. At startup we run ``alembic upgrade head``
(idempotent) so a fresh deployment self-provisions. Tests do NOT use this module;
they create the schema directly from metadata against an in-memory database.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from app.db.base import init_engine
from app.logging import get_logger

_log = get_logger("db.bootstrap")

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _ensure_sqlite_dir(database_url: str) -> None:
    """Create the parent directory for a file-based SQLite DB if needed."""
    prefix = "sqlite+aiosqlite:///"
    if not database_url.startswith(prefix):
        return
    raw_path = database_url[len(prefix) :]
    if not raw_path or ":memory:" in raw_path:
        return
    db_path = Path(raw_path)
    if not db_path.is_absolute():
        # Resolve relative to the project root. Let Path do the joining: it drops
        # a leading ``./`` while preserving ``..`` and dot-prefixed directories.
        # (A naive ``raw_path.lstrip("./")`` strips a *character set*, mangling
        # paths such as ``../data/app.db`` or ``.cfg/app.db``.)
        db_path = PROJECT_ROOT / db_path
    db_path.parent.mkdir(parents=True, exist_ok=True)


def apply_migrations(database_url: str) -> None:
    """Run ``alembic upgrade head`` against ``database_url`` (sync, in a thread)."""
    from alembic import command
    from alembic.config import Config

    cfg = Config(str(PROJECT_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(PROJECT_ROOT / "app" / "db" / "migrations"))
    cfg.set_main_option("sqlalchemy.url", database_url)
    command.upgrade(cfg, "head")


async def init_database(database_url: str) -> None:
    """Initialize the engine and bring the schema up to head."""
    _ensure_sqlite_dir(database_url)
    init_engine(database_url)
    await asyncio.to_thread(apply_migrations, database_url)
    _log.info("db.ready")
