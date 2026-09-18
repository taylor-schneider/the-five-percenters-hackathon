"""Application settings and the scoring weights from api.md section 4.

Weights live here rather than inline in the services so a threshold change lands
everywhere at once, and so GET /api/v1/version can expose them (a demo that shows
the thresholds are tunable rather than magic).
"""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from ..models.enums import PositionGroup


class ScoringWeights(BaseSettings):
    """api.md section 4."""

    # problem_score = w1*value_gap + w2*cost_penalty + w3*coverage_penalty
    w1: float = 0.45
    w2: float = 0.35
    w3: float = 0.20

    # opportunity_score = a1*value_gain + a2*cost_saving - a3*risk
    a1: float = 0.50
    a2: float = 0.35
    a3: float = 0.15

    # Traffic-light thresholds
    red_threshold: float = 0.67
    green_threshold: float = 0.34


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="GM_", env_file=".env", extra="ignore"
    )

    # --- app metadata ---
    api_version: str = "v1"
    build: str = "2026-09-18.1"
    git_sha: str = "dev"
    agent_version: str = "1.0.0"

    # --- server ---
    host: str = "0.0.0.0"  # bind address; clients call http://localhost:8000
    port: int = 8000

    # --- security (api.md section 7) ---
    api_key: str = Field(
        default="hackathon-dev-key",
        description="Shared key checked on /api/v1. Override with GM_API_KEY.",
    )
    require_api_key: bool = Field(
        default=False,
        description="Off by default so Swagger 'Try it out' works with zero setup. "
        "Turn on with GM_REQUIRE_API_KEY=true.",
    )
    cors_origins: list[str] = Field(
        default=["http://localhost:5173", "http://localhost:3000"],
        description="Never ship allow_origins=['*'], even in the demo.",
    )

    # --- business rules ---
    # No squad maximum: budget is the only constraint on roster growth,
    # so a club can grow as large as its remaining cap allows.
    #: Fallback only -- the live values are loaded from data/positions.csv.
    default_min_position_group_counts: dict[PositionGroup, int] = Field(
        default_factory=lambda: {
            PositionGroup.GK: 2,
            PositionGroup.DEF: 6,
            PositionGroup.MID: 6,
            PositionGroup.FWD: 4,
        }
    )

    # --- opportunity cache ---
    opportunity_ttl_seconds: int = 900  # 15 minutes
    idempotency_ttl_seconds: int = 86_400  # 24 hours

    # --- seed data ---
    seed_teams: int = 12
    seed_random_state: int = 20260918

    weights: ScoringWeights = Field(default_factory=ScoringWeights)


@lru_cache
def get_settings() -> Settings:
    return Settings()
