"""Enumerations from api.md section 3.1.

These are the single source of truth for every categorical value in the API.
"""

from __future__ import annotations

from enum import StrEnum


class Position(StrEnum):
    """Benchmark level (D5).

    Collapsed to the four buckets the supplied data carries, so Position and
    PositionGroup hold the same value. Both stay on the wire, so re-expanding
    to specific slots later is a change to data/positions.csv, not to the API.
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
    """Which implementation produced a result. Surfaced on every agent response
    so a consumer can tell placeholder output from real agent output."""

    STUB = "stub"
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


#: Normalised pitch coordinates per position for the Stage 1 pitch map.
#: Origin is top-left; y=0 is the team's own goal line.
PITCH_COORDINATES: dict[Position, tuple[float, float]] = {
    Position.GK: (0.50, 0.08),
    Position.DEF: (0.50, 0.32),
    Position.MID: (0.50, 0.58),
    Position.FWD: (0.50, 0.84),
}

#: Slot order for the default formation. v1 seeds everything as 4-3-3; adding a
#: formation later is a data change, not a frontend change.
FORMATIONS: dict[str, list[Position]] = {
    "4-3-3": [Position.GK, Position.DEF, Position.MID, Position.FWD],
}
