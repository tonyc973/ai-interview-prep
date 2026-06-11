"""Small UI helpers shared across pages (presentation only)."""

from __future__ import annotations

import uuid

from nicegui import context, ui

from app.middleware.auth import current_user_id


def request_ip() -> str | None:
    """Best-effort client IP for login throttling."""
    try:
        request = context.client.request
    except Exception:
        return None
    if request is not None and request.client is not None:
        return request.client.host
    return None


def require_user_id() -> uuid.UUID | None:
    """Return the current user id, redirecting to /login if unauthenticated."""
    user_id = current_user_id()
    if user_id is None:
        ui.navigate.to("/login")
        return None
    return user_id


def notify_error(message: str) -> None:
    ui.notify(message, type="negative", position="top", timeout=5000)


def notify_ok(message: str) -> None:
    ui.notify(message, type="positive", position="top")
