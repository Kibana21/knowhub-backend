"""HTTP middleware for the KnowHub API.

The correlation identifier's representation, bounds and validation live in
``knowhub.observability.correlation``. This module is the HTTP *integration*
only: it reads the header, hands the value to the canonical coercion function
and binds the result for the request. It deliberately contains no UUID
pattern, no length bound and no validation logic of its own — a second
implementation would drift from the one a future worker process uses.

Implemented as a pure ASGI middleware rather than ``BaseHTTPMiddleware``:
``BaseHTTPMiddleware`` runs the downstream application in a separate task, so
a context variable bound there is not reliably visible to the endpoint. Pure
ASGI keeps the request in one task, which is what makes the ambient
correlation context work across ``await`` boundaries.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from opentelemetry import trace
from starlette.datastructures import Headers, MutableHeaders

from knowhub.observability import (
    CORRELATION_ID_HEADER,
    coerce_correlation_id,
    set_correlation_id,
)

if TYPE_CHECKING:
    from starlette.types import ASGIApp, Message, Receive, Scope, Send

__all__ = ["CORRELATION_SCOPE_KEY", "CorrelationIdMiddleware"]

#: Where the request's correlation identifier is published on the ASGI scope.
#: The ambient context variable is the normal way to read it, but Starlette's
#: server-error handling runs *outside* user middleware, by which point the
#: context has been reset. The scope survives that boundary, so the error
#: handler can still label its response.
CORRELATION_SCOPE_KEY = "knowhub.correlation_id"

#: Span attribute carrying the correlation identifier. Bounded by the span,
#: never used as a span name or metric label (see docs/telemetry-naming.md).
_CORRELATION_SPAN_ATTRIBUTE = "knowhub.correlation_id"


class CorrelationIdMiddleware:
    """Bind a correlation identifier for the request and echo it back."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        inbound = Headers(scope=scope).get(CORRELATION_ID_HEADER)
        # Caller input goes straight to the canonical coercion: valid values
        # are honoured, everything else is replaced with a generated
        # identifier. Nothing unvalidated reaches telemetry.
        correlation_id = coerce_correlation_id(inbound)
        scope[CORRELATION_SCOPE_KEY] = correlation_id
        token = set_correlation_id(correlation_id)

        span = trace.get_current_span()
        if span.is_recording():
            span.set_attribute(_CORRELATION_SPAN_ATTRIBUTE, correlation_id)

        async def send_with_correlation(message: Message) -> None:
            if message["type"] == "http.response.start":
                MutableHeaders(scope=message)[CORRELATION_ID_HEADER] = correlation_id
            await send(message)

        try:
            await self.app(scope, receive, send_with_correlation)
        finally:
            token.var.reset(token)
