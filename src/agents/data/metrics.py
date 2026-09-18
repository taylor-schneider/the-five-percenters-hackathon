"""Deterministic assembly of the numbers an agent is allowed to cite.

The division of labour in this package: the model chooses WHICH positions,
players and trades matter and writes the commentary; this module produces every
score, euro and severity attached to that choice. A submission naming a position
is joined against these functions before it reaches the API, so a hallucinated
number cannot survive the trip.

All formulas come from services/scoring.py -- api.md section 4 has exactly one
implementation and this is not a second one.
"""

from __future__ import annotations

import statistics
from uuid import UUID

from ...api.models.enums import Position, PositionGroup, Severity, group_of
from ...api.models.responses import (
    CoverageWarning,
    FlaggedPositionMetrics,
)
from ...api.services import scoring, team_service
from .context import AgentDeps


class PositionAssessment:
    """Scores for one position slot on one team."""

    __slots__ = ("position", "problem_score", "health_status", "severity", "metrics", "occupants")

    def __init__(
        self,
        position: Position,
        problem_score: float,
        health_status,
        severity: Severity,
        metrics: FlaggedPositionMetrics,
        occupants: int,
    ) -> None:
        self.position = position
        self.problem_score = problem_score
        self.health_status = health_status
        self.severity = severity
        self.metrics = metrics
        self.occupants = occupants


def assess_position(deps: AgentDeps, position: Position) -> PositionAssessment:
    league = deps.league
    occupants = [e for e in deps.roster if e.position == position]
    counts = deps.group_counts()
    penalty = scoring.coverage_penalty_for(position, len(occupants), counts, deps.minimums)

    if occupants:
        team_avg_cost = int(round(statistics.fmean([e.cost for e in occupants])))
        team_avg_value = round(statistics.fmean([e.value_score for e in occupants]), 1)
        value_pct = statistics.fmean(
            [league.value_percentile(position, e.value_score) for e in occupants]
        )
        efficiency = statistics.fmean(
            [league.cost_efficiency(e.value_score, e.cost) for e in occupants]
        )
    else:
        # An unfilled slot has nobody to score, but it is still a gap -- the
        # coverage penalty is what carries it.
        team_avg_cost, team_avg_value, value_pct, efficiency = 0, 0.0, 0.0, 0.0

    score = scoring.problem_score(value_pct, efficiency, penalty)
    return PositionAssessment(
        position=position,
        problem_score=score,
        health_status=scoring.health_status(score),
        severity=scoring.severity_from_score(score),
        metrics=FlaggedPositionMetrics(
            team_avg_cost=team_avg_cost,
            team_avg_value=team_avg_value,
            league_avg_cost=league.league_avg_cost(position),
            league_avg_value=league.league_avg_value(position),
        ),
        occupants=len(occupants),
    )


class PlayerAssessment:
    __slots__ = ("player_ref", "problem_score", "health_status", "severity", "cost_efficiency")

    def __init__(self, player_ref, problem_score, health_status, severity, cost_efficiency):
        self.player_ref = player_ref
        self.problem_score = problem_score
        self.health_status = health_status
        self.severity = severity
        self.cost_efficiency = cost_efficiency


def assess_player(deps: AgentDeps, player_id: UUID) -> PlayerAssessment | None:
    """None when the player is not on this roster -- the caller drops the
    finding rather than guessing what the model meant."""
    entry = deps.entry_for(player_id)
    if entry is None:
        return None
    league = deps.league
    efficiency = league.cost_efficiency(entry.value_score, entry.cost)
    score = scoring.problem_score(
        league.value_percentile(entry.position, entry.value_score), efficiency
    )
    return PlayerAssessment(
        player_ref=team_service.player_ref(deps.store, entry.player_id, entry.position),
        problem_score=score,
        health_status=scoring.health_status(score),
        severity=scoring.severity_from_score(score),
        cost_efficiency=round(efficiency, 2),
    )


def coverage_warnings(deps: AgentDeps) -> list[CoverageWarning]:
    """Squad-minimum shortfalls.

    Same rule as gap_finder_service._coverage_warnings: a shortfall of more than
    one body is high severity, anything else is medium. If that rule moves,
    promote it to services/scoring.py and call it from both places.
    """
    counts = deps.group_counts()
    warnings: list[CoverageWarning] = []
    for group, required in deps.minimums.items():
        actual = counts.get(group, 0)
        if actual < required:
            warnings.append(
                CoverageWarning(
                    position_group=group,
                    required=required,
                    actual=actual,
                    severity=Severity.HIGH if required - actual > 1 else Severity.MEDIUM,
                )
            )
    return sorted(warnings, key=lambda w: w.required - w.actual, reverse=True)


def group_of_position(position: Position) -> PositionGroup:
    return group_of(position)
