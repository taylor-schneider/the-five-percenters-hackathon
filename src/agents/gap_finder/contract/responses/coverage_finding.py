"""api.md CoverageWarning plus the agent's discussion of it."""

from __future__ import annotations

from .....api.models.responses import CoverageWarning


class CoverageFinding(CoverageWarning):
    commentary: str | None = None
