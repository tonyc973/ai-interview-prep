"""Composition root: builds the gateway and services once and shares them.

The UI and entrypoint resolve everything through :func:`get_container`. Tests
build a container with a fake gateway so they never hit OpenAI.
"""

from __future__ import annotations

from app.agents.gateway import LLMGateway
from app.config import Settings, get_settings
from app.services.auth import AuthService
from app.services.interview_service import InterviewService
from app.services.session_service import SessionService
from app.services.usage_service import UsageService


class Container:
    """Holds the singletons for one running app (or one test)."""

    def __init__(self, settings: Settings, *, gateway: LLMGateway | None = None) -> None:
        self.settings = settings
        self.gateway = gateway if gateway is not None else LLMGateway(settings)
        self.usage = UsageService(settings)
        self.auth = AuthService(settings)
        self.sessions = SessionService(settings, self.gateway, self.usage)
        self.interviews = InterviewService(settings, self.gateway, self.usage)


_container: Container | None = None


def build_container(
    settings: Settings | None = None, *, gateway: LLMGateway | None = None
) -> Container:
    """Build and install the process-wide container."""
    global _container
    _container = Container(settings or get_settings(), gateway=gateway)
    return _container


def get_container() -> Container:
    if _container is None:
        raise RuntimeError("Container not initialized; call build_container() at startup.")
    return _container
