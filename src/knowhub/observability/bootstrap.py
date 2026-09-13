"""OpenTelemetry initialisation.

Observability is initialised during process bootstrap, before the application
serves, and applies to every process mode the image can run
(M00-SPEC-003 R2). Application modules obtain instrumentation through this
package; nothing else configures a provider or an exporter (R3).

Instrumentation is **vendor-neutral OpenTelemetry** (R5). The export
destination is selected by configuration and no code knows where telemetry
goes (R7). No Azure-specific telemetry SDK is a dependency of this repository
(R6) — Application Insights is an export destination, not an instrumentation
API.

Initialisation failure is visible: the process must never continue silently
with telemetry disabled when telemetry is configured active (R4).
"""

from __future__ import annotations

import logging

from opentelemetry import metrics, trace
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import (
    ConsoleMetricExporter,
    MetricReader,
    PeriodicExportingMetricReader,
)
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import (
    BatchSpanProcessor,
    ConsoleSpanExporter,
    SpanExporter,
)

from knowhub.config import Settings, TelemetryExporter
from knowhub.observability.logging import configure_logging
from knowhub.observability.span_safety import SafeSpanExporter

__all__ = [
    "TelemetryInitialisationError",
    "configure_observability",
    "get_tracer",
    "shutdown_observability",
]

_logger = logging.getLogger(__name__)

_tracer_provider: TracerProvider | None = None
_meter_provider: MeterProvider | None = None


class TelemetryInitialisationError(RuntimeError):
    """Telemetry was configured active but could not be initialised."""


def _build_span_exporter(settings: Settings) -> SpanExporter | None:
    """Select the exporter, wrapped in the span-safety boundary.

    Every configured destination is wrapped, so console and OTLP strip
    arbitrary exception text identically. See ``span_safety`` for why.
    """
    exporter = settings.telemetry.exporter
    if exporter is TelemetryExporter.NONE:
        return None
    if exporter is TelemetryExporter.CONSOLE:
        return SafeSpanExporter(ConsoleSpanExporter())
    try:
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
            OTLPSpanExporter,
        )
    except ImportError as error:  # pragma: no cover - dependency is declared
        msg = "OTLP span exporter is configured but unavailable"
        raise TelemetryInitialisationError(msg) from error
    return SafeSpanExporter(
        OTLPSpanExporter(endpoint=f"{settings.telemetry.otlp_endpoint}/v1/traces")
    )


def _build_metric_reader(settings: Settings) -> MetricReader | None:
    exporter = settings.telemetry.exporter
    if exporter is TelemetryExporter.NONE:
        return None
    if exporter is TelemetryExporter.CONSOLE:
        return PeriodicExportingMetricReader(ConsoleMetricExporter())
    try:
        from opentelemetry.exporter.otlp.proto.http.metric_exporter import (
            OTLPMetricExporter,
        )
    except ImportError as error:  # pragma: no cover - dependency is declared
        msg = "OTLP metric exporter is configured but unavailable"
        raise TelemetryInitialisationError(msg) from error
    return PeriodicExportingMetricReader(
        OTLPMetricExporter(endpoint=f"{settings.telemetry.otlp_endpoint}/v1/metrics")
    )


def configure_observability(settings: Settings, *, log_level: str = "INFO") -> None:
    """Initialise logging, tracing and metrics from configuration.

    No custom metric is defined at M00; the meter provider exists so later
    milestones attach meters without re-bootstrapping.

    Raises:
        TelemetryInitialisationError: if telemetry is configured active and
            cannot be initialised. Failure is never swallowed.
    """
    global _tracer_provider, _meter_provider

    configure_logging(log_level)

    resource = Resource.create(
        {
            "service.name": settings.service_name,
            "deployment.environment.name": settings.environment.value,
        }
    )

    try:
        span_exporter = _build_span_exporter(settings)
        tracer_provider = TracerProvider(resource=resource)
        if span_exporter is not None:
            tracer_provider.add_span_processor(BatchSpanProcessor(span_exporter))
        trace.set_tracer_provider(tracer_provider)
        _tracer_provider = tracer_provider

        metric_reader = _build_metric_reader(settings)
        readers = [metric_reader] if metric_reader is not None else []
        meter_provider = MeterProvider(resource=resource, metric_readers=readers)
        metrics.set_meter_provider(meter_provider)
        _meter_provider = meter_provider
    except TelemetryInitialisationError:
        raise
    except Exception as error:
        msg = (
            "telemetry is configured as "
            f"'{settings.telemetry.exporter.value}' but could not be initialised"
        )
        raise TelemetryInitialisationError(msg) from error

    _logger.info(
        "observability initialised",
        extra={"telemetry_exporter": settings.telemetry.exporter.value},
    )


def shutdown_observability() -> None:
    """Flush and shut down the providers. Safe to call when not initialised."""
    global _tracer_provider, _meter_provider
    if _tracer_provider is not None:
        _tracer_provider.shutdown()
        _tracer_provider = None
    if _meter_provider is not None:
        _meter_provider.shutdown()
        _meter_provider = None


def get_tracer(name: str) -> trace.Tracer:
    """Return a tracer. The only supported way to obtain instrumentation."""
    return trace.get_tracer(name)
