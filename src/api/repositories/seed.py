"""Load the supplied league from data/*.csv into the store.

This replaces the synthetic generator that stood in before real data arrived.
The CSVs are read exactly once at startup; after that the store IS the league
and execute() mutates it in place. A restart resets everything, which is what
you want for repeated demo runs.

The source data gives six columns. Four things the API requires are absent and
are derived here, all deterministically so a reload reproduces the league
exactly:

- ids          UUIDv5 from the CSV keys, so "MCI" is the same uuid every run
- value_score  spread from the 4-10 integer rating into 0-100
- age          required by PlayerRef, absent from the CSV
- the market   no listings exist in the source data at all
"""

from __future__ import annotations

import csv
import hashlib
from pathlib import Path
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

from ..models.enums import Position, group_of
from .store import (
    MarketListingRecord,
    PlayerRecord,
    RosterEntryRecord,
    Store,
    TeamRecord,
)

DATA_DIR = Path(__file__).resolve().parents[3] / "data"

#: Fixed namespace, so ids survive a restart and a bookmarked team URL keeps
#: working.
NS = uuid5(NAMESPACE_URL, "https://five-percenters.hackathon/gm")


def stable_uuid(kind: str, key: str) -> UUID:
    """Deterministic id from a CSV key. stable_uuid("team", "MCI") is constant."""
    return uuid5(NS, f"{kind}:{key}")


def _jitter(seed: str, lo: float, hi: float) -> float:
    """Deterministic value in [lo, hi) from a string seed."""
    digest = hashlib.sha256(seed.encode()).digest()
    return lo + (int.from_bytes(digest[:8], "big") / 2**64) * (hi - lo)


def spread_value_score(rating: int, code: str) -> float:
    """Turn the 4-10 integer value_rating into a 0-100 value_score.

    Seven distinct ratings across 150 players leaves percentiles heavily tied,
    so each band is spread +/-4 points. The jitter is hashed off the player code
    rather than taken from salary rank: tying value to salary would make
    cost_efficiency partly self-fulfilling and blunt the "overpaid player"
    signal the dashboard rests on. Bands stay 10 apart, so spreading never
    reorders two players of different ratings.
    """
    return round(rating * 10 + _jitter(f"value:{code}", -4.0, 4.0), 1)


def synth_age(code: str) -> int:
    """Age is required by PlayerRef and absent from the CSV. Deterministic 19-35."""
    return int(_jitter(f"age:{code}", 19, 36))


def load_league(store: Store, data_dir: Path | None = None) -> Store:
    """Populate an empty store from the CSVs."""
    d = data_dir or DATA_DIR

    with open(d / "clubs.csv", newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            team = TeamRecord(
                id=stable_uuid("team", row["club_id"]),
                name=row["club_name"],
                budget_cap=int(row["salary_cap_gbp"]),
                roster_version=1,
            )
            store.teams[team.id] = team
            # max_squad_size is deliberately ignored: budget is the only cap.

    with open(d / "players.csv", newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            code = row["player_id"]
            position = Position(row["position"])
            player = PlayerRecord(
                id=stable_uuid("player", code),
                name=row["name"],
                position=position,
                age=synth_age(code),
            )
            store.players[player.id] = player

            entry = RosterEntryRecord(
                id=stable_uuid("roster", code),
                team_id=stable_uuid("team", row["club_id"]),
                player_id=player.id,
                position=position,
                cost=int(row["annual_salary_gbp"]),
                value_score=spread_value_score(int(row["value_rating"]), code),
            )
            store.roster_entries[entry.id] = entry

    _withhold_star_players(store)
    _build_market(store)
    return store


def _withhold_star_players(store: Store) -> None:
    """Each club's single best player is not for sale.

    Gives PLAYER_NOT_AVAILABLE something real to fire on, and stops the
    Opportunity Finder proposing that every club sell its best asset.
    """
    best: dict[UUID, RosterEntryRecord] = {}
    for entry in store.roster_entries.values():
        current = best.get(entry.team_id)
        if current is None or entry.value_score > current.value_score:
            best[entry.team_id] = entry
    for entry in best.values():
        entry.available = False


def _build_market(store: Store) -> None:
    """The market does not exist in the source data -- derive it.

    Every available roster player is listed by their current club. Per D9 the
    counterparty's books are not updated on a trade; the listing is simply
    consumed, so one listing per player is enough for v1.
    """
    for entry in store.roster_entries.values():
        if not entry.available:
            continue
        listing = MarketListingRecord(
            id=uuid4(),
            player_id=entry.player_id,
            source_team_id=entry.team_id,
            position=entry.position,
            cost=entry.cost,
            expected_value_score=entry.value_score,
        )
        store.listings[listing.id] = listing


def seed(store: Store) -> Store:
    """Entry point used at app startup."""
    return load_league(store)


#: Back-compat alias for the synthetic generator this module replaced.
seed_store = seed

#: The club the demo opens on. Brentford is the interesting one: smallest squad
#: in the league, short at DEF against the minimum, and under its cap -- so the
#: dashboard has a real coverage warning and Stage 2 has room to act on it.
DEMO_CLUB_CODE = "BRE"


def demo_team_id(store: Store | None = None) -> str:
    """Team the UI lands on when no team is chosen. String, as the API returns it."""
    return str(stable_uuid("team", DEMO_CLUB_CODE))


def position_groups_of(store: Store, team_id: UUID) -> dict[str, int]:
    """Squad headcount per position group -- handy for coverage checks."""
    counts: dict[str, int] = {}
    for entry in store.roster_entries.values():
        if entry.team_id == team_id and entry.is_current:
            key = group_of(entry.position).value
            counts[key] = counts.get(key, 0) + 1
    return counts
