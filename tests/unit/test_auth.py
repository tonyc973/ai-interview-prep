"""Auth service tests: registration, login, generic errors, lockout."""

from __future__ import annotations

import pytest

from app.config import Settings
from app.services.auth import (
    AccountLocked,
    AuthService,
    EmailAlreadyRegistered,
    InvalidCredentials,
    InvalidEmail,
    WeakPassword,
)

STRONG = "tr0ub4dor-galaxy-stew-9173"
EMAIL = "person@example.com"


async def test_register_then_login(settings: Settings, db: None) -> None:
    auth = AuthService(settings)
    user = await auth.register(EMAIL, STRONG)
    assert user.email == EMAIL
    logged_in = await auth.authenticate(EMAIL, STRONG, ip="1.2.3.4")
    assert logged_in.id == user.id


async def test_register_rejects_weak_password(settings: Settings, db: None) -> None:
    auth = AuthService(settings)
    with pytest.raises(WeakPassword):
        await auth.register(EMAIL, "password1234")


async def test_register_rejects_invalid_email(settings: Settings, db: None) -> None:
    auth = AuthService(settings)
    with pytest.raises(InvalidEmail):
        await auth.register("not-an-email", STRONG)


async def test_register_rejects_duplicate(settings: Settings, db: None) -> None:
    auth = AuthService(settings)
    await auth.register(EMAIL, STRONG)
    with pytest.raises(EmailAlreadyRegistered):
        await auth.register(EMAIL.upper(), STRONG)


async def test_wrong_password_is_generic(settings: Settings, db: None) -> None:
    auth = AuthService(settings)
    await auth.register(EMAIL, STRONG)
    with pytest.raises(InvalidCredentials) as exc:
        await auth.authenticate(EMAIL, "the-wrong-password-here", ip="1.2.3.4")
    assert exc.value.user_message == "Invalid email or password."


async def test_unknown_email_is_generic(settings: Settings, db: None) -> None:
    auth = AuthService(settings)
    with pytest.raises(InvalidCredentials) as exc:
        await auth.authenticate("ghost@example.com", STRONG, ip="1.2.3.4")
    assert exc.value.user_message == "Invalid email or password."


async def test_lockout_after_repeated_failures(settings: Settings, db: None) -> None:
    auth = AuthService(settings)  # login_max_failures = 3 in test settings
    await auth.register(EMAIL, STRONG)
    for _ in range(settings.login_max_failures):
        with pytest.raises(InvalidCredentials):
            await auth.authenticate(EMAIL, "nope-nope-nope", ip="9.9.9.9")
    # Now locked — even the correct password is refused.
    with pytest.raises(AccountLocked):
        await auth.authenticate(EMAIL, STRONG, ip="9.9.9.9")


async def test_lockout_remaining_reports_seconds(settings: Settings, db: None) -> None:
    auth = AuthService(settings)
    await auth.register(EMAIL, STRONG)
    for _ in range(settings.login_max_failures):
        with pytest.raises(InvalidCredentials):
            await auth.authenticate(EMAIL, "nope-nope-nope", ip="9.9.9.9")
    remaining = await auth.lockout_remaining(EMAIL, "9.9.9.9")
    assert remaining is not None
    assert remaining > 0


async def test_set_dark_mode(settings: Settings, db: None) -> None:
    auth = AuthService(settings)
    user = await auth.register(EMAIL, STRONG)
    await auth.set_dark_mode(user.id, True)
    refreshed = await auth.get_user(user.id)
    assert refreshed is not None
    assert refreshed.dark_mode is True
