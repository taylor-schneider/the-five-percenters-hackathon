"""Error envelope, error codes, and exception handlers (api.md section 6).

Every non-2xx response uses ErrorEnvelope, INCLUDING FastAPI's own 422s. The
handler below rewrites RequestValidationError into the same shape -- without it
you ship two error formats and the frontend has to branch on status code to
parse them.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from starlette.exceptions import HTTPException as StarletteHTTPException

from .logging import get_logger

logger = get_logger(__name__)


class ErrorCode(StrEnum):
    """api.md section 6.2. Hard violation codes double as 409 error codes."""

    VALIDATION_ERROR = "VALIDATION_ERROR"

    TEAM_NOT_FOUND = "TEAM_NOT_FOUND"
    PLAYER_NOT_FOUND = "PLAYER_NOT_FOUND"
    TRADE_NOT_FOUND = "TRADE_NOT_FOUND"
    LISTING_NOT_FOUND = "LISTING_NOT_FOUND"

    OPPORTUNITY_EXPIRED = "OPPORTUNITY_EXPIRED"
    INVALID_LEG_COMBINATION = "INVALID_LEG_COMBINATION"
    CONFIRMATION_REQUIRED = "CONFIRMATION_REQUIRED"
    STALE_ROSTER_VERSION = "STALE_ROSTER_VERSION"
    IDEMPOTENCY_KEY_REUSED = "IDEMPOTENCY_KEY_REUSED"

    # Hard violations -- appear as Violation entries in a 200 simulate, and as
    # the error code on a 409 from execute.
    BUDGET_CAP_EXCEEDED = "BUDGET_CAP_EXCEEDED"
    POSITION_MINIMUM_VIOLATED = "POSITION_MINIMUM_VIOLATED"
    PLAYER_NOT_AVAILABLE = "PLAYER_NOT_AVAILABLE"
    PLAYER_NOT_ON_ROSTER = "PLAYER_NOT_ON_ROSTER"
    DUPLICATE_PLAYER_IN_TRADE = "DUPLICATE_PLAYER_IN_TRADE"

    # Soft violations -- never block, only ever appear as Violation entries.
    HIGH_UNCERTAINTY = "HIGH_UNCERTAINTY"
    POSITION_CHURN = "POSITION_CHURN"

    UNAUTHORIZED = "UNAUTHORIZED"
    EXECUTION_FAILED = "EXECUTION_FAILED"
    INTERNAL_ERROR = "INTERNAL_ERROR"


#: Codes that block execution. Reused by the trader service so the hard/soft
#: split is defined once.
HARD_VIOLATION_CODES: frozenset[ErrorCode] = frozenset(
    {
        ErrorCode.BUDGET_CAP_EXCEEDED,
        ErrorCode.POSITION_MINIMUM_VIOLATED,
        ErrorCode.PLAYER_NOT_AVAILABLE,
        ErrorCode.PLAYER_NOT_ON_ROSTER,
        ErrorCode.DUPLICATE_PLAYER_IN_TRADE,
    }
)


class ErrorDetail(BaseModel):
    code: ErrorCode
    message: str
    details: dict[str, Any] = Field(default_factory=dict)
    trace_id: str | None = None


class ErrorEnvelope(BaseModel):
    """The shape of every non-2xx response body."""

    error: ErrorDetail

    model_config = {
        "json_schema_extra": {
            "example": {
                "error": {
                    "code": "BUDGET_CAP_EXCEEDED",
                    "message": "Trade would exceed team budget cap",
                    "details": {"post_trade_cost": 51000000, "budget_cap": 50000000},
                    "trace_id": "req-abc-123",
                }
            }
        }
    }


class AppError(Exception):
    """Raise this anywhere; the handler turns it into an ErrorEnvelope."""

    def __init__(
        self,
        code: ErrorCode,
        message: str,
        status_code: int = status.HTTP_400_BAD_REQUEST,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.details = details or {}


# --- convenience constructors for the common cases -------------------------


def not_found(code: ErrorCode, message: str, **details: Any) -> AppError:
    return AppError(code, message, status.HTTP_404_NOT_FOUND, details)


def conflict(code: ErrorCode, message: str, **details: Any) -> AppError:
    return AppError(code, message, status.HTTP_409_CONFLICT, details)


def bad_request(code: ErrorCode, message: str, **details: Any) -> AppError:
    return AppError(code, message, status.HTTP_400_BAD_REQUEST, details)


def gone(code: ErrorCode, message: str, **details: Any) -> AppError:
    return AppError(code, message, status.HTTP_410_GONE, details)


# --- handlers ---------------------------------------------------------------


def _trace_id(request: Request) -> str:
    return getattr(request.state, "trace_id", "unknown")


def _envelope(
    request: Request, status_code: int, code: ErrorCode, message: str, details: dict[str, Any]
) -> JSONResponse:
    trace_id = _trace_id(request)
    body = ErrorEnvelope(
        error=ErrorDetail(code=code, message=message, details=details, trace_id=trace_id)
    )
    return JSONResponse(
        status_code=status_code,
        content=body.model_dump(mode="json"),
        headers={"X-Request-Id": trace_id},
    )


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def _app_error(request: Request, exc: AppError) -> JSONResponse:
        logger.warning(
            "app_error code=%s status=%s trace=%s", exc.code, exc.status_code, _trace_id(request)
        )
        return _envelope(request, exc.status_code, exc.code, exc.message, exc.details)

    @app.exception_handler(RequestValidationError)
    async def _validation_error(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        # D6: 422 is reserved exclusively for schema validation.
        return _envelope(
            request,
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            ErrorCode.VALIDATION_ERROR,
            "Request payload failed schema validation",
            {"fields": _serialisable_errors(exc)},
        )

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = {
            401: ErrorCode.UNAUTHORIZED,
            403: ErrorCode.UNAUTHORIZED,
            404: ErrorCode.TEAM_NOT_FOUND,
        }.get(exc.status_code, ErrorCode.INTERNAL_ERROR)
        return _envelope(request, exc.status_code, code, str(exc.detail), {})

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception) -> JSONResponse:
        logger.exception("unhandled error trace=%s", _trace_id(request))
        return _envelope(
            request,
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            ErrorCode.INTERNAL_ERROR,
            "An unexpected error occurred",
            {},
        )


def _serialisable_errors(exc: RequestValidationError) -> list[dict[str, Any]]:
    """Pydantic errors can carry non-JSON values in `ctx`; strip them."""
    out: list[dict[str, Any]] = []
    for err in exc.errors():
        out.append(
            {
                "loc": [str(p) for p in err.get("loc", ())],
                "msg": err.get("msg", ""),
                "type": err.get("type", ""),
            }
        )
    return out


#: Reusable OpenAPI `responses=` fragments so Swagger documents error cases and
#: generated clients get an error type.
def error_responses(*status_codes: int) -> dict[int | str, dict[str, Any]]:
    descriptions = {
        400: "Malformed request the schema cannot catch",
        401: "Missing or invalid API key",
        404: "Referenced entity does not exist",
        409: "Valid request, invalid state or business rule",
        410: "Referenced ephemeral resource has expired",
        422: "Payload failed schema validation",
        500: "Unexpected failure",
        503: "Dependency unavailable",
    }
    return {
        code: {"model": ErrorEnvelope, "description": descriptions.get(code, "Error")}
        for code in status_codes
    }
