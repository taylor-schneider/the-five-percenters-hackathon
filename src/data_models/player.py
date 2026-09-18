"""Player identity. Seeded from data/players.csv.

Identity only -- no money, no scores. Salary and value belong to a player's
membership of a team, so they live on RosterEntryRecord (api.md 3.4).
"""

from __future__ import annotations

from dataclasses import dataclass

from uuid import UUID

from ..api.models.enums import Position, PositionGroup, group_of


@dataclass(slots=True)
class PlayerRecord:
    id: UUID
    name: str
    position: Position
    age: int
    """Not in the source CSV -- derived deterministically at load."""
    appearances: int = 30
    """League appearances. Drives confidence and the HIGH_UNCERTAINTY soft
    violation -- a thin sample is a real risk, not a guess."""

    @property
    def position_group(self) -> PositionGroup:
        return group_of(self.position)
