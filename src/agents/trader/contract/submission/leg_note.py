"""One per-player note on a trade leg, as the model authors it."""

from __future__ import annotations

from uuid import UUID

from pydantic import Field

from ....data.tools import ToolArgs


class LegNote(ToolArgs):
    player_id: UUID = Field(description="One of the players in the proposed trade.")
    commentary: str = Field(
        min_length=30,
        max_length=500,
        description=(
            "What this individual movement means: what the squad gains or loses at that "
            "position, and whether the price is right for what arrives or leaves."
        ),
    )
