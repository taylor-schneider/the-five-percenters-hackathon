"""A persisted agent finding (api.md 3.13).

Written by Gap Finder when `persist_insights` is true, and read back by
GET /teams/{id}/insights and GET /trades/{id}/reasoning. This is the
explainability trail -- the record of what an agent concluded and when.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from uuid import UUID

from ..api.models.enums import AgentName, InsightType, Position, Severity


@dataclass(slots=True)
class AgentInsightRecord:
    insight_id: UUID
    team_id: UUID
    agent_name: AgentName
    insight_type: InsightType
    severity: Severity
    summary: str
    created_at: datetime
    position: Position | None = None
    player_id: UUID | None = None
    details: dict[str, Any] = field(default_factory=dict)
