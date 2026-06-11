"""Application entrypoint (NiceGUI).

Loads configuration (failing fast on missing secrets), configures structured
logging, builds the service container, installs the auth gate, registers pages,
and runs migrations on startup. ``/healthz`` checks DB connectivity.
"""

from __future__ import annotations

import os

# Silence CrewAI/OpenTelemetry phone-home before anything imports crewai.
os.environ.setdefault("CREWAI_DISABLE_TELEMETRY", "true")
os.environ.setdefault("OTEL_SDK_DISABLED", "true")

from nicegui import app, ui
from sqlalchemy import text
from starlette.responses import JSONResponse

from app.config import ConfigError, get_settings
from app.container import build_container
from app.db.base import dispose_engine, session_scope
from app.db.bootstrap import init_database
from app.logging import configure_logging, get_logger
from app.middleware.auth import AuthMiddleware
from app.ui import register_pages


def _bootstrap() -> None:
    try:
        settings = get_settings()
    except ConfigError as exc:
        # Fail fast with a readable, secret-free message.
        print(f"\nConfiguration error:\n{exc}\n")
        raise SystemExit(1) from None

    configure_logging(settings.log_level, json_logs=settings.is_production)
    build_container(settings)
    app.add_middleware(AuthMiddleware)
    register_pages()

    log = get_logger("main")

    @app.on_startup
    async def _on_startup() -> None:
        await init_database(settings.database_url)
        log.info("app.started", env=settings.env, port=settings.port)

    @app.on_shutdown
    async def _on_shutdown() -> None:
        await dispose_engine()

    @app.get("/healthz")
    async def _healthz() -> JSONResponse:
        try:
            async with session_scope() as session:
                await session.execute(text("SELECT 1"))
        except Exception:
            return JSONResponse({"status": "error", "db": "down"}, status_code=503)
        return JSONResponse({"status": "ok"})


_bootstrap()


def main() -> None:
    settings = get_settings()
    ui.run(
        host=settings.host,
        port=settings.port,
        title="AI Interview Prep",
        storage_secret=settings.storage_secret.get_secret_value(),
        reload=not settings.is_production,
        show=False,
        favicon="🧠",
    )


if __name__ in {"__main__", "__mp_main__"}:
    main()
