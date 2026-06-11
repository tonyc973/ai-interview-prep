"""Opt-in real-OpenAI smoke test (``make smoke``). NEVER runs in CI.

Runs one real research-stage call through the gateway to prove the OpenAI wiring,
structured-output parsing, and cost accounting work end to end. Requires a real
``APP_OPENAI_API_KEY``. Prints token usage and cost; persists nothing.
"""

from __future__ import annotations

import uuid

from app.agents.crews import run_research_stage
from app.agents.gateway import LLMGateway, UsageLedger
from app.config import ConfigError, get_settings
from app.domain.enums import SeniorityLevel
from app.logging import configure_logging


def main() -> int:
    try:
        settings = get_settings()
    except ConfigError as exc:
        print(f"Configuration error:\n{exc}")
        return 1

    configure_logging(settings.log_level, json_logs=False)
    gateway = LLMGateway(settings)
    ledger = UsageLedger(
        user_id=uuid.uuid4(),
        session_id=None,
        max_cost_per_session_usd=settings.max_cost_per_session_usd,
        max_cost_per_user_per_day_usd=settings.max_cost_per_user_per_day_usd,
    )

    print("Running real research stage against OpenAI…")
    brief = run_research_stage(
        settings=settings,
        gateway=gateway,
        ledger=ledger,
        target_role="Backend Engineer",
        target_company="Acme Corp",
        seniority=SeniorityLevel.SENIOR,
        job_description="Build and scale Python services. Strong on system design and reliability.",
        cv_text=None,
    )
    print("\n--- ResearchBrief ---")
    print(f"Summary: {brief.role_summary}")
    print(f"Competencies: {', '.join(brief.key_competencies)}")
    total_cost = sum(e.cost_usd for e in ledger.entries)
    total_tokens = sum(e.total_tokens for e in ledger.entries)
    print(f"\nCalls: {len(ledger.entries)} | tokens: {total_tokens} | cost: ${total_cost:.6f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
