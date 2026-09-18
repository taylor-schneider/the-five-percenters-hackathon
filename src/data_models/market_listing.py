"""An acquirable player (api.md 5.7).

Not present in the source data at all -- the entire Stage 2 surface depends on
this table, so the seeder derives it: every available roster player becomes a
listing owned by their club, plus synthetic free agents so there is always a
buy option.

If a future Postgres schema keeps the design doc's `asking_price` column, map it
to `cost` in the repository layer. Do not surface two names for one number.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID


@dataclass(slots=True)
class MarketListingRecord:
    listing_id: UUID
    player_id: UUID
    source_team_id: UUID | None
    """The selling club. None means a free agent."""
    cost: int
    """The salary this player will carry once on your roster -- the same field,
    same meaning, as `cost` on RosterEntryRecord (D1)."""
    expected_value_score: float
    available: bool
    updated_at: datetime
    sample_size: int = 0
    """Backs the soft HIGH_UNCERTAINTY violation: a thin sample behind
    `expected_value_score` warns but never blocks."""
