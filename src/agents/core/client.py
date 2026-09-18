"""Anthropic client construction and the availability check.

The availability check is the contract that lets the API treat agents as an
enhancement rather than a dependency: ask once, cheaply, before committing to
an agent path.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

from .config import get_agent_settings
from .errors import AgentUnavailable


@lru_cache
def _client() -> Any:
    settings = get_agent_settings()
    try:
        import anthropic
    except ImportError as exc:  # pragma: no cover - environment-dependent
        raise AgentUnavailable(
            "the `anthropic` package is not installed (pip install -r requirements-agents.txt)"
        ) from exc
    # Bare constructor on purpose: it resolves ANTHROPIC_API_KEY, then
    # ANTHROPIC_AUTH_TOKEN, then an `ant auth login` profile. Passing api_key
    # explicitly would break the profile case.
    return anthropic.Anthropic(timeout=settings.request_timeout_seconds)


def get_client() -> Any:
    settings = get_agent_settings()
    if not settings.enabled:
        raise AgentUnavailable("agents are disabled (GM_AGENT_ENABLED=false)")
    return _client()


def is_available() -> bool:
    """True when an agent run is worth attempting.

    Deliberately makes no network call -- this is checked on every request and
    the answer only changes on deploy.

    Constructing the client is NOT sufficient evidence: `Anthropic()` builds
    happily with no credentials at all and only fails when a request is sent.
    So we check that something actually resolved, and we err towards False --
    a false negative costs a heuristic response, a false positive costs a
    failed request in front of the demo.
    """
    settings = get_agent_settings()
    if not settings.enabled:
        return False
    try:
        import anthropic  # noqa: F401
    except ImportError:
        return False
    if settings.api_key:
        return True
    try:
        client = _client()
    except Exception:
        return False
    if getattr(client, "api_key", None) or getattr(client, "auth_token", None):
        return True
    # Last possibility: an `ant auth login` profile, which the SDK resolves at
    # request time without materialising a key on the client.
    return (Path.home() / ".config" / "anthropic").exists()


def reset_client_cache() -> None:
    """Tests flip credentials between cases; the lru_cache would hide that."""
    _client.cache_clear()
