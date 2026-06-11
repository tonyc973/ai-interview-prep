"""Authentication service: registration, login, throttling.

All login-failure paths return the SAME generic error and spend comparable time,
so an attacker cannot tell whether an email exists. Throttling state is persisted
in ``login_attempts`` (not in-memory) and grows exponentially per account and per
IP. Login attempts are committed in their own transaction so they survive the
auth failure that follows.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta

from app.config import Settings
from app.db.base import session_scope, utcnow
from app.db.models import User
from app.db.repositories import LoginAttemptRepository, UserRepository
from app.logging import get_logger
from app.services import security

_log = get_logger("auth")


class AuthError(Exception):
    """Base auth error; ``user_message`` is safe to display."""

    user_message = "Authentication failed."

    def __init__(self, detail: str, *, user_message: str | None = None) -> None:
        super().__init__(detail)
        if user_message is not None:
            self.user_message = user_message


class InvalidCredentials(AuthError):
    user_message = "Invalid email or password."


class AccountLocked(AuthError):
    def __init__(self, retry_after_seconds: float) -> None:
        self.retry_after_seconds = max(1, int(retry_after_seconds))
        mins = (self.retry_after_seconds + 59) // 60
        super().__init__(
            f"account locked for {self.retry_after_seconds}s",
            user_message=(
                f"Too many failed attempts. Try again in about {mins} minute"
                f"{'s' if mins != 1 else ''}."
            ),
        )


class EmailAlreadyRegistered(AuthError):
    user_message = "An account with this email already exists."


class InvalidEmail(AuthError):
    user_message = "Please enter a valid email address."


class WeakPassword(AuthError):
    def __init__(self, strength: security.PasswordStrength) -> None:
        self.strength = strength
        msg = strength.warning or "Password is too weak."
        if strength.suggestions:
            msg = f"{msg} {' '.join(strength.suggestions)}"
        super().__init__("weak password", user_message=msg)


class AuthService:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    # -- registration -------------------------------------------------------
    async def register(self, email: str, password: str) -> User:
        try:
            email_n = security.normalize_email(email)
        except ValueError as exc:
            raise InvalidEmail("invalid email format") from exc

        strength = security.evaluate_password(
            password,
            min_length=self._settings.password_min_length,
            min_score=self._settings.password_min_zxcvbn_score,
            user_inputs=[email_n, email_n.split("@")[0]],
        )
        if not strength.ok:
            raise WeakPassword(strength)

        async with session_scope() as session:
            users = UserRepository(session)
            if await users.get_by_email(email_n) is not None:
                raise EmailAlreadyRegistered("email taken")
            user = await users.create(email=email_n, password_hash=security.hash_password(password))
        _log.info("auth.registered", user_id=str(user.id))
        return user

    # -- authentication -----------------------------------------------------
    async def authenticate(self, email: str, password: str, *, ip: str | None) -> User:
        try:
            email_n = security.normalize_email(email)
        except ValueError as exc:
            await self._record(email.lower(), ip, success=False)
            raise InvalidCredentials("invalid email format") from exc

        remaining = await self.lockout_remaining(email_n, ip)
        if remaining is not None:
            raise AccountLocked(remaining)

        async with session_scope() as session:
            user = await UserRepository(session).get_by_email(email_n)

        if user is None:
            security.verify_dummy(password)
            await self._record(email_n, ip, success=False)
            raise InvalidCredentials("no such user")

        if not user.is_active or not security.verify_password(user.password_hash, password):
            await self._record(email_n, ip, success=False)
            raise InvalidCredentials("bad password or inactive")

        # Success: record it and opportunistically upgrade the hash.
        async with session_scope() as session:
            users = UserRepository(session)
            fresh = await users.get_by_email(email_n)
            if fresh is not None and security.needs_rehash(fresh.password_hash):
                await users.set_password_hash(fresh, security.hash_password(password))
            await LoginAttemptRepository(session).record(email=email_n, ip=ip, success=True)

        _log.info("auth.login_ok", user_id=str(user.id))
        return user

    # -- throttling ---------------------------------------------------------
    async def lockout_remaining(self, email: str, ip: str | None) -> float | None:
        """Seconds remaining on a lockout, or None if not locked."""
        s = self._settings
        now = utcnow()
        horizon = now - timedelta(seconds=s.login_lockout_max_seconds)

        async with session_scope() as session:
            attempts = LoginAttemptRepository(session)
            last_success = await attempts.last_success_at(email)
            account_since = max(last_success, horizon) if last_success else horizon
            account_failures = await attempts.failures_for_email_since(email, account_since)
            ip_failures = await attempts.failures_for_ip_since(ip, horizon) if ip else 0
            failures = max(account_failures, ip_failures)
            if failures < s.login_max_failures:
                return None
            last_fail_email = await attempts.last_failure_at_email(email)
            last_fail_ip = await attempts.last_failure_at_ip(ip) if ip else None

        last_fail = _latest(last_fail_email, last_fail_ip)
        if last_fail is None:
            return None
        overage = failures - s.login_max_failures
        penalty = min(s.login_lockout_base_seconds * (2**overage), s.login_lockout_max_seconds)
        elapsed = (now - last_fail).total_seconds()
        remaining = penalty - elapsed
        return remaining if remaining > 0 else None

    # -- account ------------------------------------------------------------
    async def get_user(self, user_id: uuid.UUID) -> User | None:
        async with session_scope() as session:
            return await UserRepository(session).get_by_id(user_id)

    async def set_dark_mode(self, user_id: uuid.UUID, enabled: bool) -> None:
        async with session_scope() as session:
            users = UserRepository(session)
            user = await users.get_by_id(user_id)
            if user is not None:
                await users.set_dark_mode(user, enabled)

    # -- internal -----------------------------------------------------------
    async def _record(self, email: str, ip: str | None, *, success: bool) -> None:
        async with session_scope() as session:
            await LoginAttemptRepository(session).record(email=email, ip=ip, success=success)


def _latest(a: datetime | None, b: datetime | None) -> datetime | None:
    if a is None:
        return b
    if b is None:
        return a
    return max(a, b)
