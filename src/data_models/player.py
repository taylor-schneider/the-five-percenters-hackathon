"""Player identity. Seeded from `data/players.csv`.

Identity only -- no money, no scores. Salary and value are properties of a
player's membership of a team, so they live on RosterEntryRecord (api.md 3.4).
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from ..api.models.enums import Position, PositionGroup


@dataclass(frozen=True, slots=True)
class PlayerRecord:
    player_id: UUID
    """UUIDv5 derived from `code`, so re-seeding is stable."""
    code: str
    """The source `player_id` (e.g. "P001"). Kept for CSV traceability."""
    name: str
    position: Position
    position_group: PositionGroup
    age: int
    """Not present in the source CSV -- derived deterministically at seed time."""
    active: bool = True
