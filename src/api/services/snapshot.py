"""The per-request read view every agent is handed.

Agents never touch the Store. They receive one of these, built once per request,
and every read they make comes from it. That buys three things:

- `input_snapshot_hash` (api.md 3.14) is meaningful, because the snapshot really
  is the agent's input. You can prove which roster state a recommendation was
  made against, and replay it.
- Gap Finder, Opportunity Finder and Trader cannot disagree with each other or
  with the dashboard, because they all read the same frozen view.
- The league-wide percentile distributions get built once, not once per agent.

Writes are the exception: Trader.execute and Gap Finder's persist_insights call
the Store directly. Nothing inside an agent reasoning loop writes.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import UUID

from ...data_models import (
    MarketListingRecord,
    PlayerRecord,
    PositionRecord,
    RosterEntryRecord,
    TeamRecord,
)
from ..models.enums import Position, PositionGroup
from ..repositories.store import Store
from .scoring import LeagueContext


@dataclass(frozen=True, slots=True)
class Snapshot:
    """One team's world, frozen at a point in time."""

    team: TeamRecord
    squad: list[RosterEntryRecord]
    """This team's current roster entries."""
    league: list[RosterEntryRecord]
    """Every current entry in the league. Percentiles are league-wide (api.md 4)."""
    listings: list[MarketListingRecord]
    """Buyable players, already excluding this team's own."""
    players: dict[UUID, PlayerRecord]
    positions: dict[Position, PositionRecord]
    roster_version: int
    """The version this view was taken at. Echoed back by simulate/execute so
    execute can re-check it against the live store (D7)."""
    taken_at: datetime

    # --- derived ------------------------------------------------------------

    def league_context(self) -> LeagueContext:
        """Percentile distributions. Built once per request, shared by all agents."""
        return LeagueContext.build(self.league)

    def min_counts(self) -> dict[PositionGroup, int]:
        return {p.position_group: p.min_count for p in self.positions.values()}

    def group_counts(self) -> dict[PositionGroup, int]:
        """This squad's headcount per position group."""
        counts = {g: 0 for g in PositionGroup}
        for entry in self.squad:
            counts[self.players[entry.player_id].position_group] += 1
        return counts

    def team_cost(self) -> int:
        return sum(e.cost for e in self.squad)

    def team_score(self) -> float:
        """Unweighted mean of roster value_score, 1dp (D4)."""
        if not self.squad:
            return 0.0
        return round(sum(e.value_score for e in self.squad) / len(self.squad), 1)

    def player(self, player_id: UUID) -> PlayerRecord | None:
        return self.players.get(player_id)

    def entry_for(self, player_id: UUID) -> RosterEntryRecord | None:
        """This team's entry for a player, or None if they do not hold them."""
        return next((e for e in self.squad if e.player_id == player_id), None)

    def listing_for(self, player_id: UUID) -> MarketListingRecord | None:
        return next((l for l in self.listings if l.player_id == player_id), None)

    # --- provenance ---------------------------------------------------------

    def input_hash(self) -> str:
        """SHA-256 over the canonicalised view (api.md 3.14).

        Covers every number an agent could have read, so two runs producing the
        same hash saw the same league. Deliberately excludes `taken_at` -- the
        wall clock is not part of what the agent reasoned over.
        """
        payload = {
            "team": [str(self.team.team_id), self.team.budget_cap, self.roster_version],
            "squad": sorted(
                [str(e.player_id), e.cost, e.value_score, e.available] for e in self.squad
            ),
            "league": sorted(
                [str(e.player_id), e.cost, e.value_score] for e in self.league
            ),
            "listings": sorted(
                [str(l.listing_id), l.cost, l.expected_value_score] for l in self.listings
            ),
        }
        blob = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return "sha256:" + hashlib.sha256(blob.encode()).hexdigest()


def build(store: Store, team_id: UUID) -> Snapshot:
    """Take a read view for one team. Call once per request, at the top."""
    team = store.teams.get(team_id)
    if team is None:
        raise KeyError(f"unknown team {team_id}")
    return Snapshot(
        team=team,
        squad=store.current_roster(team_id),
        league=store.league_roster(),
        listings=store.available_listings(exclude_team_id=team_id),
        players=dict(store.players),
        positions=dict(store.positions),
        roster_version=team.roster_version,
        taken_at=datetime.now(timezone.utc),
    )
