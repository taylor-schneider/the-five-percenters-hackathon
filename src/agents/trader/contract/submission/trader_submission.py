"""The terminal tool's argument model -- the Trader's whole output."""

from __future__ import annotations

from pydantic import ConfigDict, Field

from ....data.tools import ToolArgs
from ..verdict import Verdict
from .leg_note import LegNote


class TraderSubmission(ToolArgs):
    model_config = ConfigDict(extra="forbid")

    verdict: Verdict = Field(
        description=(
            "proceed when the trade is clearly worth doing; proceed_with_caution when it "
            "is defensible but carries a risk the GM must accept knowingly; "
            "do_not_proceed when you would advise against it. A trade the rules forbid is "
            "always do_not_proceed."
        )
    )
    headline: str = Field(
        min_length=20,
        max_length=200,
        description="One sentence a GM could read on a confirmation modal, with the figures.",
    )
    narrative: str = Field(
        min_length=80,
        max_length=1500,
        description=(
            "The case for or against, in three to six sentences. What the squad looks like "
            "afterwards, what the money buys, what it costs elsewhere, and what you would "
            "want to know that you do not."
        ),
    )
    leg_notes: list[LegNote] = Field(
        default_factory=list,
        max_length=8,
        description="Per-player commentary. Cover every leg of a swap.",
    )
    risks: list[str] = Field(
        default_factory=list,
        max_length=5,
        description=(
            "Judgement risks in the GM's terms. Rule violations are attached automatically; "
            "do not repeat them verbatim."
        ),
    )
    alternatives: list[str] = Field(
        default_factory=list,
        max_length=3,
        description=(
            "Better or safer moves you found while checking this one, one line each. "
            "Required in spirit when your verdict is do_not_proceed -- a GM told no wants "
            "to know what instead."
        ),
    )
    confidence: float = Field(ge=0, le=1, description="Your certainty in this verdict.")
