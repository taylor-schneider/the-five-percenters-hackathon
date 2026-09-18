"""api.md FlaggedPosition plus the agent's discussion of it."""

from __future__ import annotations

from .....api.models.responses import FlaggedPosition


class PositionFinding(FlaggedPosition):
    """api.md FlaggedPosition plus the agent's discussion of it."""

    commentary: str
