"""One flagged player, as the model authors it."""

from __future__ import annotations

from uuid import UUID

from pydantic import Field

from ....data.tools import ToolArgs


class PlayerCall(ToolArgs):
    player_id: UUID = Field(
        description="Must be a player currently on this roster; copy the id from get_roster."
    )
    commentary: str = Field(
        min_length=40,
        max_length=700,
        description=(
            "Two to four sentences on this individual: what the salary buys against what "
            "the position returns, whether the sample behind their value is solid, and "
            "what the GM's realistic options are."
        ),
    )
    reasons: list[str] = Field(min_length=1, max_length=4)
