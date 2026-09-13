"""Shared test fixtures.

Two rules shape everything here: tests are deterministic and
order-independent, and they share no mutable global state. The settings cache
and the OpenTelemetry provider are both process-global, so both are reset
around every test that touches them.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from knowhub.config import reset_settings_cache
from knowhub.observability import SafeSpanExporter

#: Distinctive string used by leakage tests. If this ever appears in output a
#: test is meant to inspect, something is leaking.
CANARY_SECRET = "CANARY-b8f1c0d2-DO-NOT-EMIT"  # noqa: S105 - synthetic by design

#: A second canary shaped like a real database URL. Driver exceptions embed
#: connection strings, so the safety rule is proven against that shape too.
CANARY_DSN = "postgresql://knowhub:CANARY-dsn-pw-9f2a@db.internal:5432/knowhub"


@pytest.fixture(autouse=True)
def reset_configuration_cache() -> Iterator[None]:
    """Settings are cached process-wide; never let one test's load leak.

    Environment isolation itself belongs to the unit layer: integration tests
    must see the *real* configured database, so they deliberately inherit the
    ambient environment.
    """
    reset_settings_cache()
    yield
    reset_settings_cache()


@pytest.fixture
def canary_secret() -> str:
    """A distinctive synthetic secret for leakage assertions."""
    return CANARY_SECRET


@pytest.fixture
def canary_dsn() -> str:
    """A synthetic connection-string-shaped secret for leakage assertions."""
    return CANARY_DSN


@pytest.fixture(scope="session", autouse=True)
def _tracer_provider() -> InMemorySpanExporter:
    """Install one in-memory tracer provider for the whole session.

    OpenTelemetry refuses to replace a tracer provider once set, so this must
    win the race against the first ``configure_observability`` call. Session
    scope plus ``autouse`` guarantees it runs before any test body, which is
    what makes span assertions independent of test order.
    """
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    # Wrapped exactly as production wraps its configured exporter, so what the
    # tests inspect is what a real collector would receive. Asserting against
    # the raw exporter would test a path production does not use.
    provider.add_span_processor(SimpleSpanProcessor(SafeSpanExporter(exporter)))
    trace.set_tracer_provider(provider)
    return exporter


@pytest.fixture
def span_exporter(_tracer_provider: InMemorySpanExporter) -> InMemorySpanExporter:
    """The session tracer provider's exporter, emptied for this test."""
    _tracer_provider.clear()
    return _tracer_provider
