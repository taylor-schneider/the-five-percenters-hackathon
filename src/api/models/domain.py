"""Canonical domain objects from api.md section 3.

This module is the ONLY place these objects are defined. requests.py and
responses.py compose them and never restate a field.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from .enums import (
    AgentMode,
    AgentName,
    HealthStatus,
    InsightType,
    OpportunityType,
    Position,
    PositionGroup,
    Severity,
    TradeAction,
    TradeStatus,
)


class ApiModel(BaseModel):
    """Base for every API object: snake_case, no extra fields, enums as values."""

    model_config = ConfigDict(extra="forbid", use_enum_values=False)


# --------------------------------------------------------------------------
# 3.2 / 3.3  Team
# --------------------------------------------------------------------------


class TeamSummary(ApiModel):
    team_id: UUID
    name: str
    budget_cap: int = Field(description="Hard cap, whole euros (D10)")
    roster_version: int = Field(
        description="Optimistic-lock token. Increments on every committed trade (D7)."
    )


class TeamMetrics(ApiModel):
    team_cost: int = Field(description="SUM(cost) over the current roster")
    team_score: float = Field(ge=0, le=100, description="AVG(value_score), 1dp")
    budget_cap: int
    budget_remaining: int = Field(
        description="budget_cap - team_cost. May be negative on a pre-existing "
        "overspend; a trade may never make it negative."
    )
    squad_size: int


# --------------------------------------------------------------------------
# 3.4 / 3.5  Player and roster
# --------------------------------------------------------------------------


class PlayerRef(ApiModel):
    """Minimal player identity. Never carries money or scores -- those are
    contextual to a roster entry or a market listing."""

    player_id: UUID
    name: str
    position: Position
    position_group: PositionGroup
    age: int


class RosterRow(ApiModel):
    roster_entry_id: UUID
    player: PlayerRef
    cost: int = Field(description="Per-season salary on this team (D1)")
    value_score: float = Field(ge=0, le=100)

    # Benchmark columns. Omitted by the raw /roster endpoint (5.5).
    league_avg_cost: int | None = None
    league_avg_value: float | None = None
    cost_vs_league_pct: float | None = Field(
        default=None, description="(cost / league_avg_cost - 1) * 100. Positive = overpaid."
    )
    value_vs_league_pct: float | None = Field(
        default=None,
        description="(value_score / league_avg_value - 1) * 100. Negative = underperforming.",
    )
    cost_efficiency: float | None = Field(
        default=None, ge=0, le=1, description="Normalised value_score/cost across the league"
    )
    health_status: HealthStatus | None = None

    available: bool = Field(description="May this player legally be sold or swapped out")


# --------------------------------------------------------------------------
# 3.6 / 3.7  Pitch map and benchmarks
# --------------------------------------------------------------------------


class PitchSlot(ApiModel):
    position: Position
    position_group: PositionGroup
    x: float = Field(ge=0, le=1)
    y: float = Field(ge=0, le=1, description="0 = the team's own goal line")
    health_status: HealthStatus
    problem_score: float = Field(ge=0, le=1)
    occupants: list[UUID] = Field(
        default_factory=list,
        description="Empty array means an unfilled slot, which is itself a gap.",
    )
    slot_avg_cost: int
    slot_avg_value: float
    headline: str | None = Field(
        default=None, description="One-line tooltip. Present only when health_status is red."
    )


class PitchMap(ApiModel):
    formation: str = "4-3-3"
    slots: list[PitchSlot] = Field(default_factory=list)


class PositionBenchmark(ApiModel):
    position: Position
    league_avg_cost: int
    league_avg_value: float
    cost_p50: int
    value_p50: float
    sample_size: int = Field(
        description="Mute benchmark columns in the UI when this is below 5."
    )


# --------------------------------------------------------------------------
# 3.8  Trade legs
# --------------------------------------------------------------------------


class TradeLegRequest(ApiModel):
    """All a client ever sends. No price fields, by design (D2)."""

    action: TradeAction
    player_id: UUID


class TradeLeg(ApiModel):
    """Server-enriched leg. All deltas signed from the acting team (D3)."""

    action: TradeAction
    player: PlayerRef
    cost_delta: int = Field(
        description="The player's salary, signed by direction. Nothing else contributes (D1)."
    )
    value_delta: float = Field(
        description="Raw score delta, NOT a team-average delta. The team-level number "
        "is computed once over the whole trade in TradeImpact."
    )
    counterparty_team_id: UUID | None = None
    listing_id: UUID | None = Field(
        default=None, description="Set on buy/swap_in only. Pins the listing the salary came from."
    )


# --------------------------------------------------------------------------
# 3.9 / 3.10  Impact and violations
# --------------------------------------------------------------------------


class Violation(ApiModel):
    code: str
    severity: Severity = Field(
        description="high = hard blocker, always blocks execute. low/medium = surfaced "
        "in the UI but does not block."
    )
    message: str
    details: dict[str, Any] = Field(default_factory=dict)


class TradeImpact(ApiModel):
    valid: bool
    violations: list[Violation] = Field(default_factory=list)
    projected_cost_delta: int = Field(
        description="Exactly the sum of leg cost_delta values -- the identity D1 buys you."
    )
    projected_value_delta: float = Field(
        description="post.team_score - current.team_score. NOT the sum of leg value_delta, "
        "because team_score is a mean over a changing squad size."
    )
    current_metrics: TeamMetrics
    post_trade_metrics: TeamMetrics
    position_group_counts_after: dict[PositionGroup, int]
    roster_version: int


# --------------------------------------------------------------------------
# 3.11  Opportunity
# --------------------------------------------------------------------------


class Opportunity(ApiModel):
    opportunity_id: str = Field(pattern=r"^opp_[0-9a-f]{12}$")
    type: OpportunityType
    target_position: Position | None = None
    opportunity_score: float = Field(
        ge=0,
        le=1,
        description="Ranking key. Min-max normalised WITHIN one response -- do not "
        "persist it for cross-run comparison.",
    )
    confidence: float = Field(
        ge=0,
        le=1,
        description="The agent's own certainty. Distinct from opportunity_score: a trade "
        "can be clearly good but rest on thin data.",
    )
    legs: list[TradeLeg]
    impact: TradeImpact
    risks: list[str] = Field(default_factory=list)
    reasoning_summary: str
    reasoning_steps: list[str] = Field(default_factory=list)
    expires_at: datetime


# --------------------------------------------------------------------------
# 3.12  Trade record
# --------------------------------------------------------------------------


class TradeRecord(ApiModel):
    trade_id: UUID
    team_id: UUID
    status: TradeStatus
    initiated_by: str
    source_opportunity_id: str | None = None
    legs: list[TradeLeg] = Field(default_factory=list)
    projected_cost_delta: int
    projected_value_delta: float
    metrics_before: TeamMetrics
    metrics_after: TeamMetrics
    roster_version_before: int
    roster_version_after: int
    rationale_snapshot: dict[str, Any] = Field(
        default_factory=dict,
        description="The frozen Opportunity as it stood at approval -- the audit record "
        "of what the GM actually agreed to.",
    )
    agent_meta: "AgentMeta | None" = None
    created_at: datetime
    executed_at: datetime | None = None


# --------------------------------------------------------------------------
# 3.13 / 3.14  Insights and agent metadata
# --------------------------------------------------------------------------


class AgentInsight(ApiModel):
    insight_id: UUID
    team_id: UUID
    agent_name: AgentName
    insight_type: InsightType
    severity: Severity
    position: Position | None = None
    player_id: UUID | None = None
    summary: str
    details: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime


class AgentMeta(ApiModel):
    agent_name: AgentName
    mode: AgentMode
    version: str
    model: str | None = Field(
        default=None, description="null in heuristic mode; the model id in llm mode."
    )
    input_snapshot_hash: str = Field(
        description="SHA-256 over the canonicalised agent input. Proves which roster "
        "state a recommendation was made against."
    )
    latency_ms: int
    generated_at: datetime


class MarketListing(ApiModel):
    listing_id: UUID
    player: PlayerRef
    source_team_id: UUID | None = Field(
        default=None, description="null for a free agent"
    )
    cost: int = Field(
        description="The salary this player will carry once on your roster -- the same "
        "field, same meaning, as cost on a RosterRow (D1)."
    )
    expected_value_score: float = Field(ge=0, le=100)
    available: bool
    updated_at: datetime


TradeRecord.model_rebuild()
