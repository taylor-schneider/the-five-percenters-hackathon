"""A retained idempotency key for POST /agents/trader/execute (api.md 1).

Replaying a key with an identical body returns the stored response verbatim;
replaying with a different body is a 409 IDEMPOTENCY_KEY_REUSED. `request_hash`
is what distinguishes the two, so it must be taken over the canonicalised body.

Retention is 24 hours.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from uuid import UUID


@dataclass(slots=True)
class IdempotencyRecord:
    key: UUID
    request_hash: str
    """SHA-256 over the canonicalised request body."""
    created_at: datetime
    expires_at: datetime
    response_body: dict[str, Any] = field(default_factory=dict)
    """The original 200, replayed verbatim under `Idempotency-Replayed: true`."""
