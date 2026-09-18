"""A club. Seeded from `data/clubs.csv`."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID


@dataclass(slots=True)
class TeamRecord:
    team_id: UUID
    """UUIDv5 derived from `club_code`, so re-seeding is stable."""
    club_code: str
    """The source `club_id` (e.g. "MCI"). Kept for CSV traceability."""
    name: str
    budget_cap: int
    """Hard cap, whole currency units (D10). Three clubs seed over cap and can
    therefore only make cost-reducing trades until they are back under it."""
    roster_version: int = 1
    """Optimistic-lock token (D7). Mutable -- increments on every committed
    trade, which is why this record is not frozen."""
