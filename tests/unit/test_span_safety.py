"""The span-safety boundary, tested directly rather than only end to end."""

from __future__ import annotations

from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import Link, SpanKind, Status, StatusCode

from knowhub.observability import SafeSpanExporter, sanitise_span
from knowhub.observability.span_safety import (
    EXCEPTION_EVENT_NAME,
    SAFE_ERROR_DESCRIPTION,
    SAFE_EXCEPTION_EVENT_ATTRIBUTES,
)


def _record_failing_span(message: str) -> InMemorySpanExporter:
    """Produce a span the way the framework does: exception escapes use_span."""
    raw = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(SafeSpanExporter(raw)))
    tracer = provider.get_tracer("test")
    try:
        with tracer.start_as_current_span("GET /thing"):
            raise RuntimeError(message)
    except RuntimeError:
        pass
    provider.shutdown()
    return raw


def test_exception_message_and_stacktrace_are_removed() -> None:
    secret = "pw-9f2a-in-the-message"  # noqa: S105 - synthetic by design
    exported = _record_failing_span(f"driver failure {secret}")
    spans = exported.get_finished_spans()
    assert spans

    for span in spans:
        for event in span.events:
            attributes = dict(event.attributes or {})
            assert "exception.message" not in attributes
            assert "exception.stacktrace" not in attributes
            assert set(attributes) <= SAFE_EXCEPTION_EVENT_ATTRIBUTES
        assert secret not in repr(span.events)
        assert secret not in repr(span.status.description)


def test_exception_type_and_error_status_survive() -> None:
    exported = _record_failing_span("anything")
    span = exported.get_finished_spans()[0]
    exception_events = [e for e in span.events if e.name == EXCEPTION_EVENT_NAME]
    assert exception_events, "the exception event itself must be preserved"
    assert dict(exception_events[0].attributes or {}).get("exception.type") == (
        "RuntimeError"
    )
    assert span.status.status_code is StatusCode.ERROR
    assert span.status.description == SAFE_ERROR_DESCRIPTION


def test_status_description_derived_from_the_exception_is_replaced() -> None:
    """``use_span`` builds the description as f-string of type and message."""
    secret = "description-canary-7c1d"  # noqa: S105 - synthetic by design
    exported = _record_failing_span(f"failed {secret}")
    span = exported.get_finished_spans()[0]
    assert span.status.description is not None
    assert secret not in span.status.description
    assert "RuntimeError:" not in span.status.description


def test_span_identity_and_attributes_are_preserved() -> None:
    exported = _record_failing_span("boom")
    span = exported.get_finished_spans()[0]
    assert span.name == "GET /thing"
    context = span.get_span_context()
    assert context is not None
    assert context.trace_id != 0
    assert context.span_id != 0
    assert span.start_time is not None
    assert span.end_time is not None
    assert span.instrumentation_scope is not None


def test_span_without_an_exception_is_passed_through_unchanged() -> None:
    raw = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(SafeSpanExporter(raw)))
    tracer = provider.get_tracer("test")
    with tracer.start_as_current_span("GET /ok") as span:
        span.set_attribute("knowhub.correlation_id", "abc")
    provider.shutdown()

    exported = raw.get_finished_spans()[0]
    assert exported.name == "GET /ok"
    assert dict(exported.attributes or {})["knowhub.correlation_id"] == "abc"
    assert exported.status.status_code is not StatusCode.ERROR


def test_sanitise_span_is_a_no_op_without_exception_events() -> None:
    """The common path must not rebuild the span."""
    raw = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(raw))
    tracer = provider.get_tracer("test")
    with tracer.start_as_current_span("GET /ok"):
        pass
    provider.shutdown()

    original = raw.get_finished_spans()[0]
    assert sanitise_span(original) is original


def test_exporter_delegates_lifecycle_to_the_wrapped_exporter() -> None:
    raw = InMemorySpanExporter()
    wrapper = SafeSpanExporter(raw)
    assert wrapper.force_flush() is True
    wrapper.shutdown()


