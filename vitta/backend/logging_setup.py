"""Structured logging + request-ID middleware.

configure_logging() runs once at process start (from main.py); after that
every module gets its logger via `structlog.get_logger(__name__)` and the
current request's id is auto-attached to every log line for the duration
of that request via a ContextVar.

Format is chosen by the LOG_FORMAT env var:
  - LOG_FORMAT=json  -> single-line JSON per event (prod, log aggregators)
  - anything else    -> coloured, aligned key=value (dev)

The middleware:
  1. Reads an inbound X-Request-ID header if present; generates a fresh
     hex id otherwise. Same request that came from a load balancer keeps
     the id the LB assigned it, so a single trace spans hops.
  2. Puts that id into a ContextVar so structlog's merge_contextvars
     processor picks it up without every log call having to pass it.
  3. Echoes the id back in the response's X-Request-ID header so the
     client (and any downstream service) can correlate.
  4. Logs one access line per request, at info for 2xx/3xx and warning
     for 4xx/5xx, including method, path, status, and duration_ms.
"""

from __future__ import annotations

import logging
import os
import secrets
import sys
import time
from contextvars import ContextVar

import structlog
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import ASGIApp

REQUEST_ID_HEADER = "X-Request-ID"

# The current request's id, or None outside a request. structlog's
# merge_contextvars processor reads whatever we bind to it via
# structlog.contextvars.bind_contextvars() below.
_request_id_var: ContextVar[str | None] = ContextVar("request_id", default=None)


def current_request_id() -> str | None:
    """Read the current request id, for callers that need to attach it to
    something other than a log line (an outbound API call, a job record).
    Returns None outside a request context."""
    return _request_id_var.get()


def configure_logging() -> None:
    """Configure structlog + stdlib logging once at process start.

    Idempotent by construction (structlog.configure replaces prior state),
    so calling it twice — e.g. under `uvicorn --reload` — is safe.
    """
    log_format = os.environ.get("LOG_FORMAT", "console").lower()
    log_level_name = os.environ.get("LOG_LEVEL", "INFO").upper()
    log_level = getattr(logging, log_level_name, logging.INFO)

    # Route stdlib logging (which uvicorn and everything else in the
    # ecosystem uses) through structlog so the format is uniform across
    # our own log calls and third-party ones. Level filtering happens
    # here — structlog itself doesn't filter.
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=log_level,
        force=True,
    )

    # Silence uvicorn's default access log — we emit our own from the
    # RequestIDMiddleware below so the request-id is included and the
    # line matches the JSON/console shape of the rest of the logs.
    logging.getLogger("uvicorn.access").disabled = True

    shared_processors: list = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]

    if log_format == "json":
        renderer: structlog.types.Processor = structlog.processors.JSONRenderer()
    else:
        renderer = structlog.dev.ConsoleRenderer(colors=sys.stdout.isatty())

    structlog.configure(
        processors=[*shared_processors, renderer],
        wrapper_class=structlog.make_filtering_bound_logger(log_level),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )


class RequestIDMiddleware(BaseHTTPMiddleware):
    """Attach a request-id to every request; log one access line per
    request; echo the id back in the response header.

    Uses BaseHTTPMiddleware (not raw ASGI middleware) because Starlette's
    Request/Response objects give a clean way to read/write headers, and
    the small overhead is fine at Vitta's request rates.
    """

    def __init__(self, app: ASGIApp) -> None:
        super().__init__(app)
        self._log = structlog.get_logger("vitta.access")

    async def dispatch(self, request: Request, call_next):
        inbound = request.headers.get(REQUEST_ID_HEADER)
        request_id = _sanitize_id(inbound) if inbound else secrets.token_hex(8)

        token = _request_id_var.set(request_id)
        structlog.contextvars.bind_contextvars(request_id=request_id)

        start = time.perf_counter()
        response: Response
        status_code = 500
        try:
            response = await call_next(request)
            status_code = response.status_code
        except Exception as exc:
            # Log the failure with the request-id attached, then re-raise
            # so FastAPI's own exception handling still runs.
            self._log.exception(
                "request_failed",
                method=request.method,
                path=request.url.path,
                error=repr(exc),
                duration_ms=round((time.perf_counter() - start) * 1000, 2),
            )
            raise
        finally:
            structlog.contextvars.unbind_contextvars("request_id")
            _request_id_var.reset(token)

        response.headers[REQUEST_ID_HEADER] = request_id

        duration_ms = round((time.perf_counter() - start) * 1000, 2)
        log = self._log.warning if status_code >= 400 else self._log.info
        log(
            "http_access",
            method=request.method,
            path=request.url.path,
            status=status_code,
            duration_ms=duration_ms,
            request_id=request_id,
        )
        return response


def _sanitize_id(candidate: str) -> str:
    """Trust-but-verify an inbound X-Request-ID: cap length and keep only
    a safe character set. Prevents a client from injecting whitespace,
    control chars, or a 10KB blob into every downstream log line."""
    safe = "".join(c for c in candidate if c.isalnum() or c in "-_")
    return safe[:64] if safe else secrets.token_hex(8)
