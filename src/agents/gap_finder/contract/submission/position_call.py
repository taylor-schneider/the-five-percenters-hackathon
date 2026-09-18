"""One flagged position, as the model authors it."""

from __future__ import annotations

from pydantic import Field

from .....api.models.enums import Position
from ....data.tools import ToolArgs


class PositionCall(ToolArgs):
    position: Position = Field(description="The slot you are flagging, e.g. CB.")
    commentary: str = Field(
        min_length=40,
        max_length=700,
        description=(
            "Two to four sentences for the GM. Say what the numbers mean, not what they "
            "are: why this position is a problem now, what it is costing the squad, and "
            "how confident the evidence makes you. Quote specific figures from the tools."
        ),
    )
    reasons: list[str] = Field(
        min_length=1,
        max_length=4,
        description=(
            "Short evidence bullets, one clause each, each tied to a number you actually "
            'read, e.g. "value 12.4% below the league average at CB".'
        ),
    )
