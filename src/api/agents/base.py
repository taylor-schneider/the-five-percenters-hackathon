"""The agent seam.

The API owns HTTP, data access, pricing arithmetic, hard-rule validation, and
the transactional write. The agents own judgement. This file is the boundary
between the two, and it is the ONE file to change if the agent branch settles on
different contracts.

What an agent is handed, and what it must hand back:

    GapFinderAgent.analyze(ctx)  -> GapFinderVerdict
    OpportunityFinderAgent.find(ctx) -> list[ProposedOpportunity]
    TraderAgent.review(ctx)      -> TradeReview

Deliberately, agents do NOT return finished API responses:

* An Opportunity Finder returns *proposals* -- legs plus reasoning. The API
  prices each one through `toolbox.price_trade`, assigns the `opportunity_id`
  and `expires_at`, attaches the resulting `TradeImpact`, and caches it. So a
  proposal cannot carry made-up numbers into a response.
* A Gap Finder returns *judgements* -- which positions and players are a
  problem and why. The API attaches the measured benchmark metrics alongside.
* A Trader returns a *review*, not a write. Execution stays transactional and
  deterministic regardless of what the review says.

Implementations are resolved by `GM_AGENT_IMPL`:

    stub      -> agents.stub (default; no API calls, no key required)
    anthropic -> agents.anthropic_agents (lands from the agent branch)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable
from uuid import UUID

from ..core.config import get_settings
from ..models.domain import PlayerRef
from ..models.enums import AgentMode, HealthStatus, OpportunityType, Position, Severity
from ..models.requests import (
    Constraints,
    OpportunityConstraints,
    OpportunityFocus,
)
from ..repositories.store import Store


# --------------------------------------------------------------------------
# What an agent is handed
# --------------------------------------------------------------------------


@dataclass(slots=True)
class AgentContext:
    """Handle onto the data layer plus the request that triggered the run.

    An agent reaches data through `toolbox` functions taking this `store`, not
    by touching the repositories directly.
    """

    store: Store
    team_id: UUID
    roster_version: int
    trace_id: str = "unknown"


@dataclass(slots=True)
class GapFinderContext(AgentContext):
    constraints: Constraints = field(default_factory=Constraints)


@dataclass(slots=True)
class OpportunityFinderContext(AgentContext):
    focus: OpportunityFocus = field(default_factory=OpportunityFocus)
    constraints: OpportunityConstraints = field(default_factory=OpportunityConstraints)


@dataclass(slots=True)
class TraderContext(AgentContext):
    legs: list[dict[str, str]] = field(default_factory=list)
    opportunity_id: str | None = None


# --------------------------------------------------------------------------
# What an agent hands back
# --------------------------------------------------------------------------


@dataclass(slots=True)
class PositionJudgement:
    position: Position
    health_status: HealthStatus
    problem_score: float
    severity: Severity
    reasons: list[str]


@dataclass(slots=True)
class PlayerJudgement:
    player_id: UUID
    health_status: HealthStatus
    problem_score: float
    severity: Severity
    reasons: list[str]


@dataclass(slots=True)
class GapFinderVerdict:
    positions: list[PositionJudgement] = field(default_factory=list)
    players: list[PlayerJudgement] = field(default_factory=list)
    narrative: str | None = None


@dataclass(slots=True)
class ProposedOpportunity:
    """A trade the agent thinks is worth the GM's attention.

    `legs` carries actions and player ids only -- the API resolves the salaries
    and computes the impact, so a proposal can never smuggle in a price the
    agent invented.
    """

    type: OpportunityType
    legs: list[dict[str, str]]
    reasoning_summary: str
    reasoning_steps: list[str] = field(default_factory=list)
    risks: list[str] = field(default_factory=list)
    confidence: float = 0.5
    target_position: Position | None = None
    rank_hint: float | None = field(
        default=None,
        metadata={
            "note": "Optional agent-supplied ordering. The API still ranks by "
            "opportunity_score; this only breaks ties."
        },
    )


@dataclass(slots=True)
class TradeReview:
    approved: bool
    summary: str
    concerns: list[str] = field(default_factory=list)
    confidence: float = 0.5


# --------------------------------------------------------------------------
# Protocols
# --------------------------------------------------------------------------


@runtime_checkable
class GapFinderAgent(Protocol):
    name: str

    def analyze(self, ctx: GapFinderContext) -> GapFinderVerdict: ...


@runtime_checkable
class OpportunityFinderAgent(Protocol):
    name: str

    def find(self, ctx: OpportunityFinderContext) -> list[ProposedOpportunity]: ...


@runtime_checkable
class TraderAgent(Protocol):
    name: str

    def review(self, ctx: TraderContext) -> TradeReview: ...


@dataclass(slots=True)
class AgentBundle:
    gap_finder: GapFinderAgent
    opportunity_finder: OpportunityFinderAgent
    trader: TraderAgent
    impl: str
    model: str | None = None

    @property
    def mode(self) -> AgentMode:
        """What goes on every AgentMeta, so a consumer can tell placeholder
        output from real agent output."""
        return AgentMode.STUB if self.impl == "stub" else AgentMode.LLM

    def describe(self) -> dict[str, Any]:
        return {
            "impl": self.impl,
            "model": self.model,
            "gap_finder": self.gap_finder.name,
            "opportunity_finder": self.opportunity_finder.name,
            "trader": self.trader.name,
        }


class AgentsUnavailable(RuntimeError):
    """Raised when the configured implementation cannot be loaded."""


def get_agents() -> AgentBundle:
    """Resolve the configured agent implementation.

    The agent branch lands a module exposing `build_bundle() -> AgentBundle`;
    setting GM_AGENT_IMPL=anthropic picks it up with no other change here.
    """
    settings = get_settings()
    impl = settings.agent_impl.lower()

    if impl == "stub":
        from . import stub

        return stub.build_bundle()

    if impl == "anthropic":
        try:
            from . import anthropic_agents  # type: ignore[attr-defined]
        except ImportError as exc:
            raise AgentsUnavailable(
                "GM_AGENT_IMPL=anthropic but src/api/agents/anthropic_agents.py is "
                "not present yet. Merge the agent branch, or set GM_AGENT_IMPL=stub."
            ) from exc
        if not settings.anthropic_api_key:
            raise AgentsUnavailable(
                "GM_AGENT_IMPL=anthropic but ANTHROPIC_API_KEY is not set. Put it "
                "in .env (see .env.example)."
            )
        return anthropic_agents.build_bundle()

    raise AgentsUnavailable(
        f"Unknown GM_AGENT_IMPL={settings.agent_impl!r}. Expected 'stub' or 'anthropic'."
    )


__all__ = [
    "AgentBundle",
    "AgentContext",
    "AgentsUnavailable",
    "GapFinderAgent",
    "GapFinderContext",
    "GapFinderVerdict",
    "OpportunityFinderAgent",
    "OpportunityFinderContext",
    "PlayerJudgement",
    "PlayerRef",
    "PositionJudgement",
    "ProposedOpportunity",
    "TradeReview",
    "TraderAgent",
    "TraderContext",
    "get_agents",
]
