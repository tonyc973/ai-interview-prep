# syntax=docker/dockerfile:1

# ---- Builder: resolve + install locked deps into a venv ----
FROM python:3.12-slim-bookworm AS builder

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/app/.venv

WORKDIR /app

# Project metadata + source needed for the editable build during `uv sync`.
COPY pyproject.toml uv.lock README.md ./
COPY app ./app

# Production deps only (no dev group), exactly as locked.
# (No BuildKit cache mount, so this builds on the legacy builder too.)
RUN uv sync --frozen --no-dev


# ---- Runtime: slim, non-root ----
FROM python:3.12-slim-bookworm AS runtime

RUN useradd --create-home --uid 10001 appuser

WORKDIR /app

COPY --from=builder /app/.venv /app/.venv
COPY app ./app
COPY alembic.ini ./

RUN mkdir -p /app/data && chown -R appuser:appuser /app

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    APP_ENV=production \
    APP_HOST=0.0.0.0 \
    APP_PORT=8080

USER appuser
EXPOSE 8080

# Health check hits the public /healthz endpoint (DB connectivity).
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8080/healthz').status==200 else 1)" || exit 1

# app.main runs `alembic upgrade head` on startup, then serves.
CMD ["python", "-m", "app.main"]
