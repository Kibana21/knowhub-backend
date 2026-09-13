"""The correlation identifier and its ambient context.

Every unit of work carries a correlation identifier (M00-SPEC-003 R8). It is
accepted from the caller when valid and generated otherwise, and it travels in
ambient context rather than being threaded through call signatures (R11) — a
threaded identifier is forgotten somewhere and the gap is invisible.

A caller-supplied value is untrusted input. It is validated before use (R9):
bounded length, then the canonical UUIDv4 representation. Anything that fails
is discarded and replaced with a freshly generated identifier, so
caller-controlled text never reaches a span attribute or a log record.

This module deliberately imports no web framework. The ASGI middleware that
reads the request header lives in ``knowhub.api``, so a future worker process
can reuse this context unchanged.
"""

from __future__ import annotations

import re
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar, Token

__all__ = [
    "CORRELATION_ID_HEADER",
    "CORRELATION_ID_MAX_LENGTH",
    "bind_correlation_id",
    "coerce_correlation_id",
    "current_correlation_id",
    "generate_correlation_id",
    "is_valid_correlation_id",
    "set_correlation_id",
]

#: The header a caller may use to supply an identifier, and the header the
#: response carries so a client-observed request can be found in telemetry.
CORRELATION_ID_HEADER = "X-Correlation-ID"

#: Canonical hyphenated UUID length. Checked before the pattern, so an
#: oversized value is rejected cheaply and never compiled against.
CORRELATION_ID_MAX_LENGTH = 36

_UUID_PATTERN = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$"
)

_correlation_id: ContextVar[str | None] = ContextVar(
    "knowhub_correlation_id", default=None
)


def generate_correlation_id() -> str:
    """Return a fresh identifier in the canonical representation."""
    return str(uuid.uuid4())


def is_valid_correlation_id(value: object) -> bool:
    """Return whether ``value`` is acceptable as a correlation identifier.

    Checks, in order: it is a string, it is within the length bound, and it
    matches canonical lowercase UUIDv4. The length bound is applied first so a
    hostile multi-megabyte header is rejected without pattern matching.
    Control characters cannot survive the pattern.
    """
    if not isinstance(value, str):
        return False
    if len(value) > CORRELATION_ID_MAX_LENGTH:
        return False
    return _UUID_PATTERN.match(value) is not None


def coerce_correlation_id(value: object) -> str:
    """Return ``value`` if it is a valid identifier, otherwise a fresh one.

    This is the only route by which caller input becomes a correlation
    identifier. An absent or non-conforming value is replaced, never repaired
    and never propagated.
    """
    if is_valid_correlation_id(value):
        # Narrowed by is_valid_correlation_id.
        return str(value)
    return generate_correlation_id()


def current_correlation_id() -> str | None:
    """Return the identifier bound to the current context, if any."""
    return _correlation_id.get()


def set_correlation_id(value: str) -> Token[str | None]:
    """Bind ``value`` to the current context and return the reset token."""
    return _correlation_id.set(value)


@contextmanager
def bind_correlation_id(value: object = None) -> Iterator[str]:
    """Bind a correlation identifier for the duration of the block.

    ``value`` is coerced, so passing caller input directly is safe. The
    binding is restored on exit, and it survives ``await`` boundaries within
    the block because it lives in a context variable.
    """
    correlation_id = coerce_correlation_id(value)
    token = _correlation_id.set(correlation_id)
    try:
        yield correlation_id
    finally:
        _correlation_id.reset(token)
