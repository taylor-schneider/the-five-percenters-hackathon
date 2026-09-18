"""What the API receives.

api.md section 5.8's response plus the one field that response has nowhere to
put: commentary. See README.md -- "the missing discussion field" -- for the
proposed api.md delta.
"""

from .coverage_finding import CoverageFinding
from .gap_finder_analysis import GapFinderAnalysis
from .player_finding import PlayerFinding
from .position_finding import PositionFinding

__all__ = [
    "CoverageFinding",
    "GapFinderAnalysis",
    "PlayerFinding",
    "PositionFinding",
]
