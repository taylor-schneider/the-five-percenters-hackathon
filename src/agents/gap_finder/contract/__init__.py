"""Gap Finder contract: what the model submits, and what the agent returns.

Two layers, deliberately separate:

`submission` holds the terminal tool's argument models -- everything the MODEL
is trusted to author. Note what is absent: no problem_score, no severity, no
health_status, no euros. Those are joined in afterwards from
services/scoring.py.

`responses` holds what the API receives: api.md section 5.8's response plus the
one field that response has nowhere to put: commentary. See README.md -- "the
missing discussion field" -- for the proposed api.md delta.
"""

from .responses import (
    CoverageFinding,
    GapFinderAnalysis,
    PlayerFinding,
    PositionFinding,
)
from .submission import (
    CoverageNote,
    GapFinderSubmission,
    PlayerCall,
    PositionCall,
)

__all__ = [
    "CoverageFinding",
    "CoverageNote",
    "GapFinderAnalysis",
    "GapFinderSubmission",
    "PlayerCall",
    "PlayerFinding",
    "PositionCall",
    "PositionFinding",
]
