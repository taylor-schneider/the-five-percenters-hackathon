"""In-memory store: loads data/*.csv once, serves every read, owns every write.

Hackathon shape. The CSVs are read exactly once at startup; after that this
object IS the league and `execute` mutates it in place. A restart resets
everything, which is what you want for repeated demo runs.

Phase 2 swaps this module for a SQLAlchemy-backed repository. Nothing above it
changes -- services take a Snapshot, never this object.
"""

from __future__ import annotations

import csv
import hashlib
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

from ...data_models import (
    AgentInsightRecord,
    IdempotencyRecord,
    MarketListingRecord,
    PlayerRecord,
    PositionRecord,
    RosterEntryRecord,
    TeamRecord,
    TradeItemRecord,
    TradeRecordRow,
)
from ..models.enums import Position, PositionGroup

DATA_DIR = Path(__file__).resolve().parents[3] / "data"
EPOCH = datetime(2026, 7, 1, tzinfo=timezone.utc)

#: Namespace for UUIDv5 ids. Fixed, so "MCI" maps to the same uuid every run and
#: a bookmarked team URL survives a restart.
NS = uuid5(NAMESPACE_URL, "https://five-percenters.hackathon/gm")


class StaleRosterVersion(Exception):
    """The optimistic lock (D7) failed. Surfaces as 409 STALE_ROSTER_VERSION."""

    def __init__(self, expected: int, actual: int) -> None:
        super().__init__(f"roster_version {expected} is behind {actual}")
        self.expected = expected
        self.actual = actual


def stable_uuid(kind: str, key: str) -> UUID:
    """Deterministic id from a CSV key. stable_uuid("team", "MCI") is constant."""
    return uuid5(NS, f"{kind}:{key}")


def _jitter(seed: str, lo: float, hi: float) -> float:
    """Deterministic value in [lo, hi) from a string seed."""
    digest = hashlib.sha256(seed.encode()).digest()
    frac = int.from_bytes(digest[:8], "big") / 2**64
    return lo + frac * (hi - lo)


def spread_value_score(rating: int, code: str) -> float:
    """Turn the 4-10 integer value_rating into a 0-100 value_score.

    Seven distinct ratings across 150 players makes percentiles heavily tied, so
    each rating band is spread +/-4 points. The jitter is hashed off the player
    code rather than taken from salary rank: tying value to salary would make
    cost_efficiency partly self-fulfilling and blunt the "overpaid player"
    signal the whole demo rests on. Bands stay 10 apart, so spreading never
    reorders two players of different ratings.
    """
    return round(rating * 10 + _jitter(f"value:{code}", -4.0, 4.0), 1)


def synth_age(code: str) -> int:
    """Age is required by PlayerRef and absent from the CSV. Deterministic 19-35."""
    return int(_jitter(f"age:{code}", 19, 36))