def test_sanitising_preserves_all_unrelated_span_information(
    canary_secret: str,
) -> None:
    """Only the unsafe error payload may change; everything else survives."""
    raw = InMemorySpanExporter()
    resource = Resource.create({"service.name": "knowhub-test", "custom.key": "kept"})
    provider = TracerProvider(resource=resource)
    provider.add_span_processor(SimpleSpanProcessor(SafeSpanExporter(raw)))
    tracer = provider.get_tracer("knowhub.test.scope", "9.9.9")

    with tracer.start_as_current_span("linked-span") as linked:
        linked_context = linked.get_span_context()

    child_context = None
    with tracer.start_as_current_span("parent-span") as parent:
        parent_context = parent.get_span_context()
        try:
            with tracer.start_as_current_span(
                "GET /things/{id}",
                kind=SpanKind.SERVER,
                links=[Link(linked_context)],
                attributes={
                    "knowhub.correlation_id": "0f8f_correlation",
                    "http.request.method": "GET",
                    "http.route": "/things/{id}",
                },
            ) as child:
                child.add_event("knowhub.stage", {"stage": "compose", "count": 3})
                child_context = child.get_span_context()
                raise RuntimeError(f"driver failure {canary_secret}")
        except RuntimeError:
            pass
    provider.shutdown()

    exported = next(
        span for span in raw.get_finished_spans() if span.name == "GET /things/{id}"
    )

    # identity
    assert child_context is not None
    exported_context = exported.get_span_context()
    assert exported_context is not None
    assert exported_context.trace_id == child_context.trace_id
    assert exported_context.span_id == child_context.span_id
    assert exported.parent is not None
    assert exported.parent.span_id == parent_context.span_id

    # shape
    assert exported.name == "GET /things/{id}"
    assert exported.kind is SpanKind.SERVER
    assert exported.start_time is not None
    assert exported.end_time is not None
    assert exported.end_time >= exported.start_time

    # provenance
    assert exported.resource.attributes["service.name"] == "knowhub-test"
    assert exported.resource.attributes["custom.key"] == "kept"
    assert exported.instrumentation_scope is not None
    assert exported.instrumentation_scope.name == "knowhub.test.scope"
    assert exported.instrumentation_scope.version == "9.9.9"

    # links
    assert len(exported.links) == 1
    assert exported.links[0].context.span_id == linked_context.span_id

    # ordinary attributes
    attributes = dict(exported.attributes or {})
    assert attributes["knowhub.correlation_id"] == "0f8f_correlation"
    assert attributes["http.request.method"] == "GET"
    assert attributes["http.route"] == "/things/{id}"

    # a safe, non-exception event survives intact
    stage_events = [e for e in exported.events if e.name == "knowhub.stage"]
    assert len(stage_events) == 1
    assert dict(stage_events[0].attributes or {}) == {"stage": "compose", "count": 3}
    assert stage_events[0].timestamp is not None

    # status code kept; only the payload changed
    assert exported.status.status_code is StatusCode.ERROR
    assert canary_secret not in repr(exported.events)
    assert canary_secret not in str(exported.status.description)


def test_error_status_description_is_removed_without_any_exception_event(
    canary_dsn: str,
) -> None:
    """An ERROR description is unsafe text whoever wrote it."""
    raw = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(SafeSpanExporter(raw)))
    tracer = provider.get_tracer("test")

    with tracer.start_as_current_span("GET /thing") as span:
        span.set_status(Status(StatusCode.ERROR, f"could not connect to {canary_dsn}"))
    provider.shutdown()

    exported = raw.get_finished_spans()[0]
    assert not [e for e in exported.events if e.name == EXCEPTION_EVENT_NAME]
    assert exported.status.status_code is StatusCode.ERROR
    assert exported.status.description == SAFE_ERROR_DESCRIPTION
    assert canary_dsn not in str(exported.status.description)
    assert "CANARY-dsn-pw-9f2a" not in repr(exported.status)


def test_error_status_with_a_plain_secret_description_is_also_removed(
    canary_secret: str,
) -> None:
    raw = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(SafeSpanExporter(raw)))
    tracer = provider.get_tracer("test")

    with tracer.start_as_current_span("job") as span:
        span.set_status(Status(StatusCode.ERROR, f"token was {canary_secret}"))
    provider.shutdown()

    exported = raw.get_finished_spans()[0]
    assert canary_secret not in str(exported.status.description)
    assert exported.status.status_code is StatusCode.ERROR


def test_ok_and_unset_span_semantics_are_untouched() -> None:
    """Only ERROR spans are touched; OK and UNSET pass through identically.

    OpenTelemetry itself drops a description on a non-ERROR status, so the
    assertion is that the status object survives unchanged, not that it
    carries text.
    """
    raw = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(SafeSpanExporter(raw)))
    tracer = provider.get_tracer("test")

    with tracer.start_as_current_span("ok-span") as ok_span:
        ok_span.set_status(Status(StatusCode.OK))
        ok_span.set_attribute("knowhub.stage", "done")
    with tracer.start_as_current_span("unset-span"):
        pass
    provider.shutdown()

    by_name = {span.name: span for span in raw.get_finished_spans()}
    ok_span_exported = by_name["ok-span"]
    assert ok_span_exported.status.status_code is StatusCode.OK
    assert ok_span_exported.status.description is None
    assert dict(ok_span_exported.attributes or {})["knowhub.stage"] == "done"
    assert by_name["unset-span"].status.status_code is StatusCode.UNSET
    assert by_name["unset-span"].status.description is None
