"""Trader agent: the last opinion before a trade is committed.

Backs POST /api/v1/agents/trader/simulate (as the reasoning layer over the
deterministic impact) and gives /execute something to freeze into
TradeRecord.rationale_snapshot.

    run = trader.assess(store, simulate_request)
    return run.output.to_api_response(run.to_agent_meta())

The impact block is produced by trader_service.simulate before the model is
called, and handed to it as evidence. The agent's contribution is the verdict
and the explanation -- it cannot change a single euro of the simulation, which
is why a wrong opinion is a bad recommendation rather than a bad trade.
"""

from __future__ import annotations

from typing import Any

from ...api.models.enums import AgentName, Severity
from ...api.models.requests import SimulateRequest
from ...api.repositories.store import Store, utcnow
from ...api.services import trader_service
from ...api.services.opportunity_cache import get_opportunity_cache
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
from .contract import AssessedLeg, TradeAssessment, TraderSubmission
from .prompts import SYSTEM, build_task


def _submit(args: TraderSubmission, deps: AgentDeps) -> Any:  # pragma: no cover
    raise AssertionError("terminal tool handler is not executed")


submit_assessment = Tool(
    name="submit_assessment",
    description=(
        "Submit your verdict on the proposed trade. Call this once. The impact figures are "
        "already fixed by the simulation -- what you are submitting is judgement, "
        "commentary and a recommendation."
    ),
    args_model=TraderSubmission,
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
        submit_assessment,
    ]
)


def build_agent() -> ReActAgent:
    return ReActAgent(
        agent_name=AgentName.TRADER,
        system_prompt=SYSTEM,
        toolbox=TOOLS,
    )


def assess(store: Store, request: SimulateRequest) -> AgentRun[TradeAssessment]:
    """Simulate the trade deterministically, then have the agent judge it.

    Order matters. The simulation runs first, so a structurally broken request
    (unknown player, expired opportunity, stale roster) fails fast with the
    api.md error it deserves and never costs a model call. An invalid-but-
    well-formed trade still goes to the agent: `impact.valid = false` is a 200
    with violations (api.md 5.10), and explaining why the Execute button is
    disabled is exactly what the GM needs at that moment.
    """
    simulation = trader_service.simulate(store, request)

    deps = AgentDeps.build(store, request.team_id)
    agent = build_agent()

    run = agent.run(
        task=build_task(
            team_name=deps.team.name,
            roster_version=deps.team.roster_version,
            budget_cap=deps.budget_cap,
            minimums={g.value: n for g, n in deps.minimums.items()},
            source=_describe_source(request),
            simulation=_simulation_brief(simulation),
            opportunity_rationale=_opportunity_rationale(request, deps),
        ),
        deps=deps,
        input_payload={
            **deps.snapshot(),
            "opportunity_id": request.opportunity_id,
            "legs": [leg.model_dump(mode="json") for leg in (request.legs or [])],
        },
    )
    run.output = _assemble(deps, simulation, run.output)
    return run


# --------------------------------------------------------------------------


def _describe_source(request: SimulateRequest) -> str:
    if request.opportunity_id:
        return f"a cached Opportunity Finder recommendation ({request.opportunity_id})"
    return "hand-built by the GM in the trade builder"


def _opportunity_rationale(request: SimulateRequest, deps: AgentDeps) -> str | None:
    """The Opportunity Finder's own argument, when this trade came from one.

    Withholding it would be cleaner in theory -- an independent reviewer -- but
    a GM comparing two screens wants to know whether the Trader engaged with
    the original case or just re-derived a different one.
    """
    if not request.opportunity_id:
        return None
    try:
        opportunity = get_opportunity_cache().get(
            request.opportunity_id, deps.team.id, deps.team.roster_version
        )
    except Exception:
        return None
    lines = [opportunity.reasoning_summary]
    lines += [f"- {step}" for step in opportunity.reasoning_steps]
    if opportunity.risks:
        lines.append("Risks already noted: " + "; ".join(opportunity.risks))
    return "\n".join(lines)


def _simulation_brief(simulation) -> dict[str, Any]:
    """The deterministic result, flattened for the prompt.

    Same shape the simulate_trade tool returns, so the agent reads one format
    whether the numbers came from the task or from a tool it called.
    """
    impact = simulation.impact
    return {
        "valid": impact.valid,
        "violations": [
            {"code": v.code, "severity": v.severity.value, "message": v.message}
            for v in impact.violations
        ],
        "projected_cost_delta": impact.projected_cost_delta,
        "projected_value_delta": impact.projected_value_delta,
        "current": {
            "team_cost": impact.current_metrics.team_cost,
            "team_score": impact.current_metrics.team_score,
            "squad_size": impact.current_metrics.squad_size,
        },
        "post_trade": {
            "team_cost": impact.post_trade_metrics.team_cost,
            "team_score": impact.post_trade_metrics.team_score,
            "budget_remaining": impact.post_trade_metrics.budget_remaining,
            "squad_size": impact.post_trade_metrics.squad_size,
        },
        "position_group_counts_after": {
            g.value: n for g, n in impact.position_group_counts_after.items()
        },
        "legs": [
            {
                "action": leg.action.value,
                "player": leg.player.name,
                "player_id": str(leg.player.player_id),
                "position": leg.player.position.value,
                "cost_delta": leg.cost_delta,
                "value_delta": leg.value_delta,
            }
            for leg in simulation.legs
        ],
    }


def _assemble(
    deps: AgentDeps, simulation, submission: TraderSubmission
) -> TradeAssessment:
    notes = {note.player_id: note.commentary.strip() for note in submission.leg_notes}
    verdict = submission.verdict
    if not simulation.impact.valid and verdict != "do_not_proceed":
        # The rules already decided this one. An agent that says "proceed" over
        # a hard violation would put a recommendation on screen next to a
        # disabled button, which is worse than no recommendation.
        verdict = "do_not_proceed"

    return TradeAssessment(
        team_id=deps.team.id,
        roster_version=deps.team.roster_version,
        verdict=verdict,
        headline=submission.headline.strip(),
        narrative=submission.narrative.strip(),
        risks=_risks(submission, simulation.impact),
        alternatives=[a.strip() for a in submission.alternatives if a.strip()],
        confidence=round(submission.confidence, 2),
        impact=simulation.impact,
        legs=[
            AssessedLeg(leg=leg, commentary=notes.get(leg.player.player_id))
            for leg in simulation.legs
        ],
        generated_at=utcnow(),
    )


def _risks(submission: TraderSubmission, impact) -> list[str]:
    risks = [r.strip() for r in submission.risks if r.strip()]
    for violation in impact.violations:
        if violation.severity is not Severity.HIGH and violation.message not in risks:
            risks.append(violation.message)
    return risks
