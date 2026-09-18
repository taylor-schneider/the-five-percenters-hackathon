"""One proposed trade, as the model authors it."""

from __future__ import annotations

from pydantic import Field

from .....api.models.domain import TradeLegRequest
from .....api.models.enums import OpportunityType, Position
from ....data.tools import ToolArgs


class OpportunityCall(ToolArgs):
    type: OpportunityType = Field(
        description="buy adds a player, sell removes one, swap does both in one move."
    )
    target_position: Position | None = Field(
        default=None, description="The slot this move is meant to improve."
    )
    legs: list[TradeLegRequest] = Field(
        min_length=1,
        max_length=6,
        description=(
            "Exactly the legs you validated with simulate_trade. If you did not simulate "
            "it, do not submit it."
        ),
    )
    headline: str = Field(
        min_length=20,
        max_length=200,
        description=(
            "One sentence naming the players and the trade-off, e.g. "
            '"Replace T. Alvarez with M. Sorensen at CB: EUR 0.9M cheaper, +1.4 team score."'
        ),
    )
    commentary: str = Field(
        min_length=60,
        max_length=900,
        description=(
            "Two to four sentences of judgement for the GM. Why this move and not the "
            "obvious alternative, what the squad looks like afterwards, and what would "
            "make you change your mind. Do not restate the headline."
        ),
    )
    reasoning_steps: list[str] = Field(
        min_length=1,
        max_length=6,
        description="How you got here, one step per line, each tied to something a tool told you.",
    )
    risks: list[str] = Field(
        default_factory=list,
        max_length=4,
        description=(
            "What could go wrong, in the GM's terms. Rule violations are added "
            "automatically -- use this for judgement risks like a thin sample or losing "
            "depth at a position."
        ),
    )
    confidence: float = Field(
        ge=0,
        le=1,
        description=(
            "How sure you are this is a good move, separate from how good it looks. A "
            "clearly profitable trade resting on 6 appearances is high value, low confidence."
        ),
    )
