"""What the agent returns: its judgement joined to the authoritative TradeImpact."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import Field

from .....api.models.domain import AgentMeta, ApiModel, TradeImpact
from .....api.models.responses import SimulateResponse
from ..verdict import Verdict
from .assessed_leg import AssessedLeg


class TradeAssessment(ApiModel):
    team_id: UUID
    roster_version: int
    verdict: Verdict
    headline: str
    narrative: str
    risks: list[str] = Field(default_factory=list)
    alternatives: list[str] = Field(default_factory=list)
    confidence: float = Field(ge=0, le=1)
    impact: TradeImpact = Field(
        description="From trader_service.simulate. Authoritative, never model-authored."
    )
    legs: list[AssessedLeg] = Field(default_factory=list)
    generated_at: datetime

    @property
    def blocks_execution(self) -> bool:
        """True when the rules forbid the trade.

        Note what this does NOT say: a do_not_proceed verdict is advice, not a
        veto. The human-in-the-loop gate belongs to the GM, and an agent that
        can silently refuse a legal trade is a worse product than one that
        argues against it and loses.
        """
        return not self.impact.valid

    def to_api_response(self, agent_meta: AgentMeta) -> SimulateResponse:
        """Narrow to the frozen api.md 5.10 shape.

        Everything the agent added -- verdict, narrative, per-leg commentary --
        is dropped here. For the demo that matters, serve this object instead;
        see README.md for the proposed api.md delta.
        """
        return SimulateResponse(
            impact=self.impact,
            legs=[assessed.leg for assessed in self.legs],
            agent_meta=agent_meta,
        )
