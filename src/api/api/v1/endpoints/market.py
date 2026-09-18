"""Benchmarks, market listings, trades and insights (api.md 5.6, 5.7, 5.12-5.14)."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query

from ....core.errors import ErrorCode, error_responses, not_found
from ....models.enums import (
    AgentName,
    InsightType,
    Position,
    PositionGroup,
    Severity,
    TradeStatus,
)
from ....models.responses import (
    BenchmarksResponse,
    InsightsPage,
    MarketPage,
    Page,
    TradeReasoningResponse,
)
from ....repositories.store import utcnow
from ....services import team_service, trader_service
from ....services.scoring import LeagueContext
from ...deps import StoreDep

router = APIRouter()


@router.get(
    "/benchmarks/positions",
    response_model=BenchmarksResponse,
    tags=["Benchmarks"],
    summary="League average cost and value per position",
    description=(
        "`sample_size` matters: with a small league seed a benchmark over 3 players is "
        "noise. Mute benchmark columns in the UI when it is below 5."
    ),
)
async def get_benchmarks(
    store: StoreDep,
    position: Annotated[list[Position] | None, Query()] = None,
) -> BenchmarksResponse:
    ctx = LeagueContext.build(store.all_current_entries())
    return BenchmarksResponse(
        items=team_service.benchmarks(ctx, position), computed_at=utcnow()
    )


@router.get(
    "/market/listings",
    response_model=MarketPage,
    tags=["Market"],
    summary="Browse acquirable players",
    description=(
        "`cost` is the salary the player will carry once on your roster -- the same "
        "field, same meaning, as `cost` on a RosterRow (D1)."
    ),
)
async def list_market(
    store: StoreDep,
    position: Position | None = None,
    position_group: PositionGroup | None = None,
    max_cost: int | None = None,
    min_value: float | None = None,
    exclude_team_id: UUID | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    cursor: str | None = None,
) -> MarketPage:
    records = store.list_listings(
        position=position,
        position_group=position_group,
        max_cost=max_cost,
        min_value=min_value,
        exclude_team_id=exclude_team_id,
    )
    offset = int(cursor) if cursor and cursor.isdigit() else 0
    window = records[offset : offset + limit]
    next_cursor = str(offset + limit) if offset + limit < len(records) else None
    return Page(
        items=[team_service.listing_model(store, r) for r in window],
        next_cursor=next_cursor,
        total=len(records),
    )


@router.get(
    "/trades/{trade_id}",
    tags=["Trades"],
    summary="Trade record",
    responses=error_responses(404, 422),
)
async def get_trade(trade_id: UUID, store: StoreDep):
    row = store.get_trade(trade_id)
    if row is None:
        raise not_found(
            ErrorCode.TRADE_NOT_FOUND, f"Trade {trade_id} not found", trade_id=str(trade_id)
        )
    return trader_service.trade_to_model(row)


@router.get(
    "/trades/{trade_id}/reasoning",
    response_model=TradeReasoningResponse,
    tags=["Trades"],
    summary="Full reasoning trace for a committed trade",
    description=(
        "The frozen Opportunity as approved, the agent chain, and the input snapshot "
        "hash -- the audit record of what the GM actually agreed to."
    ),
    responses=error_responses(404, 422),
)
async def get_trade_reasoning(trade_id: UUID, store: StoreDep) -> TradeReasoningResponse:
    row = store.get_trade(trade_id)
    if row is None:
        raise not_found(
            ErrorCode.TRADE_NOT_FOUND, f"Trade {trade_id} not found", trade_id=str(trade_id)
        )
    payload = row.payload
    snapshot = payload.get("rationale_snapshot", {}) if isinstance(payload, dict) else {}
    agent_meta = payload.get("agent_meta") if isinstance(payload, dict) else None
    chain = [agent_meta] if agent_meta else []
    insights = [
        team_service.to_insight_model(i) for i in store.list_insights(row.team_id)
    ][:20]
    return TradeReasoningResponse(
        trade_id=trade_id,
        rationale_snapshot=snapshot,
        agent_chain=chain,
        insights=insights,
    )


@router.get(
    "/teams/{team_id}/insights",
    response_model=InsightsPage,
    tags=["Insights"],
    summary="Persisted agent insight trail, newest first",
    responses=error_responses(404, 422),
)
async def list_insights(
    team_id: UUID,
    store: StoreDep,
    agent_name: AgentName | None = None,
    insight_type: InsightType | None = None,
    severity: Severity | None = None,
    position: Position | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    cursor: str | None = None,
) -> InsightsPage:
    team_service.require_team(store, team_id)
    records = store.list_insights(
        team_id,
        agent_name=agent_name.value if agent_name else None,
        insight_type=insight_type.value if insight_type else None,
        severity=severity.value if severity else None,
        position=position,
    )
    offset = int(cursor) if cursor and cursor.isdigit() else 0
    window = records[offset : offset + limit]
    next_cursor = str(offset + limit) if offset + limit < len(records) else None
    return Page(
        items=[team_service.to_insight_model(r) for r in window],
        next_cursor=next_cursor,
        total=len(records),
    )
