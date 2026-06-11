"""NiceGUI auth gate + session helpers.

A Starlette middleware redirects unauthenticated requests to ``/login`` (carrying
``redirect_to``), leaving public paths and NiceGUI's own internal routes open.
Authentication state lives in NiceGUI's signed ``app.storage.user``. On login we
clear prior storage and mint a fresh session token (session-fixation mitigation;
see SECURITY.md). NiceGUI manages the underlying cookie.
"""

from __future__ import annotations

import secrets
import uuid
from typing import TYPE_CHECKING

from nicegui import app
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import RedirectResponse, Response

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from starlette.requests import Request

from app.db.models import User

PUBLIC_PATHS = frozenset({"/login", "/register", "/healthz"})
_AUTH_KEY = "auth"


class AuthMiddleware(BaseHTTPMiddleware):
    """Redirect unauthenticated users to the login page."""

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        path = request.url.path
        if _is_public(path):
            return await call_next(request)
        if not _is_authenticated():
            target = path if path != "/" else ""
            suffix = f"?redirect_to={target}" if target else ""
            return RedirectResponse(f"/login{suffix}")
        return await call_next(request)


def _is_public(path: str) -> bool:
    if path in PUBLIC_PATHS:
        return True
    # NiceGUI internals + static assets must always pass through.
    return path.startswith(("/_nicegui", "/static", "/favicon"))


def _is_authenticated() -> bool:
    try:
        return bool(app.storage.user.get(_AUTH_KEY))
    except Exception:
        return False


def login_user(user: User) -> None:
    """Establish an authenticated session, rotating session identity."""
    app.storage.user.clear()
    app.storage.user[_AUTH_KEY] = {
        "user_id": str(user.id),
        "email": user.email,
        "token": secrets.token_urlsafe(32),
    }
    app.storage.user["dark_mode"] = bool(user.dark_mode)


def logout_user() -> None:
    """Invalidate the current session."""
    app.storage.user.clear()


def current_user_id() -> uuid.UUID | None:
    auth = _auth()
    if not auth:
        return None
    try:
        return uuid.UUID(str(auth["user_id"]))
    except (KeyError, ValueError):
        return None


def current_user_email() -> str | None:
    auth = _auth()
    return str(auth["email"]) if auth and "email" in auth else None


def _auth() -> dict[str, str] | None:
    try:
        value = app.storage.user.get(_AUTH_KEY)
    except Exception:
        return None
    return value if isinstance(value, dict) else None
