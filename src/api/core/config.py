"""Application settings and the scoring weights from api.md section 4.

Weights live here rather than inline in the services so a threshold change lands
everywhere at once, and so GET /api/v1/version can expose them (a demo that shows
the thresholds are tunable rather than magic).
"""

from __future__ import annotations

from functools import lru_cache

from pydantic import AliasChoices, Field
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

    # --- agents ---
    agent_impl: str = Field(
        default="stub",
        description="'stub' (no API calls, no key) or 'anthropic' (the real agents, "
        "landing from the agent branch). Resolved in agents/base.py:get_agents().",
    )
    agent_model: str = Field(
        default="claude-opus-5",
        description="Model the agents run on.",
    )
    anthropic_api_key: str | None = Field(
        default=None,
        # Read from the conventional unprefixed name, not GM_ANTHROPIC_API_KEY.
        validation_alias=AliasChoices("ANTHROPIC_API_KEY", "GM_ANTHROPIC_API_KEY"),
        description="Required only when agent_impl='anthropic'. Lives in .env, "
        "which is gitignored.",
    )

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
    max_squad_size: int = 30
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
