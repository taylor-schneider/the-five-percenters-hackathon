"""Structured logging and the trace_id middleware (api.md section 1)."""

from __future__ import annotations

import logging
import sys
import time
import uuid
from collections.abc import Awaitable, Callable

from fastapi import FastAPI, Request, Response

_CONFIGURED = False


def configure_logging(level: int = logging.INFO) -> None:
    global _CONFIGURED
    if _CONFIGURED:
        return
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)-7s %(name)s :: %(message)s")
    )
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level)
    _CONFIGURED = True


def get_logger(name: str) -> logging.Logger:
    configure_logging()
    return logging.getLogger(name)


logger = get_logger("api.request")


def register_request_middleware(app: FastAPI) -> None:
    """Attach a trace_id to every request and echo it as X-Request-Id.

    This is also the audit log required by api.md section 7 -- every /agents/
    call is logged with its trace_id, latency, and status.
    """

    @app.middleware("http")
    async def _trace(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        trace_id = request.headers.get("X-Request-Id") or f"req-{uuid.uuid4().hex[:12]}"
        request.state.trace_id = trace_id
        started = time.perf_counter()

        response = await call_next(request)

        elapsed_ms = int((time.perf_counter() - started) * 1000)
        response.headers["X-Request-Id"] = trace_id
        if request.url.path.startswith("/api/v1/agents/"):
            logger.info(
                "agent_call path=%s status=%s latency_ms=%s trace=%s",
                request.url.path,
                response.status_code,
                elapsed_ms,
                trace_id,
            )
        return response
