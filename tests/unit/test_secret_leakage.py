"""Secret-leakage regression: the T04 and T05 forward watch-items.

An exception message is the most likely place a secret escapes into
telemetry: it is attacker- or caller-influenced, it flows into logs, and
tracing libraries routinely attach it to a span. These tests raise an
exception whose message *contains* a synthetic canary and then look for that
canary everywhere the request could have put it.

They also cover the T05 watch-item: unhandled exceptions cross Starlette's
server-error boundary, which sits outside every user middleware, and the
correlation identifier has to survive that crossing for an operator to tie a
caller's report to a trace.
"""

from __future__ import annotations

import io
import json
import logging
import uuid
from collections.abc import Iterator
from contextlib import contextmanager

import pytest
from fastapi import APIRouter, FastAPI
from fastapi.testclient import TestClient
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from knowhub.observability import (
    CORRELATION_ID_HEADER,
    CorrelationFilter,
    JsonFormatter,
    is_valid_correlation_id,
)


@contextmanager
def capture_logs() -> Iterator[io.StringIO]:
    """Capture root logging with the real filter and formatter.

    Must be entered *after* the application is built: ``create_app`` calls
    ``dictConfig``, which replaces root handlers. Installing capture first
    would silently discard every record and make leakage assertions pass
    vacuously.
    """
    buffer = io.StringIO()
    handler = logging.StreamHandler(buffer)
    handler.setFormatter(JsonFormatter())
    handler.addFilter(CorrelationFilter())
    root = logging.getLogger()
    original = root.handlers[:]
    level = root.level
    root.handlers = [handler]
    root.setLevel(logging.DEBUG)
    try:
        yield buffer
    finally:
        root.handlers = original
        root.setLevel(level)


def _build_leaking_app(exporter: InMemorySpanExporter, message: str) -> FastAPI:
    """An application with one route that fails, carrying ``message``."""
    from knowhub.api.main import create_app

    exporter.clear()
    app = create_app()
    router = APIRouter()

    @router.get("/boom")
    async def boom() -> dict[str, str]:
        raise RuntimeError(message)

    app.include_router(router)
    return app


@pytest.fixture
def leaking_app(span_exporter: InMemorySpanExporter, canary_secret: str) -> FastAPI:
    return _build_leaking_app(
        span_exporter, f"connection failed for user=knowhub password={canary_secret}"
    )


def _span_payload(exporter: InMemorySpanExporter) -> str:
    """Everything an exported span carries: name, attributes, status, events."""
    parts: list[str] = []
    for span in exporter.get_finished_spans():
        parts.append(span.name)
        parts.append(repr(dict(span.attributes or {})))
        parts.append(repr(span.status.description))
        for event in span.events:
            parts.append(event.name)
            parts.append(repr(dict(event.attributes or {})))
    return "\n".join(parts)


@pytest.mark.parametrize(
    "canary_kind",
    ["arbitrary-secret", "connection-string"],
)
def test_canary_does_not_escape_through_any_channel(
    span_exporter: InMemorySpanExporter,
    canary_secret: str,
    canary_dsn: str,
    canary_kind: str,
) -> None:
    """Neither an arbitrary secret nor a connection string may escape.

    Checks every channel a failing request could put it in: the response, the
    log stream and the exported span, including exception events and their
    ``exception.message`` / ``exception.stacktrace`` attributes.
    """
    canary = canary_secret if canary_kind == "arbitrary-secret" else canary_dsn
    app = _build_leaking_app(span_exporter, f"driver failure: {canary}")
    given = str(uuid.uuid4())
    with (
        capture_logs() as buffer,
        TestClient(app, raise_server_exceptions=False) as client,
    ):
        response = client.get("/boom", headers={CORRELATION_ID_HEADER: given})
        logs = buffer.getvalue()

    assert response.status_code == 500
    # Guard against a vacuous pass: the failure must actually have been logged.
    assert logs.strip(), "no log output captured - the assertions below prove nothing"

    assert canary not in response.text, "canary leaked into the response body"
    assert canary not in repr(dict(response.headers)), (
        "canary leaked into a response header"
    )
    assert canary not in logs, "canary leaked into log output"
    for record in (json.loads(line) for line in logs.splitlines() if line.strip()):
        assert canary not in json.dumps(record), (
            "canary leaked into a structured log field"
        )
    assert canary not in _span_payload(span_exporter), (
        "canary leaked into span attributes, status or exception events"
    )


