"""Password hashing, password-strength, and email validation primitives.

Pure functions (no DB). argon2id only (the argon2-cffi default). Failure paths
are written to be constant-time where it matters: an unknown email still runs an
argon2 verify against a dummy hash so login timing does not reveal whether an
account exists.
"""

from __future__ import annotations

import contextlib
from dataclasses import dataclass

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError
from email_validator import EmailNotValidError, validate_email
from zxcvbn import zxcvbn

_hasher = PasswordHasher()

# Precomputed once so authenticate() can spend the same time on a missing user.
DUMMY_HASH = _hasher.hash("timing-equalizer-not-a-real-password")


@dataclass(frozen=True, slots=True)
class PasswordStrength:
    ok: bool
    score: int  # zxcvbn 0-4
    warning: str
    suggestions: tuple[str, ...]


def hash_password(password: str) -> str:
    """Hash a password with argon2id."""
    return _hasher.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    """Verify a password against a hash. Returns False on any mismatch/parse error."""
    try:
        return _hasher.verify(password_hash, password)
    except (VerifyMismatchError, InvalidHashError, ValueError):
        return False


def verify_dummy(password: str) -> None:
    """Run a verify against the dummy hash to equalize timing for missing users."""
    with contextlib.suppress(Exception):
        _hasher.verify(DUMMY_HASH, password)


def needs_rehash(password_hash: str) -> bool:
    """True if the stored hash should be upgraded to current argon2 parameters."""
    try:
        return _hasher.check_needs_rehash(password_hash)
    except InvalidHashError:
        return True


def normalize_email(email: str) -> str:
    """Validate and normalize an email; raise ValueError on invalid input."""
    try:
        result = validate_email(email, check_deliverability=False)
    except EmailNotValidError as exc:
        raise ValueError(str(exc)) from exc
    return result.normalized.lower()


def evaluate_password(
    password: str,
    *,
    min_length: int,
    min_score: int,
    user_inputs: list[str] | None = None,
) -> PasswordStrength:
    """Evaluate a password against the length + zxcvbn-score policy."""
    if len(password) < min_length:
        return PasswordStrength(
            ok=False,
            score=0,
            warning=f"Password must be at least {min_length} characters.",
            suggestions=(f"Use {min_length} or more characters.",),
        )
    result = zxcvbn(password, user_inputs=user_inputs or [])
    score = int(result["score"])
    feedback = result.get("feedback", {}) or {}
    warning = str(feedback.get("warning", "") or "")
    suggestions = tuple(str(s) for s in feedback.get("suggestions", []) or [])
    if score < min_score:
        return PasswordStrength(
            ok=False,
            score=score,
            warning=warning or "Password is too weak or guessable.",
            suggestions=suggestions or ("Add more words, length, or unpredictability.",),
        )
    return PasswordStrength(ok=True, score=score, warning="", suggestions=())
