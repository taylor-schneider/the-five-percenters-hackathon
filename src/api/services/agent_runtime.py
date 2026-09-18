"""AgentMeta construction -- the explainability and reproducibility hook.

Every agent response carries one of these. `input_snapshot_hash` is a SHA-256
over the canonicalised agent input, which is what lets you prove after the fact
which roster state a recommendation was made against (api.md section 3.14).
"""

from __future__ import annotations

import hashlib
import json
import time
from contextlib import contextmanager
from typing import Any, Iterator

from ..core.config import get_settings
from ..models.domain import AgentMeta
from ..models.enums import AgentMode, AgentName
from ..repositories.store import utcnow


def snapshot_hash(payload: Any) -> str:
    """Stable hash of an agent's input. Keys sorted so the same logical input
    always produces the same hash regardless of dict ordering."""
    canonical = json.dumps(payload, sort_keys=True, default=str, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()


@contextmanager
def agent_run(agent_name: AgentName, payload: Any) -> Iterator[list[AgentMeta]]:
    """Time an agent call and yield a one-slot list that receives its AgentMeta.

        with agent_run(AgentName.GAP_FINDER, request) as meta:
            ...
        return Response(..., agent_meta=meta[0])
    """
    settings = get_settings()
    digest = snapshot_hash(payload)
    started = time.perf_counter()
    holder: list[AgentMeta] = []
    try:
        yield holder
    finally:
        holder.append(
            AgentMeta(
                agent_name=agent_name,
                # Phase 1 is deterministic heuristics; Phase 2 swaps in LLM calls
                # behind the same schema and flips this to AgentMode.LLM (D11).
                mode=AgentMode.HEURISTIC,
                version=settings.agent_version,
                model=None,
                input_snapshot_hash=digest,
                latency_ms=int((time.perf_counter() - started) * 1000),
                generated_at=utcnow(),
            )
        )