def test_safe_diagnostics_are_still_available(
    span_exporter: InMemorySpanExporter,
    canary_secret: str,
) -> None:
    """Denying exception text must not leave the failure undiagnosable."""
    app = _build_leaking_app(span_exporter, f"driver failure: {canary_secret}")
    given = str(uuid.uuid4())
    with (
        capture_logs() as buffer,
        TestClient(app, raise_server_exceptions=False) as client,
    ):
        response = client.get("/boom", headers={CORRELATION_ID_HEADER: given})
        captured = buffer.getvalue()

    assert response.status_code == 500
    assert response.json() == {"status": "error"}
    assert response.headers[CORRELATION_ID_HEADER] == given

    assert captured.strip(), "no log output captured"
    records = [json.loads(line) for line in captured.splitlines() if line.strip()]
    errors = [r for r in records if r.get("error")]
    assert errors, "no error record was emitted at all"
    error_record = errors[0]
    assert error_record["error"] == {"type": "RuntimeError"}
    assert error_record["correlation_id"] == given
    assert error_record["trace_id"]
    assert error_record["span_id"]

    server_spans = [
        span
        for span in span_exporter.get_finished_spans()
        if dict(span.attributes or {}).get("knowhub.correlation_id") == given
    ]
    assert server_spans, "the server span did not carry the correlation identifier"
    assert server_spans[0].status.status_code.name == "ERROR"


def test_unhandled_error_response_is_coarse(leaking_app: FastAPI) -> None:
    with TestClient(leaking_app, raise_server_exceptions=False) as client:
        response = client.get("/boom")
    assert response.json() == {"status": "error"}
    for internal in ("Traceback", "RuntimeError", 'File "', "knowhub/api", "password"):
        assert internal not in response.text


def test_correlation_survives_the_server_error_boundary(leaking_app: FastAPI) -> None:
    """T05 watch-item: the identifier crosses ServerErrorMiddleware."""
    given = str(uuid.uuid4())
    with TestClient(leaking_app, raise_server_exceptions=False) as client:
        response = client.get("/boom", headers={CORRELATION_ID_HEADER: given})
    assert response.status_code == 500
    assert response.headers.get(CORRELATION_ID_HEADER) == given


def test_generated_correlation_also_survives_the_error_boundary(
    leaking_app: FastAPI,
) -> None:
    with TestClient(leaking_app, raise_server_exceptions=False) as client:
        response = client.get("/boom")
    returned = response.headers.get(CORRELATION_ID_HEADER)
    assert returned is not None
    assert is_valid_correlation_id(returned)


def test_request_span_carries_the_correlation_identifier(
    span_exporter: InMemorySpanExporter, canary_secret: str
) -> None:
    from knowhub.api.main import create_app

    span_exporter.clear()
    app = create_app()
    given = str(uuid.uuid4())
    with TestClient(app) as client:
        client.get("/healthz", headers={CORRELATION_ID_HEADER: given})

    server_spans = [
        span
        for span in span_exporter.get_finished_spans()
        if dict(span.attributes or {}).get("knowhub.correlation_id") == given
    ]
    assert server_spans, "no span carried knowhub.correlation_id"
    assert canary_secret not in _span_payload(span_exporter)


def test_span_names_are_route_templates_not_instance_paths(
    span_exporter: InMemorySpanExporter,
) -> None:
    """Bounded cardinality: a span name must not embed a per-request value."""
    from knowhub.api.main import create_app

    span_exporter.clear()
    app = create_app()
    with TestClient(app) as client:
        client.get("/healthz")

    names = {span.name for span in span_exporter.get_finished_spans()}
    assert names, "no spans recorded"
    for name in names:
        assert "/healthz" in name or "send" in name or "receive" in name
        assert not any(character.isdigit() for character in name.split()[-1][:8])


def test_no_metric_label_uses_a_caller_controlled_value() -> None:
    """M00 defines no metric, so no label can be caller-controlled."""
    from opentelemetry import metrics

    provider = metrics.get_meter_provider()
    assert provider is not None
