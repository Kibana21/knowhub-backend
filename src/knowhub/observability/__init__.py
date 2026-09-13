"""KnowHub observability — OpenTelemetry bootstrap and the correlation contract.

Instrumentation is obtained through this package. No other module configures a
provider or an exporter, so telemetry cannot silently diverge per package.

This package imports no web framework: the correlation context is reusable by
any process mode, and the ASGI middleware that reads the request header lives
in ``knowhub.api``.
"""

from knowhub.observability.bootstrap import (
    TelemetryInitialisationError,
    configure_observability,
    get_tracer,
    shutdown_observability,
)
from knowhub.observability.correlation import (
    CORRELATION_ID_HEADER,
    CORRELATION_ID_MAX_LENGTH,
    bind_correlation_id,
    coerce_correlation_id,
    current_correlation_id,
    generate_correlation_id,
    is_valid_correlation_id,
    set_correlation_id,
)
from knowhub.observability.logging import (
    CorrelationFilter,
    JsonFormatter,
    configure_logging,
)
from knowhub.observability.span_safety import (
    SAFE_EXCEPTION_EVENT_ATTRIBUTES,
    SafeSpanExporter,
    sanitise_span,
)

__all__ = [
    "CORRELATION_ID_HEADER",
    "CORRELATION_ID_MAX_LENGTH",
    "SAFE_EXCEPTION_EVENT_ATTRIBUTES",
    "CorrelationFilter",
    "JsonFormatter",
    "SafeSpanExporter",
    "TelemetryInitialisationError",
    "bind_correlation_id",
    "coerce_correlation_id",
    "configure_logging",
    "configure_observability",
    "current_correlation_id",
    "generate_correlation_id",
    "get_tracer",
    "is_valid_correlation_id",
    "sanitise_span",
    "set_correlation_id",
    "shutdown_observability",
]
