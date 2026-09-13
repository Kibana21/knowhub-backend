"""The minimal API: two probes, safe responses, correlation end to end."""

from __future__ import annotations

import uuid
from collections.abc import Iterator

import pytest
from fastapi import FastAPI
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from knowhub.api.health import ReadinessState
from knowhub.api.main import create_app
from knowhub.observability import CORRELATION_ID_HEADER, is_valid_correlation_id


@pytest.fixture
def app() -> FastAPI:
    return create_app()


@pytest.fixture
def client(app: FastAPI) -> Iterator[TestClient]:
    with TestClient(app, raise_server_exceptions=False) as test_client:
        yield test_client


def _api_routes(router: object) -> list[APIRoute]:
    """Walk included routers: FastAPI nests them behind ``original_router``."""
    found: list[APIRoute] = []
    for route in getattr(router, "routes", []):
        if isinstance(route, APIRoute):
            found.append(route)
        inner = getattr(route, "original_router", None)
        if inner is not None:
            found += _api_routes(inner)
    return found


def test_exactly_two_knowhub_routes_exist(app: FastAPI) -> None:
    routes = sorted(
        (r.path, sorted(r.methods or set())) for r in _api_routes(app.router)
    )
    assert routes == [("/healthz", ["GET"]), ("/readyz", ["GET"])]


@pytest.mark.parametrize("path", ["/openapi.json", "/docs", "/redoc"])
def test_schema_and_documentation_routes_are_disabled(
    client: TestClient, path: str
) -> None:
    """M00 publishes no contract, so it exposes no schema describing one."""
    assert client.get(path).status_code == 404


def test_healthz_is_coarse(client: TestClient) -> None:
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_readyz_is_ready_after_normal_startup(client: TestClient) -> None:
    response = client.get("/readyz")
    assert response.status_code == 200
    assert response.json()["status"] == "ready"


def test_readyz_reports_not_ready_safely(app: FastAPI, client: TestClient) -> None:
    state: ReadinessState = app.state.readiness
    state.observability_ready = False
    try:
        response = client.get("/readyz")
        assert response.status_code == 503
        body = response.json()
        assert body == {"status": "not_ready", "pending": ["observability"]}
    finally:
        state.observability_ready = True
    assert client.get("/readyz").status_code == 200


def test_readiness_reflects_settings_and_observability_only() -> None:
    """Readiness must not reach for a capability a later milestone owns."""
    assert sorted(ReadinessState().pending()) == ["observability", "settings"]
    assert (
        ReadinessState(settings_loaded=True, observability_ready=True).pending() == []
    )


@pytest.mark.parametrize("path", ["/healthz", "/readyz"])
def test_probes_disclose_no_configuration_or_secret(
    client: TestClient, path: str, test_db_password: str
) -> None:
    response = client.get(path)
    subject = response.text + repr(dict(response.headers))
    for leaked in (
        test_db_password,
        "127.0.0.1",
        "5432",
        "postgres",
        "password",
        "env:",
        "PATH",
    ):
        assert leaked not in subject


def test_valid_correlation_header_is_echoed_unchanged(client: TestClient) -> None:
    given = str(uuid.uuid4())
    response = client.get("/healthz", headers={CORRELATION_ID_HEADER: given})
    assert response.headers[CORRELATION_ID_HEADER] == given


def test_absent_correlation_header_gets_a_generated_identifier(
    client: TestClient,
) -> None:
    returned = client.get("/healthz").headers[CORRELATION_ID_HEADER]
    assert is_valid_correlation_id(returned)


@pytest.mark.parametrize(
    "rejected",
    [
        "not-a-uuid",
        "a" * 37,
        "z" * 4000,
        "<script>alert(1)</script>",
        "../../etc/passwd",
    ],
    ids=["malformed", "over-length", "very-long", "script", "traversal"],
)
def test_invalid_correlation_header_is_replaced(
    client: TestClient, rejected: str
) -> None:
    returned = client.get(
        "/healthz", headers={CORRELATION_ID_HEADER: rejected}
    ).headers[CORRELATION_ID_HEADER]
    assert is_valid_correlation_id(returned)
    assert returned != rejected
