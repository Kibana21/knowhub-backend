"""FastAPI application bootstrap.

Wiring order is fixed (M00-SPEC-001 R8, M00-SPEC-003 R2):

1. load and validate settings — a misconfigured process fails here, at
   startup, rather than at first use;
2. initialise observability — before the application begins serving, so no
   request is handled untraced;
3. construct the application, attach middleware, register the probes.

Nothing constructs the application before configuration has been validated,
and neither step is swallowed: a configuration or telemetry failure
propagates and the process does not start.

M00 registers exactly two routes, both operational. No business route,
router, persistence, authentication, session or dependency client exists yet
(R11).
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from opentelemetry import trace
from opentelemetry.trace import Status, StatusCode

from knowhub.api.health import ReadinessState
from knowhub.api.health import router as health_router
from knowhub.api.middleware import CORRELATION_SCOPE_KEY, CorrelationIdMiddleware
from knowhub.config import Settings, get_settings
from knowhub.observability import (
    CORRELATION_ID_HEADER,
    bind_correlation_id,
    configure_observability,
    shutdown_observability,
)

#: ``app`` is not bound here: it is provided lazily by ``__getattr__``
#: below, so importing this module has no side effects.
__all__ = ["create_app"]

_logger = logging.getLogger(__name__)


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Own the process lifecycle for resources this application created."""
    _logger.info("api startup complete")
    try:
        yield
    finally:
        # Stop advertising readiness before tearing telemetry down, so a
        # draining process reports not-ready while it finishes in flight.
        state: ReadinessState = app.state.readiness
        state.observability_ready = False
        _logger.info("api shutdown: draining")
        shutdown_observability()


def _install_instrumentation(app: FastAPI) -> None:
    """Attach OTel FastAPI instrumentation exactly once.

    Added *after* the correlation middleware so the tracing middleware sits
    outermost: a server span is then already recording when the correlation
    middleware runs and can carry the identifier as an attribute.
    """
    if getattr(app, "_is_instrumented_by_opentelemetry", False):
        return
    # Imported here rather than at module scope so the instrumentation
    # dependency is only touched when an app is actually built.
    # The package ships no type stubs and no py.typed marker; the suppression
    # is scoped to this one import rather than relaxing the rule repo-wide.
    from opentelemetry.instrumentation.fastapi import (  # pyright: ignore[reportMissingTypeStubs]
        FastAPIInstrumentor,
    )

    FastAPIInstrumentor.instrument_app(app)


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build the application, in the order the specification fixes."""
    resolved = settings if settings is not None else get_settings()
    readiness = ReadinessState(settings_loaded=True)

    configure_observability(resolved)
    readiness.observability_ready = True

    app = FastAPI(
        title="KnowHub backend",
        version="0.0.0",
        lifespan=_lifespan,
        # The generated schema and documentation routes are disabled at M00.
        # The backend owns the OpenAPI contract (ADR-017), but M00 introduces
        # no business API surface, so there is no contract to publish, and
        # publishing one describing only the probes would create an artifact
        # M1 has to unpick. They return with the first business endpoint.
        openapi_url=None,
        docs_url=None,
        redoc_url=None,
    )
    app.state.readiness = readiness
    app.state.settings = resolved

    app.add_middleware(CorrelationIdMiddleware)
    _install_instrumentation(app)

    app.add_exception_handler(Exception, _handle_unexpected_error)
    app.include_router(health_router)
    return app


async def _handle_unexpected_error(request: Request, exc: Exception) -> JSONResponse:
    """Return a coarse 500 and record the failure safely.

    The response carries no message, no stack trace and no internal detail —
    only the correlation identifier, which is what ties the caller's report to
    the operator's telemetry.

    The span is marked failed with the exception *type* and a fixed
    description. The exception's message is deliberately not placed on the
    span: a message can carry values from the failing call, and telemetry is
    not the place to find that out.

    Starlette routes unhandled exceptions to its server-error middleware,
    which sits outside every user middleware. The correlation context has
    been reset by then, so the identifier is read from the ASGI scope, where
    the correlation middleware published it.
    """
    correlation_id = request.scope.get(CORRELATION_SCOPE_KEY)
    span = trace.get_current_span()
    if span.is_recording():
        span.set_status(Status(StatusCode.ERROR, "unhandled error"))
        span.set_attribute("knowhub.error.type", type(exc).__name__)

    # Re-establish the ambient correlation for the duration of this log call.
    # The context was reset when the request left the correlation middleware,
    # so without this the record describing the failure would carry no
    # correlation identifier and could not be joined to the caller's report or
    # to the rest of the request's telemetry.
    log_extra = {"http_route": request.scope.get("route_path") or "unknown"}
    if isinstance(correlation_id, str):
        with bind_correlation_id(correlation_id):
            _logger.exception("unhandled error serving request", extra=log_extra)
    else:
        _logger.exception("unhandled error serving request", extra=log_extra)

    headers = {CORRELATION_ID_HEADER: correlation_id} if correlation_id else {}
    return JSONResponse(
        status_code=500,
        content={"status": "error"},
        headers=headers,
    )


#: Memoised application for the module-level ``app`` attribute. Built on first
#: access, then reused: a server may resolve ``module:app`` more than once
#: while starting, and each build would otherwise construct a whole new
#: application and re-run telemetry bootstrap.
_app: FastAPI | None = None


def __getattr__(name: str) -> object:
    """Build the application lazily on first attribute access, then reuse it.

    ``uvicorn knowhub.api.main:app`` resolves ``app`` by attribute lookup, so
    the documented process command keeps working (blueprint §30.1). Binding it
    eagerly at module scope would make *importing* this package require valid
    configuration and would initialise telemetry providers as an import side
    effect — which breaks introspection, tooling and testing, and makes the
    cost of an import invisible at the call site.

    The result is cached because the attribute is not necessarily read once.
    Without that, a second read builds a second application and calls
    ``configure_observability`` again; OpenTelemetry refuses to replace an
    installed provider, so the second set is discarded and the process logs
    "Overriding of current TracerProvider is not allowed" — wasted work and a
    misleading log line.
    """
    global _app
    if name == "app":
        if _app is None:
            _app = create_app()
        return _app
    message = f"module {__name__!r} has no attribute {name!r}"
    raise AttributeError(message)
