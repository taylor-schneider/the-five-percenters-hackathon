"""Opportunity Finder agent: which trades to put in front of the GM.

Backs POST /api/v1/agents/opportunity-finder/find. The API's job is:

    run = opportunity_finder.find(store, request)
    return run.output.to_api_response(request.focus, run.to_agent_meta())

The agent proposes; trader_service prices and validates; scoring.py ranks. A
trade the model believes in but cannot simulate never reaches the response.

Note on roster_version: the caller checks it (409 STALE_ROSTER_VERSION) before
invoking. The agent reasons over whatever store state it is handed -- burning a
model call to re-discover that the dashboard is stale is the wrong order.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from ...api.core.config import get_settings
from ...api.core.errors import AppError
from ...api.models.enums import AgentName, Severity
from ...api.models.requests import OpportunityFinderRequest
from ...api.repositories.store import Store, utcnow
from ...api.services import scoring, trader_service
from ...api.services.opportunity_cache import get_opportunity_cache, new_opportunity_id
from ..core.loop import ReActAgent
from ..core.tools import Tool, ToolBox
from ..core.trace import AgentRun
from ..data.context import AgentDeps
from ..data.tools import (
    get_position_benchmarks,
    get_roster,
    get_team_overview,
    inspect_player,
    search_market,
    simulate_trade,
)
from .contract import (
    OpportunityCall,
    OpportunityFinderSubmission,
    OpportunityFinding,
    OpportunityPlan,
    RejectedOpportunity,
)
from .prompts import SYSTEM, build_task

#: Confidence floor/ceiling for the appearance-derived half of the blend, and
#: the full season that counts as a complete sample. Mirrors the heuristic path
#: in opportunity_finder_service so the two agree about what "thin data" means.
_FULL_SEASON = 38
_MIN_DATA_CONFIDENCE = 0.30
_MAX_DATA_CONFIDENCE = 0.95
#: No incoming player means no incoming-performance uncertainty: a sale's
#: outcome is known the moment it clears.
_SELL_DATA_CONFIDENCE = 0.88


def _submit(args: OpportunityFinderSubmission, deps: AgentDeps) -> Any:  # pragma: no cover
    raise AssertionError("terminal tool handler is not executed")


submit_opportunities = Tool(
    name="submit_opportunities",
    description=(
        "Submit the trades worth putting in front of the GM. Call this once. Every leg is "
        "re-priced and re-validated server-side, and the ranking is recomputed -- submit "
        "only trades you have already simulated."
    ),
    args_model=OpportunityFinderSubmission,
    handler=_submit,
    terminal=True,
)


TOOLS = ToolBox(
    [
        get_team_overview,
        get_roster,
        get_position_benchmarks,
        inspect_player,
        search_market,
        simulate_trade,
        submit_opportunities,
    ]
)


def build_agent() -> ReActAgent:
    return ReActAgent(
        agent_name=AgentName.OPPORTUNITY_FINDER,
        system_prompt=SYSTEM,
        toolbox=TOOLS,
    )


def find(
    store: Store,
    request: OpportunityFinderRequest,
    *,
    cache: bool = True,
) -> AgentRun[OpportunityPlan]:
    """Run the Opportunity Finder.

    `cache=True` registers each opportunity in the TTL cache so
    trader/execute can later be called with just an `opportunity_id`
    (api.md 3.11). Turn it off for evals and dry runs.
    """
    deps = AgentDeps.build(store, request.team_id, request.constraints)
    agent = build_agent()

    focus_players = [
        f"{deps.store.get_player(pid).name} ({pid})"
        for pid in request.focus.player_ids
        if deps.store.get_player(pid) is not None
    ]

    run = agent.run(
        task=build_task(
            team_name=deps.team.name,
            roster_version=deps.team.roster_version,
            budget_cap=deps.budget_cap,
            minimums={g.value: n for g, n in deps.minimums.items()},
            focus_positions=[p.value for p in request.focus.positions],
            focus_players=focus_players,
            types=[t.value for t in request.focus.types],
            max_results=request.constraints.max_results,
            max_cost_increase=request.constraints.max_cost_increase,
            min_value_gain=request.constraints.min_value_gain,
        ),
        deps=deps,
        input_payload={
            **deps.snapshot(),
            "focus": request.focus.model_dump(mode="json"),
            "constraints": request.constraints.model_dump(mode="json"),
        },
    )

    plan = _assemble(deps, request, run.output)
    run.output = plan
    if cache and plan.opportunities:
        get_opportunity_cache().put_many(
            list(plan.opportunities), deps.team.id, deps.team.roster_version
        )
    return run


# --------------------------------------------------------------------------
# Re-pricing, filtering, ranking
# --------------------------------------------------------------------------


class _Priced:
    __slots__ = ("call", "legs", "impact", "confidence", "risk", "risks")

    def __init__(self, call, legs, impact, confidence, risk, risks):
        self.call = call
        self.legs = legs
        self.impact = impact
        self.confidence = confidence
        self.risk = risk
        self.risks = risks


def _assemble(
    deps: AgentDeps,
    request: OpportunityFinderRequest,
    submission: OpportunityFinderSubmission,
) -> OpportunityPlan:
    priced: list[_Priced] = []
    rejected = [
        RejectedOpportunity(summary=n.summary, why_rejected=n.why_rejected)
        for n in submission.considered_and_rejected
    ]
    evaluated = 0

    for call in submission.opportunities:
        evaluated += 1
        try:
            trader_service.validate_leg_shape(call.legs)
            resolved = trader_service.resolve_legs(deps.store, deps.team, call.legs)
            impact = trader_service.compute_impact(
                deps.store, deps.team, resolved, deps.minimums
            )
        except AppError as exc:
            # The model proposed something that no longer prices -- a consumed
            # listing, a player it misremembered. It is not a recommendation.
            rejected.append(
                RejectedOpportunity(
                    summary=call.headline, why_rejected=f"{exc.code.value}: {exc.message}"
                )
            )
            continue

        blocked = _blocking_reason(impact, request)
        if blocked is not None:
            rejected.append(RejectedOpportunity(summary=call.headline, why_rejected=blocked))
            continue

        confidence, risk = _confidence(call, resolved)
        priced.append(
            _Priced(
                call=call,
                legs=[leg.model for leg in resolved],
                impact=impact,
                confidence=confidence,
                risk=risk,
                risks=_risks(call, impact),
            )
        )

    return OpportunityPlan(
        team_id=deps.team.id,
        roster_version=deps.team.roster_version,
        narrative=submission.narrative.strip(),
        opportunities=_rank(priced, request.constraints.max_results),
        considered_and_rejected=rejected,
        candidates_evaluated=evaluated,
        confidence=round(submission.confidence, 2),
        generated_at=utcnow(),
    )


def _blocking_reason(impact, request: OpportunityFinderRequest) -> str | None:
    """The constraints are hard filters (api.md 5.9), enforced here rather than
    trusted to the prompt."""
    if not impact.valid:
        blocker = next(v for v in impact.violations if v.severity is Severity.HIGH)
        return f"{blocker.code}: {blocker.message}"
    constraints = request.constraints
    if (
        constraints.max_cost_increase is not None
        and impact.projected_cost_delta > constraints.max_cost_increase
    ):
        return (
            f"salary would rise EUR {impact.projected_cost_delta:,}, above the "
            f"EUR {constraints.max_cost_increase:,} limit"
        )
    if (
        constraints.min_value_gain is not None
        and impact.projected_value_delta < constraints.min_value_gain
    ):
        return (
            f"team score gain {impact.projected_value_delta:+.1f} is below the "
            f"{constraints.min_value_gain:+.1f} floor"
        )
    return None


def _confidence(call: OpportunityCall, resolved) -> tuple[float, float]:
    """Blend the model's certainty with the sample behind the incoming player.

    Neither number alone is honest: the model can be confident about six
    appearances, and a full season of data says nothing about whether the move
    is wise. The mean of the two moves both ways and stays explainable.
    """
    appearances = [leg.appearances for leg in resolved if leg.action.is_incoming]
    if appearances:
        data_confidence = max(
            _MIN_DATA_CONFIDENCE, min(_MAX_DATA_CONFIDENCE, min(appearances) / _FULL_SEASON)
        )
    else:
        data_confidence = _SELL_DATA_CONFIDENCE
    confidence = round((call.confidence + data_confidence) / 2, 2)
    return confidence, round(1.0 - confidence, 2)


def _risks(call: OpportunityCall, impact) -> list[str]:
    """The model's judgement risks plus every soft violation the simulation
    raised. Soft violations never block, so if they are not surfaced here they
    are not surfaced at all."""
    risks = [r.strip() for r in call.risks if r.strip()]
    for violation in impact.violations:
        if violation.severity is not Severity.HIGH and violation.message not in risks:
            risks.append(violation.message)
    return risks


def _rank(priced: list[_Priced], max_results: int) -> list[OpportunityFinding]:
    if not priced:
        return []

    scores = scoring.opportunity_scores(
        value_gains=[p.impact.projected_value_delta for p in priced],
        cost_savings=[-p.impact.projected_cost_delta for p in priced],
        risks=[p.risk for p in priced],
    )
    expires_at = utcnow() + timedelta(seconds=get_settings().opportunity_ttl_seconds)

    ranked = sorted(zip(priced, scores, strict=True), key=lambda pair: pair[1], reverse=True)
    return [
        OpportunityFinding(
            opportunity_id=new_opportunity_id(),
            type=item.call.type,
            target_position=item.call.target_position,
            opportunity_score=score,
            confidence=item.confidence,
            legs=item.legs,
            impact=item.impact,
            risks=item.risks,
            reasoning_summary=item.call.headline.strip(),
            reasoning_steps=[s.strip() for s in item.call.reasoning_steps if s.strip()],
            commentary=item.call.commentary.strip(),
            expires_at=expires_at,
        )
        for item, score in ranked[:max_results]
    ]
