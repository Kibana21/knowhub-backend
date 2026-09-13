"""A field-level safety boundary on exported spans.

Framework instrumentation records exceptions automatically. In
``opentelemetry-api`` 1.44.0, ``trace.use_span`` does two things when an
exception escapes the block it wraps:

* ``span.record_exception(exc)`` — an ``exception`` event carrying
  ``exception.message`` and ``exception.stacktrace``;
* ``span.set_status(Status(ERROR, f"{type(exc).__name__}: {exc}"))`` — a status
  description carrying the message again.

Both default to on and neither the ASGI nor the FastAPI instrumentation
(0.65b0) exposes a parameter to disable them, so the application cannot
prevent an exception's text from being recorded.

An exception message is caller-influenced and routinely carries the values of
the failing call — database drivers put connection details into
``OperationalError``. Exporting it unfiltered would breach
**M00-SPEC-003 R12**.

This module closes that at the export boundary: arbitrary exception payload
text is **unsafe by default** and removed, while the structural facts that make
a failure diagnosable are preserved. It is an allow-list, not pattern
redaction — a scrubber would have to anticipate every secret shape, and the
shapes it misses are the ones that matter.

**Kept:** ``exception.type``, ``exception.escaped``, span status *code*,
trace and span identifiers, span name, and every span attribute KnowHub set
under its own safe-telemetry rules.

**Removed:** ``exception.message``, ``exception.stacktrace``, any other
attribute on an ``exception`` event, and the *description* of any ERROR
status. The description is treated as arbitrary error text regardless of how
it was produced: instrumentation builds it from the exception, application
code can put anything in it, and at the export boundary the two are
indistinguishable. ``OK`` and ``UNSET`` spans are never altered.

The seam is public SDK API only — :class:`SpanExporter` is documented as an
interface to implement, and :class:`ReadableSpan` and :class:`Event` have
public constructors. Nothing here monkey-patches, forks or subclasses
third-party instrumentation, and nothing mutates the application's
exceptions. Because it wraps the configured exporter, it applies identically
to the console and OTLP paths.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from opentelemetry.sdk.trace import Event, ReadableSpan
from opentelemetry.sdk.trace.export import SpanExporter, SpanExportResult
from opentelemetry.trace import Status, StatusCode

if TYPE_CHECKING:
    from collections.abc import Sequence

__all__ = [
    "EXCEPTION_EVENT_NAME",
    "SAFE_ERROR_DESCRIPTION",
    "SAFE_EXCEPTION_EVENT_ATTRIBUTES",
    "SafeSpanExporter",
    "sanitise_span",
]

#: The semantic-convention name for an automatically recorded exception.
EXCEPTION_EVENT_NAME = "exception"

#: The only attributes permitted to survive on an exception event. Allow-list:
#: anything not named here is removed, including attributes added by a future
#: instrumentation version.
SAFE_EXCEPTION_EVENT_ATTRIBUTES = frozenset({"exception.type", "exception.escaped"})

#: Replaces the description of any ERROR status. The status *code* is
#: preserved, so a failed span still reads as failed to every consumer.
SAFE_ERROR_DESCRIPTION = "error (exception detail withheld; see exception.type)"


def _sanitise_event(event: Event) -> Event:
    """Return ``event`` with only allow-listed attributes."""
    kept = {
        key: value
        for key, value in (event.attributes or {}).items()
        if key in SAFE_EXCEPTION_EVENT_ATTRIBUTES
    }
    return Event(name=event.name, attributes=kept, timestamp=event.timestamp)


def sanitise_span(span: ReadableSpan) -> ReadableSpan:
    """Return a span with arbitrary exception text removed.

    A span that recorded no exception is returned unchanged, so the common
    path allocates nothing.
    """
    events = tuple(span.events)
    status = span.status
    has_exception_event = any(event.name == EXCEPTION_EVENT_NAME for event in events)
    has_error_description = status.status_code is StatusCode.ERROR and bool(
        status.description
    )
    if not has_exception_event and not has_error_description:
        return span

    safe_events = [
        _sanitise_event(event) if event.name == EXCEPTION_EVENT_NAME else event
        for event in events
    ]

    # Any ERROR description is arbitrary error text — instrumentation builds it
    # from the exception, application code can put anything in it, and here the
    # two are indistinguishable. The code is what consumers act on and is kept.
    # OK and UNSET statuses pass through untouched.
    safe_status = (
        Status(status_code=StatusCode.ERROR, description=SAFE_ERROR_DESCRIPTION)
        if status.status_code is StatusCode.ERROR
        else status
    )

    return ReadableSpan(
        name=span.name,
        context=span.get_span_context(),
        parent=span.parent,
        resource=span.resource,
        attributes=span.attributes,
        events=safe_events,
        links=span.links,
        kind=span.kind,
        status=safe_status,
        start_time=span.start_time,
        end_time=span.end_time,
        instrumentation_scope=span.instrumentation_scope,
    )


class SafeSpanExporter(SpanExporter):
    """Wraps an exporter, removing arbitrary exception text before export.

    Applied to whatever exporter configuration selects, so console and OTLP
    behave identically.
    """

    def __init__(self, wrapped: SpanExporter) -> None:
        self._wrapped = wrapped

    def export(self, spans: Sequence[ReadableSpan]) -> SpanExportResult:
        return self._wrapped.export([sanitise_span(span) for span in spans])

    def shutdown(self) -> None:
        self._wrapped.shutdown()

    def force_flush(self, timeout_millis: int = 30_000) -> bool:
        return self._wrapped.force_flush(timeout_millis)
