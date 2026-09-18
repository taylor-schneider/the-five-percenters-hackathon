"""In-memory data store standing in for PostgreSQL.

Records live in src/data_models/, one file each. This module owns access to
them -- how they are queried and mutated -- and nothing else knows how the
data is persisted.

This is the ONLY module that knows how data is persisted. The HTTP contract in
api.md is identical whether this is a dict or a database -- swapping in
SQLAlchemy means reimplementing this file and nothing else.

Internal records are dataclasses, deliberately distinct from the Pydantic API
models in models/domain.py, so a storage change cannot silently reshape a
response.
"""

from __future__ import annotations

import threading
from typing import Any
from uuid import UUID, uuid4

from ...data_models import (
    IdempotencyRecord,
    InsightRecord,
    MarketListingRecord,
    PlayerRecord,
    RosterEntryRecord,
    TeamRecord,
    TradeRecordRow,
    utcnow,
)
from ..models.enums import Position, PositionGroup, TradeStatus, group_of


# --------------------------------------------------------------------------
# Store
# --------------------------------------------------------------------------


class Store:
    """Process-local store. The lock makes execute() atomic, standing in for the
    database transaction that api.md section 5.11 requires."""

    def __init__(self) -> None:
        self.teams: dict[UUID, TeamRecord] = {}
        self.players: dict[UUID, PlayerRecord] = {}
        self.roster_entries: dict[UUID, RosterEntryRecord] = {}
        self.listings: dict[UUID, MarketListingRecord] = {}
        self.trades: dict[UUID, TradeRecordRow] = {}
        self.insights: dict[UUID, InsightRecord] = {}
        self.idempotency: dict[UUID, IdempotencyRecord] = {}
        self.lock = threading.RLock()

    # --- teams -------------------------------------------------------------

    def list_teams(self) -> list[TeamRecord]:
        return sorted(self.teams.values(), key=lambda t: t.name)

    def get_team(self, team_id: UUID) -> TeamRecord | None:
        return self.teams.get(team_id)

    def bump_roster_version(self, team_id: UUID) -> int:
        team = self.teams[team_id]
        team.roster_version += 1
        return team.roster_version

    # --- players -----------------------------------------------------------

    def get_player(self, player_id: UUID) -> PlayerRecord | None:
        return self.players.get(player_id)

    # --- roster ------------------------------------------------------------

    def current_roster(self, team_id: UUID) -> list[RosterEntryRecord]:
        return [
            e
            for e in self.roster_entries.values()
            if e.team_id == team_id and e.is_current
        ]

    def all_current_entries(self) -> list[RosterEntryRecord]:
        """Every current entry league-wide -- the population for benchmarks."""
        return [e for e in self.roster_entries.values() if e.is_current]

    def find_roster_entry(self, team_id: UUID, player_id: UUID) -> RosterEntryRecord | None:
        for entry in self.roster_entries.values():
            if entry.team_id == team_id and entry.player_id == player_id and entry.is_current:
                return entry
        return None

    def close_roster_entry(self, entry: RosterEntryRecord) -> None:
        entry.is_current = False
        entry.effective_to = utcnow()

    def add_roster_entry(
        self,
        team_id: UUID,
        player_id: UUID,
        position: Position,
        cost: int,
        value_score: float,
    ) -> RosterEntryRecord:
        entry = RosterEntryRecord(
            id=uuid4(),
            team_id=team_id,
            player_id=player_id,
            position=position,
            cost=cost,
            value_score=value_score,
        )
        self.roster_entries[entry.id] = entry
        return entry

    # --- market ------------------------------------------------------------

    def list_listings(
        self,
        position: Position | None = None,
        position_group: PositionGroup | None = None,
        max_cost: int | None = None,
        min_value: float | None = None,
        exclude_team_id: UUID | None = None,
        available_only: bool = True,
    ) -> list[MarketListingRecord]:
        out: list[MarketListingRecord] = []
        for listing in self.listings.values():
            if available_only and not listing.available:
                continue
            if position is not None and listing.position != position:
                continue
            if position_group is not None and group_of(listing.position) != position_group:
                continue
            if max_cost is not None and listing.cost > max_cost:
                continue
            if min_value is not None and listing.expected_value_score < min_value:
                continue
            if exclude_team_id is not None and listing.source_team_id == exclude_team_id:
                continue
            out.append(listing)
        return sorted(out, key=lambda listing: (-listing.expected_value_score, listing.cost))

    def get_listing(self, listing_id: UUID) -> MarketListingRecord | None:
        return self.listings.get(listing_id)

    def find_listing_for_player(self, player_id: UUID) -> MarketListingRecord | None:
        for listing in self.listings.values():
            if listing.player_id == player_id and listing.available:
                return listing
        return None

    # --- trades and insights ----------------------------------------------

    def add_trade(self, row: TradeRecordRow) -> TradeRecordRow:
        self.trades[row.id] = row
        return row

    def get_trade(self, trade_id: UUID) -> TradeRecordRow | None:
        return self.trades.get(trade_id)

    def add_insight(self, row: InsightRecord) -> InsightRecord:
        self.insights[row.id] = row
        return row

    def list_insights(self, team_id: UUID, **filters: Any) -> list[InsightRecord]:
        rows = [i for i in self.insights.values() if i.team_id == team_id]
        for key, value in filters.items():
            if value is None:
                continue
            rows = [r for r in rows if getattr(r, key, None) == value]
        return sorted(rows, key=lambda r: r.created_at, reverse=True)

    # --- idempotency -------------------------------------------------------

    def get_idempotency(self, key: UUID) -> IdempotencyRecord | None:
        return self.idempotency.get(key)

    def save_idempotency(self, key: UUID, request_hash: str, response: dict[str, Any]) -> None:
        self.idempotency[key] = IdempotencyRecord(
            key=key, request_hash=request_hash, response=response
        )

    def reset(self) -> None:
        self.__init__()  # type: ignore[misc]


#: Process-wide singleton. Injected via a FastAPI dependency so tests can
#: substitute a fresh instance.
_store = Store()


def get_store() -> Store:
    return _store
