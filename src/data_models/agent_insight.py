"""A persisted agent finding (api.md 3.13). The explainability trail."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from uuid import UUID

from ..api.models.enums import Position
from ._time import utcnow


@dataclass(slots=True)
class InsightRecord:
    id: UUID
    team_id: UUID
    agent_name: str
    insight_type: str
    severity: str
    position: Position | None
    player_id: UUID | None
    summary: str
    details: dict[str, Any]
    created_at: datetime = field(default_factory=utcnow)
