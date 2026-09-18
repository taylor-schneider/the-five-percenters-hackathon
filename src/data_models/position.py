"""Position reference data, one row per `data/positions.csv` line.

The position taxonomy collapsed to the four buckets the source data actually
carries, so `position` and `position_group` hold the same value in v1. Both
fields are kept on the wire (api.md 3.4/3.5) so re-expanding to ten specific
slots later is a data change in `data/positions.csv`, not an API change.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..api.models.enums import Position, PositionGroup


@dataclass(frozen=True, slots=True)
class PositionRecord:
    position: Position
    position_group: PositionGroup
    display_name: str
    pitch_x: float
    """Normalised 0-1. Origin top-left."""
    pitch_y: float
    """Normalised 0-1. y=0 is the team's own goal line."""
    min_count: int
    """Squad minimum for this group. Enforced non-worsening: a trade is blocked
    only when it pushes an already-short group further below this number."""
    sort_order: int
