"""api.md TradeLeg plus the agent's note on it."""

from __future__ import annotations

from .....api.models.domain import ApiModel, TradeLeg


class AssessedLeg(ApiModel):
    """api.md TradeLeg plus the agent's note on it."""

    leg: TradeLeg
    commentary: str | None = None
