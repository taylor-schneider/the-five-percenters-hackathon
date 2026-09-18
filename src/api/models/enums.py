"""Enumerations from api.md section 3.1.

These are the single source of truth for every categorical value in the API.
"""

from __future__ import annotations

from enum import StrEnum


class Position(StrEnum):
    """Specific pitch slot. Benchmarks are computed at this level (D5)."""

    GK = "GK"
    RB = "RB"
    CB = "CB"
    LB = "LB"
    CDM = "CDM"
    CM = "CM"
    CAM = "CAM"
    LW = "LW"
    RW = "RW"
    ST = "ST"


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
    Position.RB: PositionGroup.DEF,
    Position.CB: PositionGroup.DEF,
    Position.LB: PositionGroup.DEF,
    Position.CDM: PositionGroup.MID,
    Position.CM: PositionGroup.MID,
    Position.CAM: PositionGroup.MID,
    Position.LW: PositionGroup.FWD,
    Position.RW: PositionGroup.FWD,
    Position.ST: PositionGroup.FWD,
}


def group_of(position: Position) -> PositionGroup:
    return POSITION_GROUP[position]


#: Normalised pitch coordinates per position for the Stage 1 pitch map.
#: Origin is top-left; y=0 is the team's own goal line.
PITCH_COORDINATES: dict[Position, tuple[float, float]] = {
    Position.GK: (0.50, 0.06),
    Position.LB: (0.15, 0.24),
    Position.CB: (0.50, 0.20),
    Position.RB: (0.85, 0.24),
    Position.CDM: (0.50, 0.40),
    Position.CM: (0.28, 0.50),
    Position.CAM: (0.72, 0.50),
    Position.LW: (0.18, 0.75),
    Position.ST: (0.50, 0.84),
    Position.RW: (0.82, 0.75),
}

#: Slot order for the default formation. v1 seeds everything as 4-3-3; adding a
#: formation later is a data change, not a frontend change.
FORMATIONS: dict[str, list[Position]] = {
    "4-3-3": [
        Position.GK,
        Position.LB,
        Position.CB,
        Position.RB,
        Position.CDM,
        Position.CM,
        Position.CAM,
        Position.LW,
        Position.ST,
        Position.RW,
    ],
}
