"""The api.md section 4 formulas. This is the ONLY place they appear.

Gap Finder, Opportunity Finder and the dashboard all call in here, so a
threshold change lands everywhere at once.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass, field

from ..core.config import ScoringWeights, get_settings
from ..models.enums import HealthStatus, Position, PositionGroup, Severity, group_of
from ..repositories.store import RosterEntryRecord


def percentile_rank(value: float, population: list[float]) -> float:
    """Fraction of the population at or below `value`, ties split evenly.

    Returns 0.5 for an empty population -- an unknown percentile should read as
    neutral, not as "worst in the league".
    """
    if not population:
        return 0.5
    below = sum(1 for v in population if v < value)
    equal = sum(1 for v in population if v == value)
    return (below + 0.5 * equal) / len(population)


def normalize_0_1(value: float, low: float, high: float) -> float:
    """Min-max normalise, clamped. Degenerate ranges collapse to neutral."""
    if high <= low:
        return 0.5
    return max(0.0, min(1.0, (value - low) / (high - low)))


def value_per_euro(value_score: float, cost: int) -> float:
    """Raw efficiency ratio, scaled to a readable magnitude.

    A zero or negative salary would be a data error; treat it as maximally
    efficient rather than dividing by zero.
    """
    if cost <= 0:
        return float("inf")
    return value_score / cost * 1_000_000


@dataclass(slots=True)
class LeagueContext:
    """League-wide distributions, computed once per request.

    Percentiles are taken within `position` across every current roster entry in
    the league, per api.md section 4.
    """

    value_by_position: dict[Position, list[float]] = field(default_factory=dict)
    cost_by_position: dict[Position, list[float]] = field(default_factory=dict)
    ratio_low: float = 0.0
    ratio_high: float = 1.0

    @classmethod
    def build(cls, entries: list[RosterEntryRecord]) -> "LeagueContext":
        ctx = cls(value_by_position={}, cost_by_position={})
        ratios: list[float] = []
        for entry in entries:
            ctx.value_by_position.setdefault(entry.position, []).append(entry.value_score)
            ctx.cost_by_position.setdefault(entry.position, []).append(float(entry.cost))
            ratio = value_per_euro(entry.value_score, entry.cost)
            if ratio != float("inf"):
                ratios.append(ratio)
        if ratios:
            ctx.ratio_low = min(ratios)
            ctx.ratio_high = max(ratios)
        return ctx

    # --- per-player metrics ------------------------------------------------

    def value_percentile(self, position: Position, value_score: float) -> float:
        return percentile_rank(value_score, self.value_by_position.get(position, []))

    def cost_percentile(self, position: Position, cost: int) -> float:
        return percentile_rank(float(cost), self.cost_by_position.get(position, []))

    def cost_efficiency(self, value_score: float, cost: int) -> float:
        """Normalised value-per-euro, 0-1 across the league."""
        ratio = value_per_euro(value_score, cost)
        if ratio == float("inf"):
            return 1.0
        return normalize_0_1(ratio, self.ratio_low, self.ratio_high)

    def league_avg_cost(self, position: Position) -> int:
        costs = self.cost_by_position.get(position, [])
        return int(round(statistics.fmean(costs))) if costs else 0

    def league_avg_value(self, position: Position) -> float:
        values = self.value_by_position.get(position, [])
        return round(statistics.fmean(values), 1) if values else 0.0

    def sample_size(self, position: Position) -> int:
        return len(self.value_by_position.get(position, []))


def problem_score(
    value_percentile: float,
    cost_efficiency: float,
    coverage_penalty: float = 0.0,
    weights: ScoringWeights | None = None,
) -> float:
    """problem_score = w1*value_gap + w2*cost_penalty + w3*coverage_penalty."""
    w = weights or get_settings().weights
    value_gap = 1.0 - value_percentile
    cost_penalty = 1.0 - cost_efficiency
    score = w.w1 * value_gap + w.w2 * cost_penalty + w.w3 * coverage_penalty
    return round(max(0.0, min(1.0, score)), 3)


def health_status(score: float, weights: ScoringWeights | None = None) -> HealthStatus:
    w = weights or get_settings().weights
    if score >= w.red_threshold:
        return HealthStatus.RED
    if score >= w.green_threshold:
        return HealthStatus.WHITE
    return HealthStatus.GREEN


def severity_from_score(score: float) -> Severity:
    if score >= 0.67:
        return Severity.HIGH
    if score >= 0.34:
        return Severity.MEDIUM
    return Severity.LOW


def opportunity_scores(
    value_gains: list[float],
    cost_savings: list[float],
    risks: list[float],
    weights: ScoringWeights | None = None,
) -> list[float]:
    """opportunity_score = a1*value_gain_norm + a2*cost_saving_norm - a3*risk_norm.

    Normalisation is min-max WITHIN the candidate set, so scores are only
    comparable inside one Opportunity Finder response (api.md section 4).
    """
    w = weights or get_settings().weights
    if not value_gains:
        return []

    v_low, v_high = min(value_gains), max(value_gains)
    c_low, c_high = min(cost_savings), max(cost_savings)
    r_low, r_high = min(risks), max(risks)

    out: list[float] = []
    for gain, saving, risk in zip(value_gains, cost_savings, risks, strict=True):
        raw = (
            w.a1 * normalize_0_1(gain, v_low, v_high)
            + w.a2 * normalize_0_1(saving, c_low, c_high)
            - w.a3 * normalize_0_1(risk, r_low, r_high)
        )
        out.append(round(max(0.0, min(1.0, raw)), 3))
    return out


def pct_vs_league(actual: float, league_avg: float) -> float:
    """(actual / league_avg - 1) * 100, computed server-side so the benchmark
    definition stays in one place."""
    if league_avg <= 0:
        return 0.0
    return round((actual / league_avg - 1.0) * 100, 1)


def coverage_penalty_for(
    position: Position,
    occupant_count: int,
    group_counts: dict[PositionGroup, int],
    minimums: dict[PositionGroup, int],
) -> float:
    """1.0 when the slot is unfilled or its group is below minimum, else 0.0."""
    if occupant_count == 0:
        return 1.0
    grp = group_of(position)
    if group_counts.get(grp, 0) < minimums.get(grp, 0):
        return 1.0
    return 0.0
