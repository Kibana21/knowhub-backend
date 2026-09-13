"""The correlation identifier: validated before use, carried in context."""

from __future__ import annotations

import asyncio
import uuid

import pytest

from knowhub.observability import (
    CORRELATION_ID_HEADER,
    CORRELATION_ID_MAX_LENGTH,
    bind_correlation_id,
    coerce_correlation_id,
    current_correlation_id,
    generate_correlation_id,
    is_valid_correlation_id,
)


def test_header_name_and_length_bound_are_fixed() -> None:
    assert CORRELATION_ID_HEADER == "X-Correlation-ID"
    assert CORRELATION_ID_MAX_LENGTH == 36


def test_generated_identifier_is_valid() -> None:
    assert is_valid_correlation_id(generate_correlation_id())


def test_valid_caller_identifier_is_honoured() -> None:
    given = str(uuid.uuid4())
    assert coerce_correlation_id(given) == given


def test_absent_identifier_is_generated() -> None:
    generated = coerce_correlation_id(None)
    assert is_valid_correlation_id(generated)


@pytest.mark.parametrize(
    "rejected",
    [
        "a" * 37,
        "z" * 10_000,
        "not-a-uuid",
        "12345678-1234-1234-1234-123456789012",
        "00000000-0000-0000-0000-000000000000",
        "../../etc/passwd",
        "<script>alert(1)</script>",
        "'; DROP TABLE applications; --",
        "",
        42,
        object(),
    ],
    ids=[
        "over-length-by-one",
        "very-long",
        "not-a-uuid",
        "wrong-uuid-version",
        "nil-uuid",
        "path-traversal",
        "script-injection",
        "sql-injection",
        "empty",
        "not-a-string",
        "arbitrary-object",
    ],
)
def test_invalid_identifier_is_replaced_not_repaired(rejected: object) -> None:
    replacement = coerce_correlation_id(rejected)
    assert is_valid_correlation_id(replacement)
    assert replacement != rejected


@pytest.mark.parametrize(
    "control", ["\n", "\r", "\t", "\x00", "\x1b"], ids=list("nrtze")
)
def test_control_characters_never_survive(control: str) -> None:
    base = str(uuid.uuid4())
    replacement = coerce_correlation_id(base[:-1] + control)
    assert is_valid_correlation_id(replacement)
    assert control not in replacement


def test_uppercase_uuid_is_not_accepted() -> None:
    """One canonical representation only, so telemetry is comparable."""
    upper = str(uuid.uuid4()).upper()
    assert coerce_correlation_id(upper) != upper


def test_context_survives_await_boundaries() -> None:
    async def nested() -> str | None:
        await asyncio.sleep(0)
        return current_correlation_id()

    async def scenario() -> tuple[str, str | None]:
        with bind_correlation_id() as bound:
            return bound, await nested()

    bound, observed = asyncio.run(scenario())
    assert observed == bound


def test_context_is_restored_after_scope_exit() -> None:
    assert current_correlation_id() is None
    with bind_correlation_id() as bound:
        assert current_correlation_id() == bound
    assert current_correlation_id() is None


def test_nested_scopes_restore_the_outer_identifier() -> None:
    with bind_correlation_id() as outer:
        with bind_correlation_id() as inner:
            assert inner != outer
            assert current_correlation_id() == inner
        assert current_correlation_id() == outer


def test_binding_coerces_caller_input() -> None:
    with bind_correlation_id("not-a-uuid") as bound:
        assert is_valid_correlation_id(bound)
        assert bound != "not-a-uuid"
