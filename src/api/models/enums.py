"""Enumerations from api.md section 3.1.

These are the single source of truth for every categorical value in the API.
"""

from __future__ import annotations

from enum import StrEnum


class Position(StrEnum):
    """Benchmark level (D5).

    Collapsed to the four buckets the source data actually carries, so Position
    and PositionGroup hold the same value in v1. Both are still carried on the
    wire, so re-expanding to specific slots later is a data change in
    data/positions.csv, not an API change.
    """

    GK = "GK"
    DEF = "DEF"
    MID = "MID"
    FWD = "FWD"


class PositionGroup(StrEnum):
    """Coarse bucket. Squad minimums are enforced at this level (D5)."""

    GK = "GK"
    DEF = "DEF"
    MID = "MID"
    FWD = "FWD"


class HealthStatus(StrEnum):
    """Pitch-map traffic light."""

    GREEN = "green"
    WHITE = "white"
    RED = "red"


class Severity(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class OpportunityType(StrEnum):
    BUY = "buy"
    SELL = "sell"
    SWAP = "swap"


class TradeAction(StrEnum):
    BUY = "buy"
    SELL = "sell"
    SWAP_IN = "swap_in"
    SWAP_OUT = "swap_out"

    @property
    def is_incoming(self) -> bool:
        """True when this action brings a player onto the roster."""
        return self in (TradeAction.BUY, TradeAction.SWAP_IN)

    @property
    def is_outgoing(self) -> bool:
        """True when this action removes a player from the roster."""
        return self in (TradeAction.SELL, TradeAction.SWAP_OUT)


class TradeStatus(StrEnum):
    PROPOSED = "proposed"
    EXECUTED = "executed"
    REJECTED = "rejected"
    FAILED = "failed"


class InsightType(StrEnum):
    PROBLEM_FLAG = "problem_flag"
    RECOMMENDATION = "recommendation"
    RISK_NOTE = "risk_note"


class AgentMode(StrEnum):
    HEURISTIC = "heuristic"
    LLM = "llm"


class AgentName(StrEnum):
    GAP_FINDER = "gap_finder"
    OPPORTUNITY_FINDER = "opportunity_finder"
    TRADER = "trader"


#: Fixed position -> group mapping (api.md section 3.1). Applied server-side;
#: clients never send a position_group.
POSITION_GROUP: dict[Position, PositionGroup] = {
    Position.GK: PositionGroup.GK,
    Position.DEF: PositionGroup.DEF,
    Position.MID: PositionGroup.MID,
    Position.FWD: PositionGroup.FWD,
}


def group_of(position: Position) -> PositionGroup:
    return POSITION_GROUP[position]


# Pitch coordinates and squad minimums live in data/positions.csv and are loaded
# into PositionRecord -- see src/data_models/position.py.
