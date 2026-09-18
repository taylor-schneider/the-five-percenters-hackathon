"""A player's membership of a team for current-season state.

Where the money lives (D1: salary is the only money concept). Rows are closed
rather than deleted -- execute sets effective_to and clears is_current -- so
trade history stays reconstructable.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from uuid import UUID

from ..api.models.enums import Position
from ._time import utcnow


@dataclass(slots=True)
class RosterEntryRecord:
    id: UUID
    team_id: UUID
    player_id: UUID
    position: Position
    cost: int
    """Per-season salary on this team, whole currency units."""
    value_score: float
    """Team-contextual contribution, 0-100. Spread at load from the source
    value_rating (an integer 4-10), which alone left percentiles heavily tied."""
    available: bool = True
    is_current: bool = True
    effective_from: datetime = field(default_factory=utcnow)
    effective_to: datetime | None = None
