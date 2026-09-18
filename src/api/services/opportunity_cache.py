"""TTL cache for generated opportunities (api.md section 3.11).

Opportunities are held server-side so `execute` can be called with just an
`opportunity_id`. They are invalidated whenever `roster_version` changes --
every executed trade wipes the team's cached opportunities, because their
`impact` blocks are now computed against a stale roster.

For the hackathon this is an in-process dict. Redis is a drop-in replacement
behind the same four methods.
"""

from __future__ import annotations

import secrets
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import UUID

from ..core.config import get_settings
from ..core.errors import ErrorCode, gone
from ..models.domain import Opportunity
from ..repositories.store import utcnow


def new_opportunity_id() -> str:
    """Matches the `opp_<12 hex>` pattern the API contract declares."""
    return f"opp_{secrets.token_hex(6)}"


@dataclass(slots=True)
class CacheEntry:
    opportunity: Opportunity
    team_id: UUID
    roster_version: int
    expires_at: datetime


class OpportunityCache:
    def __init__(self) -> None:
        self._entries: dict[str, CacheEntry] = {}
        self._lock = threading.RLock()

    def put_many(
        self, opportunities: list[Opportunity], team_id: UUID, roster_version: int
    ) -> None:
        ttl = timedelta(seconds=get_settings().opportunity_ttl_seconds)
        expires = utcnow() + ttl
        with self._lock:
            for opportunity in opportunities:
                self._entries[opportunity.opportunity_id] = CacheEntry(
                    opportunity=opportunity,
                    team_id=team_id,
                    roster_version=roster_version,
                    expires_at=expires,
                )

    def get(self, opportunity_id: str, team_id: UUID, roster_version: int) -> Opportunity:
        with self._lock:
            entry = self._entries.get(opportunity_id)

        if entry is None:
            raise gone(
                ErrorCode.OPPORTUNITY_EXPIRED,
                f"Opportunity {opportunity_id} is no longer available",
                opportunity_id=opportunity_id,
            )
        if entry.expires_at <= utcnow():
            self.drop(opportunity_id)
            raise gone(
                ErrorCode.OPPORTUNITY_EXPIRED,
                f"Opportunity {opportunity_id} expired at {entry.expires_at.isoformat()}",
                opportunity_id=opportunity_id,
            )
        if entry.team_id != team_id:
            raise gone(
                ErrorCode.OPPORTUNITY_EXPIRED,
                f"Opportunity {opportunity_id} does not belong to this team",
                opportunity_id=opportunity_id,
            )
        if entry.roster_version != roster_version:
            # Invalidated by a newer trade: the impact block is stale.
            self.drop(opportunity_id)
            raise gone(
                ErrorCode.OPPORTUNITY_EXPIRED,
                f"Opportunity {opportunity_id} was invalidated by a more recent trade",
                opportunity_id=opportunity_id,
                computed_against=entry.roster_version,
                current=roster_version,
            )
        return entry.opportunity

    def drop(self, opportunity_id: str) -> None:
        with self._lock:
            self._entries.pop(opportunity_id, None)

    def invalidate_team(self, team_id: UUID) -> list[str]:
        """Drop every cached opportunity for a team. Returns the dropped ids so
        the frontend knows exactly which cards to discard."""
        with self._lock:
            dropped = [
                key for key, entry in self._entries.items() if entry.team_id == team_id
            ]
            for key in dropped:
                del self._entries[key]
        return dropped

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()


_cache = OpportunityCache()


def get_opportunity_cache() -> OpportunityCache:
    return _cache
