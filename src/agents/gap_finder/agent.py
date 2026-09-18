"""Gap Finder agent: which positions and players are a problem, and why.

Backs POST /api/v1/agents/gap-finder/analyze. The API's whole job is:

    run = gap_finder.analyze(store, request)
    return run.output.to_api_response(run.to_agent_meta())

Everything between those two lines -- tool loop, evidence gathering, joining the
model's judgement to the deterministic scores -- lives here.
"""

from __future__ import annotations

from typing import Any

from ...api.models.enums import AgentName, PositionGroup, group_of
from ...api.models.requests import GapFinderRequest
from ...api.repositories.store import Store, utcnow
from ..core.loop import ReActAgent
from ..core.tools import Tool, ToolBox
from ..core.trace import AgentRun
from ..data import metrics
from ..data.context import AgentDeps
from ..data.tools import (
    get_position_benchmarks,
    get_roster,
    get_team_overview,
    inspect_player,
)
from .contract import (
    CoverageFinding,
    GapFinderAnalysis,
    GapFinderSubmission,
    PlayerFinding,
    PositionFinding,
)
from .prompts import SYSTEM, build_task


def _submit(args: GapFinderSubmission, deps: AgentDeps) -> Any:  # pragma: no cover
    """Never runs. The loop returns as soon as a terminal tool's arguments
    validate -- the handler exists only so Tool stays one shape."""
    raise AssertionError("terminal tool handler is not executed")


submit_analysis = Tool(
    name="submit_analysis",
    description=(
        "Submit your finished analysis. Call this once, when your evidence supports your "
        "read. You supply judgement and commentary only -- scores, severities and euro "
        "figures are recomputed server-side from the same data you were shown."
    ),
    args_model=GapFinderSubmission,
    handler=_submit,
    terminal=True,
)


TOOLS = ToolBox(
    [
        get_team_overview,
        get_roster,
        get_position_benchmarks,
        inspect_player,
        submit_analysis,
    ]
)


def build_agent() -> ReActAgent:
    return ReActAgent(
        agent_name=AgentName.GAP_FINDER,
        system_prompt=SYSTEM,
        toolbox=TOOLS,
    )


def analyze(store: Store, request: GapFinderRequest) -> AgentRun[GapFinderAnalysis]:
    """Run the Gap Finder.

    Raises AgentUnavailable when no model is reachable and AgentFailed when the
    loop produced nothing usable. Both mean the same thing to the caller: fall
    back to gap_finder_service.analyze and report mode=heuristic.
    """
    deps = AgentDeps.build(store, request.team_id, request.constraints)
    agent = build_agent()

    run = agent.run(
        task=build_task(
            team_name=deps.team.name,
            roster_version=deps.team.roster_version,
            budget_cap=deps.budget_cap,
            minimums={g.value: n for g, n in deps.minimums.items()},
            cap_is_override=request.constraints.budget_cap is not None,
        ),
        deps=deps,
        input_payload=deps.snapshot(),
    )
    run.output = _assemble(deps, run.output)
    return run


# --------------------------------------------------------------------------
# Joining judgement to the numbers
# --------------------------------------------------------------------------


def _assemble(deps: AgentDeps, submission: GapFinderSubmission) -> GapFinderAnalysis:
    return GapFinderAnalysis(
        team_id=deps.team.id,
        roster_version=deps.team.roster_version,
        narrative=submission.narrative.strip(),
        priorities=[p.strip() for p in submission.priorities if p.strip()],
        flagged_positions=_positions(deps, submission),
        flagged_players=_players(deps, submission),
        coverage_warnings=_coverage(deps, submission),
        confidence=round(submission.confidence, 2),
        generated_at=utcnow(),
    )


def _positions(deps: AgentDeps, submission: GapFinderSubmission) -> list[PositionFinding]:
    findings: list[PositionFinding] = []
    seen = set()
    for call in submission.flagged_positions:
        if call.position in seen:
            continue  # the model occasionally flags the same slot twice
        seen.add(call.position)
        assessment = metrics.assess_position(deps, call.position)
        findings.append(
            PositionFinding(
                position=call.position,
                position_group=group_of(call.position),
                severity=assessment.severity,
                problem_score=assessment.problem_score,
                health_status=assessment.health_status,
                reasons=[r.strip() for r in call.reasons if r.strip()],
                metrics=assessment.metrics,
                commentary=call.commentary.strip(),
            )
        )
    return sorted(findings, key=lambda f: f.problem_score, reverse=True)


def _players(deps: AgentDeps, submission: GapFinderSubmission) -> list[PlayerFinding]:
    findings: list[PlayerFinding] = []
    seen = set()
    for call in submission.flagged_players:
        if call.player_id in seen:
            continue
        seen.add(call.player_id)
        assessment = metrics.assess_player(deps, call.player_id)
        if assessment is None:
            # The model cited someone who is not on this roster. Dropping the
            # finding is safer than inventing scores for it.
            continue
        findings.append(
            PlayerFinding(
                player=assessment.player_ref,
                severity=assessment.severity,
                problem_score=assessment.problem_score,
                health_status=assessment.health_status,
                reasons=[r.strip() for r in call.reasons if r.strip()],
                commentary=call.commentary.strip(),
            )
        )
    return sorted(findings, key=lambda f: f.problem_score, reverse=True)


def _coverage(deps: AgentDeps, submission: GapFinderSubmission) -> list[CoverageFinding]:
    """Shortfalls are computed, not claimed -- the model only supplies the note.

    A group the model wrote about that is not actually short is dropped; a group
    that is short but the model ignored still appears, without commentary.
    """
    notes: dict[PositionGroup, str] = {
        note.position_group: note.commentary.strip() for note in submission.coverage_notes
    }
    return [
        CoverageFinding(
            position_group=warning.position_group,
            required=warning.required,
            actual=warning.actual,
            severity=warning.severity,
            commentary=notes.get(warning.position_group),
        )
        for warning in metrics.coverage_warnings(deps)
    ]
