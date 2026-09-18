"""A committed or attempted trade (api.md 3.12).

There is no separate `realized_*` pair: under D1 a trade's cost is just the
salaries that moved, so the projected figures are the realized figures.

The `metrics_*`, `rationale_snapshot` and `agent_meta` blobs are plain dicts --
what a Postgres JSONB column would hold -- which keeps the storage layer free of
any dependency on the Pydantic response models.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from uuid import UUID

from ..api.models.enums import TradeStatus


@dataclass(slots=True)
class TradeRecordRow:
    trade_id: UUID
    team_id: UUID
    status: TradeStatus
    initiated_by: str
    projected_cost_delta: int
    projected_value_delta: float
    metrics_before: dict[str, Any]
    metrics_after: dict[str, Any]
    roster_version_before: int
    roster_version_after: int
    created_at: datetime
    source_opportunity_id: str | None = None
    rationale_snapshot: dict[str, Any] = field(default_factory=dict)
    """The frozen Opportunity as it stood at approval -- the audit record of
    what the GM actually agreed to."""
    agent_meta: dict[str, Any] = field(default_factory=dict)
    executed_at: datetime | None = None
