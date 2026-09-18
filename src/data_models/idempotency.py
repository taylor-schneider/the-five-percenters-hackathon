"""A retained idempotency key for trader/execute (api.md 1).

Same key + identical body replays the stored response; same key + different
body is 409 IDEMPOTENCY_KEY_REUSED. request_hash is what tells them apart.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from uuid import UUID

from ._time import utcnow


@dataclass(slots=True)
class IdempotencyRecord:
    key: UUID
    request_hash: str
    """SHA-256 over the canonicalised request body."""
    response: dict[str, Any]
    created_at: datetime = field(default_factory=utcnow)
