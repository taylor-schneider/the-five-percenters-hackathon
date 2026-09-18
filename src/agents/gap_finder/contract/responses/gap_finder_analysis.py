"""What the agent returns: api.md 5.8's response plus commentary."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import Field

from .....api.models.domain import AgentMeta, ApiModel
from .....api.models.responses import (
    CoverageWarning,
    FlaggedPlayer,
    FlaggedPosition,
    GapFinderResponse,
)
from .coverage_finding import CoverageFinding
from .player_finding import PlayerFinding
from .position_finding import PositionFinding


class GapFinderAnalysis(ApiModel):
    team_id: UUID
    roster_version: int
    narrative: str
    priorities: list[str] = Field(default_factory=list)
    flagged_positions: list[PositionFinding] = Field(default_factory=list)
    flagged_players: list[PlayerFinding] = Field(default_factory=list)
    coverage_warnings: list[CoverageFinding] = Field(default_factory=list)
    confidence: float = Field(ge=0, le=1)
    generated_at: datetime

    def to_api_response(self, agent_meta: AgentMeta) -> GapFinderResponse:
        """Narrow to the frozen api.md 5.8 shape.

        Commentary is dropped here, which is exactly the gap worth closing: the
        agent's whole reason for existing does not fit through the current
        response model. Until api.md gains the field, an endpoint that wants the
        commentary should serve this object instead.
        """
        return GapFinderResponse(
            team_id=self.team_id,
            flagged_positions=[
                FlaggedPosition.model_validate(f.model_dump(exclude={"commentary"}))
                for f in self.flagged_positions
            ],
            flagged_players=[
                FlaggedPlayer.model_validate(f.model_dump(exclude={"commentary"}))
                for f in self.flagged_players
            ],
            coverage_warnings=[
                CoverageWarning.model_validate(w.model_dump(exclude={"commentary"}))
                for w in self.coverage_warnings
            ],
            roster_version=self.roster_version,
            agent_meta=agent_meta,
            generated_at=self.generated_at,
        )
