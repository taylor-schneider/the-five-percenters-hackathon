"""Deterministic seed league.

Seeded from a fixed random_state so every demo run produces the same league --
you can point at a specific team and know what the pitch map will look like.

The first team ("Riverside FC") is deliberately built with planted weaknesses so
the Stage 1 dashboard has red circles and Stage 2 has obvious opportunities
without anyone having to hunt for a good demo team.
"""

from __future__ import annotations

import random
from uuid import uuid4

from ..core.config import get_settings
from ..models.enums import FORMATIONS, Position
from .store import (
    MarketListingRecord,
    PlayerRecord,
    Store,
    TeamRecord,
)

DEMO_TEAM_NAME = "Riverside FC"

_TEAM_NAMES = [
    DEMO_TEAM_NAME,
    "Northgate United",
    "Ashford Rovers",
    "Kestrel City",
    "Blackwell Athletic",
    "Harbour Point FC",
    "Windmere Town",
    "Sable Vale",
    "Fenwick Albion",
    "Granite Bay FC",
    "Thornbury Wanderers",
    "Cresthill United",
]

_FIRST = [
    "T.", "K.", "M.", "J.", "L.", "R.", "D.", "S.", "A.", "N.",
    "P.", "C.", "H.", "E.", "O.", "F.", "G.", "B.", "V.", "I.",
]
_LAST = [
    "Alvarez", "Osei", "Nakamura", "Lindqvist", "Moreau", "Bianchi", "Kovac",
    "Ferreira", "Okafor", "Vasquez", "Dimitrov", "Haugen", "Rossi", "Mbeki",
    "Andersen", "Costa", "Novak", "Silva", "Jansen", "Petrov", "Aguirre",
    "Bakker", "Cissokho", "Duarte", "Eriksen", "Fontaine", "Gallardo",
    "Hernandez", "Ivanov", "Jokinen", "Kimura", "Laurent", "Marchetti",
    "Nilsson", "Ortega", "Pavlov", "Quintero", "Ricci", "Sorensen", "Tanaka",
]

#: Roughly 24 players: the 10 formation slots plus depth, weighted so squads
#: satisfy the default GK:2 / DEF:6 / MID:6 / FWD:4 minimums.
_SQUAD_TEMPLATE: list[Position] = [
    Position.GK, Position.GK,
    Position.LB, Position.LB,
    Position.CB, Position.CB, Position.CB, Position.CB,
    Position.RB, Position.RB,
    Position.CDM, Position.CDM,
    Position.CM, Position.CM, Position.CM,
    Position.CAM, Position.CAM,
    Position.LW, Position.LW,
    Position.ST, Position.ST, Position.ST,
    Position.RW, Position.RW,
]

#: Baseline salary by position, before per-player variation.
#:
#: Calibrated against the 24-man template and the 50M cap: the template sums to
#: ~37.7M of base salary, which lands a seeded squad around 41-43M once the
#: per-player multiplier is applied. That leaves roughly 7-9M of headroom, which
#: is what makes trades possible at all -- with a squad already over the cap,
#: every single proposal fails BUDGET_CAP_EXCEEDED and the demo has nothing to
#: show.
_BASE_COST: dict[Position, int] = {
    Position.GK: 1_100_000,
    Position.LB: 1_200_000,
    Position.CB: 1_400_000,
    Position.RB: 1_200_000,
    Position.CDM: 1_350_000,
    Position.CM: 1_500_000,
    Position.CAM: 1_900_000,
    Position.LW: 1_800_000,
    Position.ST: 2_350_000,
    Position.RW: 1_800_000,
}


def _player_name(rng: random.Random, used: set[str]) -> str:
    for _ in range(200):
        name = f"{rng.choice(_FIRST)} {rng.choice(_LAST)}"
        if name not in used:
            used.add(name)
            return name
    name = f"{rng.choice(_FIRST)} {rng.choice(_LAST)} {len(used)}"
    used.add(name)
    return name


def seed_store(store: Store) -> Store:
    """Populate `store` with a full league. Idempotent -- clears first."""
    settings = get_settings()
    rng = random.Random(settings.seed_random_state)
    store.reset()

    used_names: set[str] = set()
    team_count = max(2, min(settings.seed_teams, len(_TEAM_NAMES)))

    for team_index in range(team_count):
        is_demo = team_index == 0
        team = TeamRecord(
            id=uuid4(),
            name=_TEAM_NAMES[team_index],
            budget_cap=50_000_000 if is_demo else rng.randrange(44, 58) * 1_000_000,
        )
        store.teams[team.id] = team

        for slot_index, position in enumerate(_SQUAD_TEMPLATE):
            player = PlayerRecord(
                id=uuid4(),
                name=_player_name(rng, used_names),
                position=position,
                age=rng.randint(19, 34),
                appearances=rng.randint(4, 38),
            )
            store.players[player.id] = player

            base = _BASE_COST[position]
            cost = int(base * rng.uniform(0.55, 1.65))
            value = round(rng.uniform(52.0, 88.0), 1)

            # Planted weaknesses on the demo team: the first-choice CB and the
            # starting ST are both overpaid and underperforming, which is what
            # turns those circles red.
            if is_demo and position in (Position.CB, Position.ST) and slot_index % 4 == 0:
                cost = int(base * rng.uniform(1.35, 1.75))
                value = round(rng.uniform(55.0, 63.0), 1)

            store.add_roster_entry(
                team_id=team.id,
                player_id=player.id,
                position=position,
                cost=cost,
                value_score=value,
            )

    # --- market listings ---------------------------------------------------
    # Two sources: free agents, and squad players other teams have listed. Every
    # listing's `cost` is the salary the player will carry once acquired (D1).
    demo_team = next(t for t in store.teams.values() if t.name == DEMO_TEAM_NAME)

    for position in FORMATIONS["4-3-3"]:
        for _ in range(rng.randint(3, 5)):
            player = PlayerRecord(
                id=uuid4(),
                name=_player_name(rng, used_names),
                position=position,
                age=rng.randint(19, 32),
                appearances=rng.randint(3, 38),
            )
            store.players[player.id] = player
            base = _BASE_COST[position]
            listing = MarketListingRecord(
                id=uuid4(),
                player_id=player.id,
                source_team_id=None,
                position=position,
                cost=int(base * rng.uniform(0.5, 1.25)),
                expected_value_score=round(rng.uniform(60.0, 92.0), 1),
            )
            store.listings[listing.id] = listing

    # Some existing squad players from other teams are on the market too.
    other_entries = [
        e for e in store.all_current_entries() if e.team_id != demo_team.id
    ]
    rng.shuffle(other_entries)
    for entry in other_entries[:40]:
        listing = MarketListingRecord(
            id=uuid4(),
            player_id=entry.player_id,
            source_team_id=entry.team_id,
            position=entry.position,
            cost=entry.cost,
            expected_value_score=entry.value_score,
        )
        store.listings[listing.id] = listing

    return store


def demo_team_id(store: Store) -> str:
    """Convenience for the /health payload and manual Swagger testing."""
    for team in store.teams.values():
        if team.name == DEMO_TEAM_NAME:
            return str(team.id)
    return ""
