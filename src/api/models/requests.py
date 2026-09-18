"""Request bodies. These COMPOSE the section 3 domain objects and never
restate a field."""

from __future__ import annotations

from typing import Literal
from uuid import UUID

from pydantic import Field, model_validator

from .domain import ApiModel, TradeLegRequest
from .enums import OpportunityType, Position, PositionGroup


class Constraints(ApiModel):
    budget_cap: int | None = Field(
        default=None,
        description="Overrides the team's stored cap for what-if analysis. "
        "null uses the stored value.",
    )
    min_position_group_counts: dict[PositionGroup, int] | None = Field(
        default=None,
        description="Keyed by PositionGroup (D5). Defaults to GK:2, DEF:6, MID:6, FWD:4.",
    )


class GapFinderConstraints(Constraints):
    pass


class GapFinderRequest(ApiModel):
    team_id: UUID
    constraints: GapFinderConstraints = Field(default_factory=GapFinderConstraints)
    persist_insights: bool = Field(
        default=True,
        description="Writes results to the agent_insights trail for explainability.",
    )

    model_config = {
        "json_schema_extra": {
            "example": {
                "team_id": "00000000-0000-0000-0000-000000000000",
                "constraints": {
                    "budget_cap": None,
                    "min_position_group_counts": {"GK": 2, "DEF": 6, "MID": 6, "FWD": 4},
                },
                "persist_insights": True,
            }
        }
    }


class OpportunityFocus(ApiModel):
    positions: list[Position] = Field(
        default_factory=list, description="Empty = analyse the whole squad"
    )
    player_ids: list[UUID] = Field(
        default_factory=list,
        description="Narrows to trades involving these players. Combined with positions as OR.",
    )
    types: list[OpportunityType] = Field(
        default_factory=lambda: list(OpportunityType), description="Defaults to all three"
    )


class OpportunityConstraints(Constraints):
    max_results: int = Field(default=20, ge=1, le=50)
    max_cost_increase: int | None = Field(
        default=None,
        description="Hard filter on projected_cost_delta. 0 = only cost-neutral-or-better.",
    )
    min_value_gain: float | None = Field(
        default=None, description="Hard filter on projected_value_delta."
    )


class OpportunityFinderRequest(ApiModel):
    team_id: UUID
    focus: OpportunityFocus = Field(default_factory=OpportunityFocus)
    constraints: OpportunityConstraints = Field(default_factory=OpportunityConstraints)
    roster_version: int | None = Field(
        default=None,
        description="If supplied and stale -> 409 STALE_ROSTER_VERSION, so a user cannot "
        "act on a dashboard rendered before someone else's trade.",
    )


class _TradeSource(ApiModel):
    """Shared rule: exactly one of opportunity_id or legs."""

    opportunity_id: str | None = None
    legs: list[TradeLegRequest] | None = None

    @model_validator(mode="after")
    def _exactly_one_source(self):
        if bool(self.opportunity_id) == bool(self.legs):
            raise ValueError("supply exactly one of opportunity_id or legs")
        return self


class SimulateRequest(_TradeSource):
    team_id: UUID
    roster_version: int | None = None

    model_config = {
        "json_schema_extra": {
            "example": {
                "team_id": "00000000-0000-0000-0000-000000000000",
                "opportunity_id": None,
                "legs": [
                    {"action": "sell", "player_id": "00000000-0000-0000-0000-000000000001"},
                    {"action": "buy", "player_id": "00000000-0000-0000-0000-000000000002"},
                ],
                "roster_version": 1,
            }
        }
    }


class ExecuteRequest(_TradeSource):
    team_id: UUID
    roster_version: int = Field(
        description="Required here, unlike simulate. Mismatch -> 409 STALE_ROSTER_VERSION (D7)."
    )
    user_confirmation: Literal[True] = Field(
        description="Must be literally true. This makes an unconfirmed execute "
        "structurally impossible to express, so the human-in-the-loop guarantee "
        "lives in the schema rather than a runtime check somebody can forget."
    )
    idempotency_key: UUID

    model_config = {
        "json_schema_extra": {
            "example": {
                "team_id": "00000000-0000-0000-0000-000000000000",
                "opportunity_id": "opp_4f2a9c1e8b03",
                "legs": None,
                "roster_version": 1,
                "user_confirmation": True,
                "idempotency_key": "7d10ea31-1d0c-4f2f-8d58-3139af7336f3",
            }
        }
    }
