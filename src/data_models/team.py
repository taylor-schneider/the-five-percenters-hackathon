"""A club. Seeded from data/clubs.csv."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from uuid import UUID

from ._time import utcnow


@dataclass(slots=True)
class TeamRecord:
    id: UUID
    name: str
    budget_cap: int
    roster_version: int = 1
    """Optimistic-lock token (D7). Increments on every committed trade."""
    created_at: datetime = field(default_factory=utcnow)
