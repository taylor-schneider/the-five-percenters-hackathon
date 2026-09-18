"""What the agent returns: api.md 5.9's response plus commentary and rejects."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import Field

from .....api.models.domain import AgentMeta, ApiModel, Opportunity
from .....api.models.requests import OpportunityFocus
from .....api.models.responses import OpportunityFinderResponse
from .opportunity_finding import OpportunityFinding
from .rejected_opportunity import RejectedOpportunity


class OpportunityPlan(ApiModel):
    team_id: UUID
    roster_version: int
    narrative: str
    opportunities: list[OpportunityFinding] = Field(default_factory=list)
    considered_and_rejected: list[RejectedOpportunity] = Field(default_factory=list)
    candidates_evaluated: int = Field(
        description="Trades the agent actually simulated, so 'no viable moves' can be "
        "distinguished from 'nothing was tried'."
    )
    confidence: float = Field(ge=0, le=1)
    generated_at: datetime

    def to_api_response(
        self, focus: OpportunityFocus, agent_meta: AgentMeta
    ) -> OpportunityFinderResponse:
        """Narrow to the frozen api.md 5.9 shape.

        Per-opportunity commentary and the rejected list are dropped -- see
        README.md for the proposed api.md delta that would keep them.
        """
        return OpportunityFinderResponse(
            team_id=self.team_id,
            focus=focus,
            opportunities=[
                Opportunity.model_validate(o.model_dump(exclude={"commentary"}))
                for o in self.opportunities
            ],
            candidates_evaluated=self.candidates_evaluated,
            roster_version=self.roster_version,
            agent_meta=agent_meta,
            generated_at=self.generated_at,
        )