@dataclass
class Store:
    positions: dict[Position, PositionRecord] = field(default_factory=dict)
    teams: dict[UUID, TeamRecord] = field(default_factory=dict)
    players: dict[UUID, PlayerRecord] = field(default_factory=dict)
    roster: list[RosterEntryRecord] = field(default_factory=list)
    listings: dict[UUID, MarketListingRecord] = field(default_factory=dict)

    # --- written at runtime ---
    trades: dict[UUID, TradeRecordRow] = field(default_factory=dict)
    trade_items: list[TradeItemRecord] = field(default_factory=list)
    insights: list[AgentInsightRecord] = field(default_factory=list)
    idempotency: dict[UUID, IdempotencyRecord] = field(default_factory=dict)

    # --- reads -------------------------------------------------------------

    def current_roster(self, team_id: UUID) -> list[RosterEntryRecord]:
        return [e for e in self.roster if e.team_id == team_id and e.is_current]

    def league_roster(self) -> list[RosterEntryRecord]:
        """Every current entry in the league. Percentiles are league-wide (api.md 4)."""
        return [e for e in self.roster if e.is_current]

    def team_by_code(self, code: str) -> TeamRecord | None:
        return self.teams.get(stable_uuid("team", code))

    def available_listings(
        self, exclude_team_id: UUID | None = None
    ) -> list[MarketListingRecord]:
        """Buyable players. A club may not buy its own player, so the acting team
        is excluded (api.md 5.7 exclude_team_id)."""
        return [
            listing
            for listing in self.listings.values()
            if listing.available and listing.source_team_id != exclude_team_id
        ]

    def min_counts(self) -> dict[PositionGroup, int]:
        """Squad minimums, from data/positions.csv rather than hardcoded."""
        return {p.position_group: p.min_count for p in self.positions.values()}

    def list_teams(self) -> list[TeamRecord]:
        """Backs the team picker (api.md 5.3). Not paginated -- ten clubs."""
        return sorted(self.teams.values(), key=lambda t: t.name)

    def listing(self, listing_id: UUID) -> MarketListingRecord | None:
        return self.listings.get(listing_id)

    def trade(self, trade_id: UUID) -> TradeRecordRow | None:
        return self.trades.get(trade_id)

    def entry(self, team_id: UUID, player_id: UUID) -> RosterEntryRecord | None:
        """The team's current entry for a player, or None if they do not hold them."""
        for e in self.roster:
            if e.team_id == team_id and e.player_id == player_id and e.is_current:
                return e
        return None

    # --- writes ------------------------------------------------------------
    #
    # Only two callers: Trader.execute (apply_trade + record_trade +
    # remember_idempotency) and Gap Finder (add_insights). No agent reasoning
    # loop writes -- execute is gated on user_confirmation, so a human commits.

    def apply_trade(
        self,
        team_id: UUID,
        incoming: list[MarketListingRecord],
        outgoing: list[RosterEntryRecord],
        expected_version: int,
    ) -> int:
        """Commit a trade and return the new roster_version.

        The optimistic lock (D7) is checked here, against the live version
        rather than the caller's snapshot -- that is what makes a slightly stale
        snapshot safe to read from.

        Callers MUST have validated the trade first. Everything below either
        cannot fail or has already been checked, so there is no partial-apply
        path and no rollback machinery: the equivalent of the single
        transaction api.md 5.11 requires.
        """
        team = self.teams.get(team_id)
        if team is None:
            raise KeyError(f"unknown team {team_id}")
        if team.roster_version != expected_version:
            raise StaleRosterVersion(expected_version, team.roster_version)

        now = datetime.now(timezone.utc)

        for entry in outgoing:
            entry.effective_to = now
            entry.is_current = False
            # A player who has left cannot still be on this club's shelf.
            listing = self.listings.get(entry.roster_entry_id)
            if listing is not None:
                listing.available = False
                listing.updated_at = now

        for listing in incoming:
            listing.available = False
            listing.updated_at = now
            player = self.players[listing.player_id]
            self.roster.append(
                RosterEntryRecord(
                    roster_entry_id=uuid4(),
                    team_id=team_id,
                    player_id=listing.player_id,
                    position=player.position,
                    cost=listing.cost,
                    value_score=listing.expected_value_score,
                    available=True,
                    effective_from=now,
                )
            )

        team.roster_version += 1
        return team.roster_version

    def record_trade(
        self, trade: TradeRecordRow, items: list[TradeItemRecord]
    ) -> TradeRecordRow:
        """Persist the audit record. Also used for failed trades (api.md 5.11)."""
        self.trades[trade.trade_id] = trade
        self.trade_items.extend(items)
        return trade

    def trade_legs(self, trade_id: UUID) -> list[TradeItemRecord]:
        return [i for i in self.trade_items if i.trade_id == trade_id]

    def add_insights(self, insights: list[AgentInsightRecord]) -> None:
        """Gap Finder's explainability trail, when persist_insights is true."""
        self.insights.extend(insights)

    def team_insights(self, team_id: UUID) -> list[AgentInsightRecord]:
        """Newest first, as api.md 5.14 requires."""
        return sorted(
            (i for i in self.insights if i.team_id == team_id),
            key=lambda i: i.created_at,
            reverse=True,
        )

    def set_listing_availability(self, listing_id: UUID, available: bool) -> None:
        """List or delist a player. The one market edit outside a trade."""
        listing = self.listings.get(listing_id)
        if listing is None:
            raise KeyError(f"unknown listing {listing_id}")
        listing.available = available
        listing.updated_at = datetime.now(timezone.utc)
        for entry in self.roster:
            if entry.roster_entry_id == listing_id:
                entry.available = available
                break

    # --- idempotency (api.md 1) --------------------------------------------

    def lookup_idempotency(self, key: UUID) -> IdempotencyRecord | None:
        """Returns the stored record, or None if unseen or expired."""
        rec = self.idempotency.get(key)
        if rec is None:
            return None
        if rec.expires_at <= datetime.now(timezone.utc):
            del self.idempotency[key]
            return None
        return rec

    def remember_idempotency(
        self, key: UUID, request_hash: str, response_body: dict, ttl_seconds: int = 86_400
    ) -> IdempotencyRecord:
        now = datetime.now(timezone.utc)
        rec = IdempotencyRecord(
            key=key,
            request_hash=request_hash,
            created_at=now,
            expires_at=now + timedelta(seconds=ttl_seconds),
            response_body=response_body,
        )
        self.idempotency[key] = rec
        return rec


