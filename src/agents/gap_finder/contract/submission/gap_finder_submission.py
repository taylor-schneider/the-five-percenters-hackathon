"""The terminal tool's argument model -- the Gap Finder's whole output."""

from __future__ import annotations

from pydantic import ConfigDict, Field

from ....data.tools import ToolArgs
from .coverage_note import CoverageNote
from .player_call import PlayerCall
from .position_call import PositionCall


class GapFinderSubmission(ToolArgs):
    """The terminal tool's arguments. This IS the model's output."""

    model_config = ConfigDict(extra="forbid")

    narrative: str = Field(
        min_length=80,
        max_length=2000,
        description=(
            "The squad-level read, in plain English, for a GM who will not look at a "
            "single chart. Where the money is going, where the value is, and the one "
            "thing you would fix first."
        ),
    )
    priorities: list[str] = Field(
        default_factory=list,
        max_length=5,
        description="Ordered, most urgent first. One line each, actionable.",
    )
    flagged_positions: list[PositionCall] = Field(default_factory=list, max_length=10)
    flagged_players: list[PlayerCall] = Field(default_factory=list, max_length=10)
    coverage_notes: list[CoverageNote] = Field(default_factory=list, max_length=4)
    confidence: float = Field(
        ge=0,
        le=1,
        description=(
            "Your certainty in this analysis given the data you saw. Thin league samples "
            "or a squad with unusual shape should pull this down."
        ),
    )
