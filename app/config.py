"""Application configuration.

ALL runtime configuration is sourced from the environment (prefixed ``APP_``)
via pydantic-settings. There are no other config inputs. The app fails fast at
startup with a readable message listing any missing/invalid required variables,
so a misconfigured deployment never starts in a half-working state.

Secrets are wrapped in :class:`~pydantic.SecretStr` so they never render in
logs, tracebacks, or ``repr`` output.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr, ValidationError, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.domain.enums import AgentName

_PLACEHOLDER_TOKENS = ("replace-me", "replace-with", "sk-replace-me", "changeme")


class ConfigError(RuntimeError):
    """Raised when configuration is missing or invalid. Message is user-safe."""


class Settings(BaseSettings):
    """Strongly-typed application settings. Immutable after load."""

    model_config = SettingsConfigDict(
        env_prefix="APP_",
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
        frozen=True,
    )

    # --- REQUIRED secrets -------------------------------------------------
    openai_api_key: SecretStr = Field(..., description="OpenAI API key for the LLM gateway")
    storage_secret: SecretStr = Field(
        ..., description="Signing secret for NiceGUI server-side user storage"
    )

    # --- Database ---------------------------------------------------------
    database_url: str = Field(default="sqlite+aiosqlite:///./data/app.db")

    # --- LLM configuration ------------------------------------------------
    openai_default_model: str = "gpt-4o-mini"
    model_role_researcher: str | None = None
    model_question_architect: str | None = None
    model_mock_interviewer: str | None = None
    model_evaluator: str | None = None
    openai_request_timeout_s: float = 60.0
    openai_max_retries: int = 4

    # --- Guardrails / cost caps ------------------------------------------
    max_cost_per_session_usd: float = 0.50
    max_cost_per_user_per_day_usd: float = 5.00
    max_jd_chars: int = 20_000
    max_cv_chars: int = 20_000
    interview_default_questions: int = 8

    # --- Auth / security --------------------------------------------------
    password_min_length: int = 12
    password_min_zxcvbn_score: int = 3
    login_max_failures: int = 5
    login_lockout_base_seconds: int = 2
    login_lockout_max_seconds: int = 900

    # --- Runtime ----------------------------------------------------------
    env: Literal["development", "production", "test"] = "development"
    log_level: str = "INFO"
    host: str = "0.0.0.0"  # noqa: S104 — binding all interfaces is intended for containers
    port: int = 8080
    base_url: str = "http://localhost:8080"

    # ------------------------------------------------------------------ #
    @field_validator("storage_secret")
    @classmethod
    def _secret_is_strong(cls, value: SecretStr) -> SecretStr:
        raw = value.get_secret_value()
        if len(raw) < 32:
            raise ValueError("APP_STORAGE_SECRET must be at least 32 characters")
        if any(tok in raw.lower() for tok in _PLACEHOLDER_TOKENS):
            raise ValueError("APP_STORAGE_SECRET is still the placeholder value")
        return value

    @field_validator("openai_api_key")
    @classmethod
    def _key_not_placeholder(cls, value: SecretStr) -> SecretStr:
        raw = value.get_secret_value()
        if not raw or any(tok in raw.lower() for tok in _PLACEHOLDER_TOKENS):
            raise ValueError("APP_OPENAI_API_KEY is missing or still the placeholder value")
        return value

    @field_validator("password_min_zxcvbn_score")
    @classmethod
    def _score_range(cls, value: int) -> int:
        if not 0 <= value <= 4:
            raise ValueError("APP_PASSWORD_MIN_ZXCVBN_SCORE must be between 0 and 4")
        return value

    # ------------------------------------------------------------------ #
    @property
    def is_sqlite(self) -> bool:
        return self.database_url.startswith("sqlite")

    @property
    def is_production(self) -> bool:
        return self.env == "production"

    def model_for_agent(self, agent: AgentName) -> str:
        """Resolve the OpenAI model for an agent, falling back to the default."""
        override = {
            AgentName.ROLE_RESEARCHER: self.model_role_researcher,
            AgentName.QUESTION_ARCHITECT: self.model_question_architect,
            AgentName.MOCK_INTERVIEWER: self.model_mock_interviewer,
            AgentName.EVALUATOR: self.model_evaluator,
        }[agent]
        return override or self.openai_default_model


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the process-wide settings singleton.

    Raises :class:`ConfigError` with a readable, secret-free summary of every
    missing or invalid variable rather than leaking a raw pydantic traceback.
    """
    try:
        return Settings()  # values come from env/.env (validated by pydantic-settings)
    except ValidationError as exc:
        problems = []
        for err in exc.errors():
            loc = ".".join(str(p) for p in err["loc"]) or "(root)"
            var = f"APP_{loc.upper()}"
            problems.append(f"  - {var}: {err['msg']}")
        joined = "\n".join(problems)
        raise ConfigError(
            "Invalid or missing configuration. Fix the following environment "
            f"variables (see .env.example):\n{joined}"
        ) from None
