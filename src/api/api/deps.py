"""Shared FastAPI dependencies."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Header, Request, status

from ..core.config import Settings, get_settings
from ..core.errors import AppError, ErrorCode
from ..repositories.store import Store, get_store

StoreDep = Annotated[Store, Depends(get_store)]
SettingsDep = Annotated[Settings, Depends(get_settings)]


async def require_api_key(
    x_api_key: Annotated[str | None, Header(alias="x-api-key")] = None,
    settings: SettingsDep = None,  # type: ignore[assignment]
) -> None:
    """api.md section 7. Off by default so Swagger 'Try it out' works with zero
    setup; enable with GM_REQUIRE_API_KEY=true."""
    settings = settings or get_settings()
    if not settings.require_api_key:
        return
    if x_api_key != settings.api_key:
        raise AppError(
            ErrorCode.UNAUTHORIZED,
            "Missing or invalid x-api-key header",
            status.HTTP_401_UNAUTHORIZED,
        )


def current_user(request: Request) -> str:
    """Stand-in for JWT identity. Phase 2 reads this from the token instead, and
    TradeRecord.initiated_by stops trusting anything client-supplied."""
    return request.headers.get("x-user", "gm@hackathon.local")


ApiKeyDep = Depends(require_api_key)
UserDep = Annotated[str, Depends(current_user)]
