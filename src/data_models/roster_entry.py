"""A player's membership of a team for current-season state.

This is where the money lives (D1: salary is the only money concept). The same
`cost` field, with the same meaning, appears on MarketListingRecord -- one
concept, one name, everywhere.

Rows are closed rather than deleted: `execute` sets `effective_to` and clears
`is_current`, so the trade history stays reconstructable.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from ..api.models.enums import Position


@dataclass(slots=True)
class RosterEntryRecord:
    roster_entry_id: UUID
    team_id: UUID
    player_id: UUID
    position: Position
    cost: int
    """Per-season salary on this team, whole currency units."""
    value_score: float
    """Team-contextual contribution, 0.0-100.0. Spread from the source
    `value_rating` (an integer 4-10) at seed time -- seven distinct ratings
    across 150 players would otherwise make percentiles heavily tied."""
    available: bool
    """Whether this player may legally be sold or swapped out."""
    effective_from: datetime
    effective_to: datetime | None = None
    is_current: bool = True
