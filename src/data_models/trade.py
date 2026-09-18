"""A committed or attempted trade (api.md 3.12).

No separate realized_* pair: under D1 a trade's cost is just the salaries that
moved, so projected figures are realized figures.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from uuid import UUID

from ..api.models.enums import TradeStatus
from ._time import utcnow


@dataclass(slots=True)
class TradeRecordRow:
    id: UUID
    team_id: UUID
    status: TradeStatus
    initiated_by: str
    source_opportunity_id: str | None
    payload: dict[str, Any]
    """Frozen legs, metrics and rationale -- what a JSONB column would hold."""
    created_at: datetime = field(default_factory=utcnow)
    executed_at: datetime | None = None
