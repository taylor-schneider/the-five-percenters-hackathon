"""api.md FlaggedPlayer plus the agent's discussion of it."""

from __future__ import annotations

from .....api.models.responses import FlaggedPlayer


class PlayerFinding(FlaggedPlayer):
    commentary: str
