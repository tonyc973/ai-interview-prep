"""Auth service tests: registration, login, generic errors, lockout."""

from __future__ import annotations

import pytest
from argon2 import PasswordHasher

from app.config import Settings
from app.db.base import session_scope
from app.db.repositories import UserRepository
from app.services import security
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


async def test_login_upgrades_outdated_password_hash(settings: Settings, db: None) -> None:
    """A correct login transparently re-hashes credentials stored with weaker,
    outdated argon2 parameters (the opportunistic upgrade in authenticate)."""
    auth = AuthService(settings)
    user = await auth.register(EMAIL, STRONG)

    # Overwrite the stored hash with one made using deliberately weak parameters,
    # which the current (default) hasher must flag as needing a rehash.
    weak_hash = PasswordHasher(time_cost=1, memory_cost=8, parallelism=1).hash(STRONG)
    assert security.needs_rehash(weak_hash)  # precondition
    async with session_scope() as session:
        users = UserRepository(session)
        stored = await users.get_by_email(EMAIL)
        assert stored is not None
        await users.set_password_hash(stored, weak_hash)

    logged_in = await auth.authenticate(EMAIL, STRONG, ip="1.2.3.4")
    assert logged_in.id == user.id

    async with session_scope() as session:
        refreshed = await UserRepository(session).get_by_email(EMAIL)
    assert refreshed is not None
    assert refreshed.password_hash != weak_hash  # it was upgraded
    assert not security.needs_rehash(refreshed.password_hash)
    assert security.verify_password(refreshed.password_hash, STRONG)


async def test_login_keeps_current_password_hash(settings: Settings, db: None) -> None:
    """A login with an already-current hash must not needlessly re-hash it."""
    auth = AuthService(settings)
    await auth.register(EMAIL, STRONG)
    async with session_scope() as session:
        before = await UserRepository(session).get_by_email(EMAIL)
        assert before is not None
        original_hash = before.password_hash

    await auth.authenticate(EMAIL, STRONG, ip="1.2.3.4")

    async with session_scope() as session:
        after = await UserRepository(session).get_by_email(EMAIL)
    assert after is not None
    assert after.password_hash == original_hash


async def test_set_dark_mode(settings: Settings, db: None) -> None:
    auth = AuthService(settings)
    user = await auth.register(EMAIL, STRONG)
    await auth.set_dark_mode(user.id, True)
    refreshed = await auth.get_user(user.id)
    assert refreshed is not None
    assert refreshed.dark_mode is True
