"""One position-group shortfall, as the model authors it."""

from __future__ import annotations

from pydantic import Field

from .....api.models.enums import PositionGroup
from ....data.tools import ToolArgs


class CoverageNote(ToolArgs):
    position_group: PositionGroup
    commentary: str = Field(
        min_length=30,
        max_length=500,
        description="What the shortfall means in practice -- injury exposure, rotation, "
        "which slot to fill first.",
    )
