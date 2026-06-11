"""Usage/cost service: bridges the gateway's in-memory ledger and the DB.

The gateway never touches the database. Before an operation, this service seeds
a :class:`UsageLedger` with spend already persisted (so per-session and per-day
caps are enforced against the real running total); after the operation it
persists the ledger's entries. This is what makes "the gateway enforces caps"
true across process restarts.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from app.agents.gateway import CostLimitExceeded, UsageLedger
from app.config import Settings
from app.db.base import session_scope, utcnow
from app.db.repositories import UsageRepository


def _utc_day_start(now: datetime | None = None) -> datetime:
    moment = now or utcnow()
    return moment.replace(hour=0, minute=0, second=0, microsecond=0)


class UsageService:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    async def new_ledger(self, *, user_id: uuid.UUID, session_id: uuid.UUID | None) -> UsageLedger:
        """Build a ledger seeded with persisted session + daily spend."""
        async with session_scope() as session:
            usage = UsageRepository(session)
            session_seed = await usage.session_cost(session_id) if session_id is not None else 0.0
            day_seed = await usage.user_cost_since(user_id, _utc_day_start())
        return UsageLedger(
            user_id=user_id,
            session_id=session_id,
            max_cost_per_session_usd=self._settings.max_cost_per_session_usd,
            max_cost_per_user_per_day_usd=self._settings.max_cost_per_user_per_day_usd,
            session_spend_seed=session_seed,
            user_day_spend_seed=day_seed,
        )

    async def assert_within_caps(self, *, user_id: uuid.UUID, session_id: uuid.UUID | None) -> None:
        """Raise CostLimitExceeded if a cap is already met before doing any work."""
        ledger = await self.new_ledger(user_id=user_id, session_id=session_id)
        ledger.check_budget()

    async def persist(self, ledger: UsageLedger) -> None:
        if not ledger.entries:
            return
        async with session_scope() as session:
            await UsageRepository(session).add_many(ledger.entries)

    async def user_daily_cost(self, user_id: uuid.UUID) -> float:
        async with session_scope() as session:
            return await UsageRepository(session).user_cost_since(user_id, _utc_day_start())

    async def session_cost(self, session_id: uuid.UUID) -> float:
        async with session_scope() as session:
            return await UsageRepository(session).session_cost(session_id)

    # exported so callers can catch a single type
    CostLimitExceeded = CostLimitExceeded
