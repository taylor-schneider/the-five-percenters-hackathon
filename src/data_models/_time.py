"""Shared clock. Lives here so records and the store agree on one source."""

from __future__ import annotations

from datetime import datetime, timezone


def utcnow() -> datetime:
    return datetime.now(timezone.utc)
