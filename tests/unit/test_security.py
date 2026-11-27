"""Unit tests for password hashing, strength, and email validation."""

from __future__ import annotations

import pytest

from app.services import security


def test_hash_and_verify_roundtrip() -> None:
    h = security.hash_password("a-strong-passphrase-123")
    assert h != "a-strong-passphrase-123"
    assert h.startswith("$argon2id$")  # argon2id, not bcrypt
    assert security.verify_password(h, "a-strong-passphrase-123")
    assert not security.verify_password(h, "wrong")


def test_verify_password_on_garbage_hash_returns_false() -> None:
    assert not security.verify_password("not-a-hash", "whatever")


def test_verify_dummy_never_raises() -> None:
    security.verify_dummy("anything")  # must not raise


def test_normalize_email() -> None:
    assert security.normalize_email("Person@Example.COM") == "person@example.com"


def test_normalize_email_rejects_invalid() -> None:
    with pytest.raises(ValueError):
        security.normalize_email("not-an-email")


def test_password_policy_length() -> None:
    result = security.evaluate_password("short", min_length=12, min_score=3)
    assert not result.ok
    assert "12" in result.warning


def test_password_policy_weak_score() -> None:
    result = security.evaluate_password("password1234", min_length=12, min_score=3)
    assert not result.ok  # common/guessable


def test_password_policy_strong() -> None:
    result = security.evaluate_password("tr0ub4dor-galaxy-stew-9173", min_length=12, min_score=3)
    assert result.ok
    assert result.score >= 3


def test_needs_rehash_false_for_current() -> None:
    h = security.hash_password("a-strong-passphrase-123")
    assert not security.needs_rehash(h)


def test_needs_rehash_true_for_invalid_hash() -> None:
    # An unparseable/garbage hash should be treated as needing an upgrade,
    # not crash — so a corrupt stored value is re-hashed on next login.
    assert security.needs_rehash("not-a-valid-argon2-hash")
