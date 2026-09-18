"""The terminal tool's argument model -- the Opportunity Finder's whole output."""

from __future__ import annotations

from pydantic import ConfigDict, Field

from ....data.tools import ToolArgs
from .opportunity_call import OpportunityCall
from .rejected_note import RejectedNote


class OpportunityFinderSubmission(ToolArgs):
    model_config = ConfigDict(extra="forbid")

    narrative: str = Field(
        min_length=60,
        max_length=1500,
        description=(
            "Your read on what this market offers this squad: the theme of the moves you "
            "are recommending, and what you could not solve."
        ),
    )
    opportunities: list[OpportunityCall] = Field(
        default_factory=list,
        max_length=20,
        description=(
            "Ranked is not required -- the server ranks them by opportunity_score. An "
            "empty list is a valid answer when nothing clears the constraints."
        ),
    )
    considered_and_rejected: list[RejectedNote] = Field(
        default_factory=list,
        max_length=6,
        description=(
            "The near misses. This is what makes an empty or short list credible to a GM."
        ),
    )
    confidence: float = Field(ge=0, le=1, description="Your certainty in the set as a whole.")
