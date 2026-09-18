"""Per-run dependencies handed to every tool handler.

One object, built once per agent invocation, holding the team, the league
distribution, and the squad minimums in force. Building the LeagueContext once
matters: it is an O(all roster entries) scan, and a ReAct agent will call five
or six tools per run.

This is also the single coupling point between the agents package and the API
package. If the API's repository layer moves to SQLAlchemy, this file changes
and the tools do not.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from uuid import UUID

from ...api.core.config import get_settings
from ...api.models.enums import PositionGroup
from ...api.models.requests import Constraints
from ...api.repositories.store import RosterEntryRecord, Store, TeamRecord
from ...api.services import team_service
from ...api.services.scoring import LeagueContext


def resolve_minimums(requested: dict[PositionGroup, int] | None) -> dict[PositionGroup, int]:
    """Squad minimums with the request's overrides applied.

    Mirrors gap_finder_service.resolve_minimums so an agent run and a heuristic
    run are judged against the same rules.
    """
    defaults = dict(get_settings().default_min_position_group_counts)
    if requested:
        defaults.update(requested)
    return defaults


@dataclass(slots=True)
class AgentDeps:
    """What every tool handler receives as its second argument."""

    store: Store
    team: TeamRecord
    minimums: dict[PositionGroup, int]
    budget_cap: int
    """Effective cap for this run: the constraint override if one was supplied,
    else the team's stored cap. Read tools report against this so what-if
    analysis is coherent."""

    _league: LeagueContext | None = field(default=None, repr=False)
    _roster: list[RosterEntryRecord] | None = field(default=None, repr=False)

    @classmethod
    def build(
        cls,
        store: Store,
        team_id: UUID,
        constraints: Constraints | None = None,
    ) -> "AgentDeps":
        team = team_service.require_team(store, team_id)
        constraints = constraints or Constraints()
        return cls(
            store=store,
            team=team,
            minimums=resolve_minimums(constraints.min_position_group_counts),
            budget_cap=constraints.budget_cap or team.budget_cap,
        )

    # --- lazily built, then reused for the whole run ----------------------

    @property
    def league(self) -> LeagueContext:
        if self._league is None:
            self._league = LeagueContext.build(self.store.all_current_entries())
        return self._league

    @property
    def roster(self) -> list[RosterEntryRecord]:
        if self._roster is None:
            self._roster = self.store.current_roster(self.team.id)
        return self._roster

    def invalidate(self) -> None:
        """Drop cached reads. Only needed if something mutates mid-run, which
        no agent tool does today -- execution is the API's job, not an agent's.
        """
        self._league = None
        self._roster = None

    # --- small shared helpers ---------------------------------------------

    def group_counts(self) -> dict[PositionGroup, int]:
        return team_service.group_counts(self.roster)

    def shortfalls(self) -> dict[str, dict[str, int]]:
        counts = self.group_counts()
        return {
            group.value: {"required": required, "actual": counts.get(group, 0)}
            for group, required in self.minimums.items()
            if counts.get(group, 0) < required
        }

    def entry_for(self, player_id: UUID) -> RosterEntryRecord | None:
        return next((e for e in self.roster if e.player_id == player_id), None)

    def snapshot(self) -> dict[str, object]:
        """The state the agent reasoned over, for AgentMeta.input_snapshot_hash.

        Roster contents are included, not just the version, so two runs against
        the same version but different seed data do not collide.
        """
        return {
            "team_id": str(self.team.id),
            "roster_version": self.team.roster_version,
            "budget_cap": self.budget_cap,
            "minimums": {g.value: n for g, n in sorted(self.minimums.items())},
            "roster": sorted(
                f"{e.player_id}:{e.cost}:{e.value_score}" for e in self.roster
            ),
        }
