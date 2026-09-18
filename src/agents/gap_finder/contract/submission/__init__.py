"""What the MODEL is trusted to author.

Note what is absent from these models: no problem_score, no severity, no
health_status, no euros. Those are joined in afterwards from
services/scoring.py.
"""

from .coverage_note import CoverageNote
from .gap_finder_submission import GapFinderSubmission
from .player_call import PlayerCall
from .position_call import PositionCall

__all__ = [
    "CoverageNote",
    "GapFinderSubmission",
    "PlayerCall",
    "PositionCall",
]
