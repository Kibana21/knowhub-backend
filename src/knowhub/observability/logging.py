"""Standard-library logging, configured once, emitting structured JSON.

Every log record carries the correlation identifier and the current trace and
span identifiers (M00-SPEC-003 R10). A ``logging.Filter`` on the handler does
the injection, so records from third-party libraries are enriched identically
to KnowHub's own — no call site has to remember.

Records are emitted as JSON objects with fixed field names, never as
interpolated strings: interpolation is how secrets reach logs unnoticed.

What must never be emitted is defined by the configuration package's content
rule — secrets, resolved credentials, tokens, connection strings and
authorization headers (M00-SPEC-003 R12). This module decides *how* a record
is rendered, not *what* callers are allowed to put in one.

**Exception text is deny-by-default.** An exception message is
caller-influenced and routinely carries the values of the failing call:
database drivers put connection details into ``OperationalError``, HTTP
clients put URLs with credentials into theirs. This formatter therefore never
serialises ``str(exception)``, its ``args``, its attributes or its traceback.
Only the exception *type* is emitted. Anything else a handler wants recorded
must be passed explicitly as a structured field, where the caller has taken
responsibility for its safety.

This is a deny-by-default rule, not pattern redaction: a scrubber would have
to anticipate every secret shape, and the ones it misses are exactly the ones
that matter.

All logging configuration lives here. Nothing else calls ``dictConfig`` or
attaches handlers.
"""

from __future__ import annotations

import json
import logging
import logging.config
from typing import Any, ClassVar

from opentelemetry import trace

from knowhub.observability.correlation import current_correlation_id

__all__ = ["CorrelationFilter", "JsonFormatter", "configure_logging"]

_INVALID_TRACE_ID = 0
_INVALID_SPAN_ID = 0


class CorrelationFilter(logging.Filter):
    """Attach the correlation identifier and trace context to every record."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.correlation_id = current_correlation_id()
        span_context = trace.get_current_span().get_span_context()
        if span_context.trace_id != _INVALID_TRACE_ID:
            record.trace_id = format(span_context.trace_id, "032x")
            record.span_id = format(span_context.span_id, "016x")
        else:
            record.trace_id = None
            record.span_id = None
        return True


class JsonFormatter(logging.Formatter):
    """Render a record as a single-line JSON object with fixed field names."""

    #: Attributes the logging module puts on every record. Anything outside
    #: this set was supplied by the caller via ``extra`` and is emitted
    #: alongside the standard fields.
    _RESERVED: ClassVar[frozenset[str]] = frozenset(
        {
            "args",
            "asctime",
            "created",
            "exc_info",
            "exc_text",
            "filename",
            "funcName",
            "levelname",
            "levelno",
            "lineno",
            "module",
            "msecs",
            "message",
            "msg",
            "name",
            "pathname",
            "process",
            "processName",
            "relativeCreated",
            "stack_info",
            "taskName",
            "thread",
            "threadName",
            "correlation_id",
            "trace_id",
            "span_id",
        }
    )

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "correlation_id": getattr(record, "correlation_id", None),
            "trace_id": getattr(record, "trace_id", None),
            "span_id": getattr(record, "span_id", None),
        }
        for key, value in record.__dict__.items():
            if key not in self._RESERVED and not key.startswith("_"):
                payload[key] = value
        # record.getMessage() interpolates record.args into the format string.
        # A handler that formats exception text into its message would defeat
        # the rule above, so handlers log a fixed message and pass structured
        # fields instead - see knowhub.api.main._handle_unexpected_error.
        if record.exc_info:
            # Type only. Never str(exc), exc.args, exc.__dict__ or the
            # traceback: all of them can carry the values of the failing call
            # (M00-SPEC-003 R12). The correlation, trace and span identifiers
            # above are what tie this record to the rest of the evidence.
            exc_type, _exc_value, _traceback = record.exc_info
            payload["error"] = {"type": exc_type.__name__ if exc_type else None}
        return json.dumps(payload, default=_fallback_repr, separators=(",", ":"))


def _fallback_repr(value: object) -> str:
    """Render a non-JSON-serialisable value by type, never by content.

    An object that reached a log field unexpectedly might be a settings object
    or a credential holder. Emitting its type is enough to debug with; its
    contents are not this module's to disclose.
    """
    return f"<{type(value).__name__}>"


def configure_logging(level: str = "INFO") -> None:
    """Configure root logging: JSON to stdout, correlation on every record."""
    logging.config.dictConfig(
        {
            "version": 1,
            "disable_existing_loggers": False,
            "filters": {"correlation": {"()": CorrelationFilter}},
            "formatters": {"json": {"()": JsonFormatter}},
            "handlers": {
                "stdout": {
                    "class": "logging.StreamHandler",
                    "stream": "ext://sys.stdout",
                    "formatter": "json",
                    "filters": ["correlation"],
                }
            },
            "root": {"handlers": ["stdout"], "level": level},
        }
    )
