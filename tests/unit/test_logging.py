"""Structured logging: correlation on every record, content rendered safely."""

from __future__ import annotations

import io
import json
import logging
from collections.abc import Iterator

import pytest

from knowhub.observability import CorrelationFilter, JsonFormatter, bind_correlation_id


@pytest.fixture
def captured_records() -> Iterator[tuple[io.StringIO, logging.Logger]]:
    """Attach the real filter and formatter to an isolated handler."""
    buffer = io.StringIO()
    handler = logging.StreamHandler(buffer)
    handler.setFormatter(JsonFormatter())
    handler.addFilter(CorrelationFilter())
    root = logging.getLogger()
    original_handlers = root.handlers[:]
    original_level = root.level
    root.handlers = [handler]
    root.setLevel(logging.INFO)
    try:
        yield buffer, root
    finally:
        root.handlers = original_handlers
        root.setLevel(original_level)


def _records(buffer: io.StringIO) -> list[dict[str, object]]:
    return [json.loads(line) for line in buffer.getvalue().splitlines() if line.strip()]


def test_every_record_carries_the_correlation_identifier(
    captured_records: tuple[io.StringIO, logging.Logger],
) -> None:
    buffer, _ = captured_records
    with bind_correlation_id() as bound:
        logging.getLogger("knowhub.test").info("hello")
    record = _records(buffer)[0]
    assert record["correlation_id"] == bound
    assert "trace_id" in record
    assert "span_id" in record


def test_third_party_loggers_are_enriched_identically(
    captured_records: tuple[io.StringIO, logging.Logger],
) -> None:
    """A filter on the handler covers libraries that know nothing of KnowHub."""
    buffer, _ = captured_records
    with bind_correlation_id() as bound:
        logging.getLogger("sqlalchemy.engine").warning("library message")
        logging.getLogger("some_vendor_sdk.client").error("vendor message")
    records = _records(buffer)
    assert len(records) == 2
    assert {r["correlation_id"] for r in records} == {bound}
    assert {r["logger"] for r in records} == {
        "sqlalchemy.engine",
        "some_vendor_sdk.client",
    }


def test_records_are_structured_json_with_fixed_fields(
    captured_records: tuple[io.StringIO, logging.Logger],
) -> None:
    buffer, _ = captured_records
    with bind_correlation_id():
        logging.getLogger("knowhub.test").info("msg", extra={"stage": "verify"})
    record = _records(buffer)[0]
    for field in ("timestamp", "level", "logger", "message", "correlation_id"):
        assert field in record
    assert record["stage"] == "verify"


def test_exception_renders_type_only(
    captured_records: tuple[io.StringIO, logging.Logger],
) -> None:
    """Exception text is deny-by-default: only the type is safe to emit.

    A message, args or traceback can all carry the values of the failing
    call. Regression for the T04 leakage defect (M00-SPEC-003 R12).
    """
    buffer, _ = captured_records
    secret = "s3cr3t-in-the-message"  # noqa: S105 - synthetic by design
    with bind_correlation_id():
        try:
            raise ValueError(f"connection failed password={secret}")
        except ValueError:
            logging.getLogger("knowhub.test").exception("failed")
    record = _records(buffer)[0]
    assert record["error"] == {"type": "ValueError"}
    output = buffer.getvalue()
    assert secret not in output
    assert "Traceback" not in output
    assert isinstance(record["error"], dict)
    assert "message" not in record["error"]


def test_exception_args_and_attributes_never_reach_output(
    captured_records: tuple[io.StringIO, logging.Logger],
) -> None:
    """Neither ``args`` nor custom attributes are serialised."""

    class _DriverError(RuntimeError):
        def __init__(self, dsn: str) -> None:
            super().__init__("driver failure", dsn)
            self.dsn = dsn

    buffer, _ = captured_records
    dsn = "postgresql://knowhub:pw-in-args@db.internal:5432/knowhub"
    with bind_correlation_id():
        try:
            raise _DriverError(dsn)
        except _DriverError:
            logging.getLogger("knowhub.test").exception("driver failed")
    output = buffer.getvalue()
    assert "pw-in-args" not in output
    assert "postgresql://" not in output
    assert _records(buffer)[0]["error"] == {"type": "_DriverError"}


def test_unserialisable_object_is_rendered_by_type_only(
    captured_records: tuple[io.StringIO, logging.Logger], test_db_password: str
) -> None:
    """An object that reaches a log field must not spill its contents."""
    from knowhub.config import get_settings

    buffer, _ = captured_records
    settings = get_settings()
    with bind_correlation_id():
        logging.getLogger("knowhub.test").info("cfg", extra={"settings": settings})
    output = buffer.getvalue()
    assert "<Settings>" in output
    assert test_db_password not in output


def test_records_outside_a_correlation_scope_still_render(
    captured_records: tuple[io.StringIO, logging.Logger],
) -> None:
    buffer, _ = captured_records
    logging.getLogger("knowhub.test").info("no scope")
    record = _records(buffer)[0]
    assert record["correlation_id"] is None
