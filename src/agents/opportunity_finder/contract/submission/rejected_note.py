"""A near miss, as the model authors it."""

from __future__ import annotations

from pydantic import Field

from ....data.tools import ToolArgs


class RejectedNote(ToolArgs):
    summary: str = Field(
        min_length=15, max_length=200, description="The move you considered, in one line."
    )
    why_rejected: str = Field(
        min_length=15,
        max_length=300,
        description="What ruled it out -- a violation, the cap, or a judgement call.",
    )
