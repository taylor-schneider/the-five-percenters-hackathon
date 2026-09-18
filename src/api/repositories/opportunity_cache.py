"""TTL store for generated opportunities (api.md 3.11).

Opportunity Finder returns cards carrying a full TradeImpact. Those are held
here so `execute` can be called with just an `opportunity_id` instead of the
client echoing back a whole trade.

Two ways an entry dies:

- it passes `expires_at` (15 minutes) -> 410 OPPORTUNITY_EXPIRED
- the team's roster moves -> every cached card for that team is dropped, because
  its TradeImpact was computed against a roster that no longer exists

`execute` returns the ids it invalidated so the frontend can drop exactly those
cards rather than blanket-refetching, which is the slow path in a demo.

In-process dict, which is all a single-process hackathon needs. Redis later
changes this module and nothing else.
"""

from __future__ import annotations

import secrets
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

TTL_SECONDS = 900  # 15 minutes


def new_opportunity_id() -> str:
    """`opp_<12 hex>` per api.md 1."""
    return f"opp_{secrets.token_hex(6)}"


@dataclass(slots=True)
class CachedOpportunity:
    opportunity_id: str
    team_id: UUID
    roster_version: int
    """The version the impact was computed against. Once the team moves past
    this, the card is stale by definition."""
    payload: dict[str, Any]
    """The serialised Opportunity, replayed verbatim into the trade's
    rationale_snapshot at approval time."""
    expires_at: datetime


@dataclass
class OpportunityCache:
    _items: dict[str, CachedOpportunity] = field(default_factory=dict)

    def put(
        self,
        team_id: UUID,
        roster_version: int,
        payload: dict[str, Any],
        ttl_seconds: int = TTL_SECONDS,
    ) -> CachedOpportunity:
        entry = CachedOpportunity(
            opportunity_id=new_opportunity_id(),
            team_id=team_id,
            roster_version=roster_version,
            payload=payload,
            expires_at=datetime.now(timezone.utc) + timedelta(seconds=ttl_seconds),
        )
        self._items[entry.opportunity_id] = entry
        return entry

    def get(self, opportunity_id: str) -> CachedOpportunity | None:
        """None means unknown OR expired -- both are 410 to the caller."""
        entry = self._items.get(opportunity_id)
        if entry is None:
            return None
        if entry.expires_at <= datetime.now(timezone.utc):
            del self._items[opportunity_id]
            return None
        return entry

    def invalidate_team(self, team_id: UUID) -> list[str]:
        """Drop every card for a team and return their ids.

        Called by execute after the version bump. The returned list is exactly
        `invalidated_opportunity_ids` in the execute response (api.md 5.11).
        """
        dropped = [k for k, v in self._items.items() if v.team_id == team_id]
        for k in dropped:
            del self._items[k]
        return dropped

    def purge_expired(self) -> int:
        now = datetime.now(timezone.utc)
        dead = [k for k, v in self._items.items() if v.expires_at <= now]
        for k in dead:
            del self._items[k]
        return len(dead)

    def __len__(self) -> int:
        return len(self._items)


_CACHE: OpportunityCache | None = None


def get_cache() -> OpportunityCache:
    global _CACHE
    if _CACHE is None:
        _CACHE = OpportunityCache()
    return _CACHE
