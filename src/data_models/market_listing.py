"""An acquirable player (api.md 5.7).

Absent from the source data -- derived at load from the roster, since the whole
Stage 2 surface depends on it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from uuid import UUID

from ..api.models.enums import Position
from ._time import utcnow


@dataclass(slots=True)
class MarketListingRecord:
    id: UUID
    player_id: UUID
    source_team_id: UUID | None
    """The selling club. None means a free agent."""
    position: Position
    cost: int
    """The salary this player carries once on your roster -- same field, same
    meaning, as cost on RosterEntryRecord (D1)."""
    expected_value_score: float
    available: bool = True
    updated_at: datetime = field(default_factory=utcnow)
