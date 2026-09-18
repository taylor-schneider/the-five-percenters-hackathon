"""Response envelopes. These COMPOSE the section 3 domain objects and never
restate a field."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Generic, TypeVar
from uuid import UUID

from pydantic import Field

from .domain import (
    AgentInsight,
    AgentMeta,
    ApiModel,
    MarketListing,
    Opportunity,
    PitchMap,
    PlayerRef,
    PositionBenchmark,
    RosterRow,
    TeamMetrics,
    TeamSummary,
    TradeImpact,
    TradeLeg,
    TradeRecord,
)
from .enums import HealthStatus, Position, PositionGroup, Severity
from .requests import OpportunityFocus

T = TypeVar("T")


class Page(ApiModel, Generic[T]):
    """api.md section 1 pagination envelope."""

    items: list[T] = Field(default_factory=list)
    next_cursor: str | None = Field(
        default=None, description="null on the final page"
    )
    total: int


# --------------------------------------------------------------------------
# 5.1 / 5.2  Health and version
# --------------------------------------------------------------------------


class HealthResponse(ApiModel):
    status: str
    checks: dict[str, str]
    uptime_seconds: int
    demo_team_id: str | None = Field(
        default=None, description="Convenience for manual Swagger testing"
    )


class AgentVersionInfo(ApiModel):
    mode: str
    version: str
    model: str | None = None


class VersionResponse(ApiModel):
    api_version: str
    build: str
    git_sha: str
    agents: dict[str, AgentVersionInfo]
    scoring_weights: dict[str, float]


# --------------------------------------------------------------------------
# 5.4  Dashboard
# --------------------------------------------------------------------------


class FlaggedPositionMetrics(ApiModel):
    team_avg_cost: int
    team_avg_value: float
    league_avg_cost: int
    league_avg_value: float


class FlaggedPosition(ApiModel):
    position: Position
    position_group: PositionGroup
    severity: Severity
    problem_score: float = Field(ge=0, le=1)
    health_status: HealthStatus
    reasons: list[str] = Field(default_factory=list)
    metrics: FlaggedPositionMetrics


class FlaggedPlayer(ApiModel):
    player: PlayerRef
    severity: Severity
    problem_score: float = Field(ge=0, le=1)
    health_status: HealthStatus
    reasons: list[str] = Field(default_factory=list)


class CoverageWarning(ApiModel):
    """A squad can be under-filled at a position without any individual player
    being bad. Nothing else in the response can express that."""

    position_group: PositionGroup
    required: int
    actual: int
    severity: Severity


class DashboardResponse(ApiModel):
    team: TeamSummary
    metrics: TeamMetrics
    roster: list[RosterRow]
    pitch: PitchMap
    flagged_positions: list[FlaggedPosition] = Field(default_factory=list)
    roster_version: int
    agent_meta: AgentMeta | None = None
    generated_at: datetime


class RosterResponse(ApiModel):
    team_id: UUID
    roster_version: int
    items: list[RosterRow]


class BenchmarksResponse(ApiModel):
    items: list[PositionBenchmark]
    computed_at: datetime


# --------------------------------------------------------------------------
# 5.8  Gap Finder
# --------------------------------------------------------------------------


class GapFinderResponse(ApiModel):
    team_id: UUID
    flagged_positions: list[FlaggedPosition] = Field(default_factory=list)
    flagged_players: list[FlaggedPlayer] = Field(default_factory=list)
    coverage_warnings: list[CoverageWarning] = Field(default_factory=list)
    roster_version: int
    agent_meta: AgentMeta
    generated_at: datetime


# --------------------------------------------------------------------------
# 5.9  Opportunity Finder
# --------------------------------------------------------------------------


class OpportunityFinderResponse(ApiModel):
    team_id: UUID
    focus: OpportunityFocus
    opportunities: list[Opportunity] = Field(
        default_factory=list, description="Sorted by opportunity_score descending"
    )
    candidates_evaluated: int = Field(
        description="Lets the UI distinguish 'nothing was considered' from "
        "'everything was filtered out'."
    )
    roster_version: int
    agent_meta: AgentMeta
    generated_at: datetime


# --------------------------------------------------------------------------
# 5.10 / 5.11  Trader
# --------------------------------------------------------------------------


class SimulateResponse(ApiModel):
    impact: TradeImpact
    legs: list[TradeLeg]
    agent_meta: AgentMeta


class AppliedChanges(ApiModel):
    acquired: list[PlayerRef] = Field(default_factory=list)
    released: list[PlayerRef] = Field(default_factory=list)


class ExecuteResponse(ApiModel):
    trade: TradeRecord
    metrics_after: TeamMetrics
    roster_version_after: int
    applied_changes: AppliedChanges
    invalidated_opportunity_ids: list[str] = Field(
        default_factory=list,
        description="Exactly which cached cards the frontend should drop. Without "
        "this the UI has to blanket-invalidate and refetch everything.",
    )
    executed_at: datetime


# --------------------------------------------------------------------------
# 5.13  Explainability
# --------------------------------------------------------------------------


class TradeReasoningResponse(ApiModel):
    trade_id: UUID
    rationale_snapshot: dict[str, Any] = Field(default_factory=dict)
    agent_chain: list[AgentMeta] = Field(default_factory=list)
    insights: list[AgentInsight] = Field(default_factory=list)


TeamsPage = Page[TeamSummary]
MarketPage = Page[MarketListing]
InsightsPage = Page[AgentInsight]