def load(data_dir: Path | None = None) -> Store:
    """Read the three CSVs and derive everything the API needs from them."""
    d = data_dir or DATA_DIR
    store = Store()

    with open(d / "positions.csv", newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            pos = Position(row["position"])
            store.positions[pos] = PositionRecord(
                position=pos,
                position_group=PositionGroup(row["position_group"]),
                display_name=row["display_name"],
                pitch_x=float(row["pitch_x"]),
                pitch_y=float(row["pitch_y"]),
                min_count=int(row["min_count"]),
                sort_order=int(row["sort_order"]),
            )

    with open(d / "clubs.csv", newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            tid = stable_uuid("team", row["club_id"])
            store.teams[tid] = TeamRecord(
                team_id=tid,
                club_code=row["club_id"],
                name=row["club_name"],
                budget_cap=int(row["salary_cap_gbp"]),
                roster_version=1,
            )
            # max_squad_size is deliberately ignored: budget is the only cap.

    with open(d / "players.csv", newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))

    for row in rows:
        code = row["player_id"]
        pid = stable_uuid("player", code)
        tid = stable_uuid("team", row["club_id"])
        pos = Position(row["position"])
        store.players[pid] = PlayerRecord(
            player_id=pid,
            code=code,
            name=row["name"],
            position=pos,
            position_group=store.positions[pos].position_group,
            age=synth_age(code),
        )
        store.roster.append(
            RosterEntryRecord(
                roster_entry_id=stable_uuid("roster", code),
                team_id=tid,
                player_id=pid,
                position=pos,
                cost=int(row["annual_salary_gbp"]),
                value_score=spread_value_score(int(row["value_rating"]), code),
                available=True,
                effective_from=EPOCH,
            )
        )

    _mark_untouchables(store)
    _build_listings(store)
    return store


def _mark_untouchables(store: Store) -> None:
    """Each club's single best player is not for sale.

    Gives PLAYER_NOT_AVAILABLE something real to fire on, and stops the
    Opportunity Finder proposing that every club sell its best asset.
    """
    best: dict[UUID, RosterEntryRecord] = {}
    for entry in store.roster:
        if entry.team_id not in best or entry.value_score > best[entry.team_id].value_score:
            best[entry.team_id] = entry
    for entry in best.values():
        entry.available = False


def _build_listings(store: Store) -> None:
    """The market does not exist in the source data -- derive it.

    Every available roster player is listed by their current club. Per D9 the
    counterparty's books are not updated on a trade; the listing is simply
    consumed, so one listing per player is enough for v1.
    """
    for entry in store.roster:
        if not entry.available:
            continue
        store.listings[entry.roster_entry_id] = MarketListingRecord(
            listing_id=entry.roster_entry_id,
            player_id=entry.player_id,
            source_team_id=entry.team_id,
            cost=entry.cost,
            expected_value_score=entry.value_score,
            available=True,
            updated_at=EPOCH,
            sample_size=12,
        )


_STORE: Store | None = None


def get_store() -> Store:
    """Process-wide singleton. Loaded on first access, mutated in place after."""
    global _STORE
    if _STORE is None:
        _STORE = load()
    return _STORE
