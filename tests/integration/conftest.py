"""Integration-layer fixtures.

These tests run against the **real configured PostgreSQL**, whichever instance
that is: KnowHub consumes a configured endpoint and cannot tell how the
service was provisioned. Nothing here mocks Alembic or PostgreSQL behaviour.

Unlike the unit layer, this layer deliberately inherits the ambient
environment — that is where the real connection details live.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import psycopg
import pytest
from alembic.config import Config
from psycopg import sql

from knowhub.config import ConfigurationError, EnvSecretResolver, get_settings

if TYPE_CHECKING:
    from collections.abc import Callable

    from knowhub.config import Settings

#: Alembic's own version-tracking table. It is bookkeeping, not a KnowHub
#: business table, and its presence never means a business migration ran.
ALEMBIC_BOOKKEEPING_TABLE = "alembic_version"

REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="session")
def configured_postgres() -> Settings:
    """Settings for a reachable PostgreSQL, or skip the layer with a reason.

    Skipping is how an absent dependency is reported — never by passing.
    Messages name the host, port and database, which are configuration, and
    never the credential.
    """
    try:
        settings = get_settings()
    except ConfigurationError as error:
        pytest.skip(f"KnowHub configuration is incomplete: {error}")

    database = settings.database
    try:
        password = EnvSecretResolver().resolve(database.password_ref).get_secret_value()
        with psycopg.connect(
            host=database.host,
            port=database.port,
            dbname=database.name,
            user=database.user,
            password=password,
            connect_timeout=5,
        ):
            pass
    except Exception as error:
        pytest.skip(
            f"configured PostgreSQL at {database.host}:{database.port}/"
            f"{database.name} is not available ({type(error).__name__})"
        )
    return settings


@pytest.fixture
def alembic_config(configured_postgres: Settings) -> Config:
    """Alembic configuration resolved from the repository root.

    ``alembic.ini`` sets ``script_location`` relative to its own directory, so
    this works regardless of the working directory pytest was started from.
    ``migrations/env.py`` obtains the URL from the canonical settings model —
    this fixture supplies no connection details of its own.
    """
    assert configured_postgres is not None
    return Config(str(REPO_ROOT / "alembic.ini"))


def _query_names(settings: Settings, statement: str) -> set[str]:
    password = (
        EnvSecretResolver().resolve(settings.database.password_ref).get_secret_value()
    )
    with (
        psycopg.connect(
            host=settings.database.host,
            port=settings.database.port,
            dbname=settings.database.name,
            user=settings.database.user,
            password=password,
            connect_timeout=5,
        ) as connection,
        connection.cursor() as cursor,
    ):
        cursor.execute(sql.SQL(statement))  # pyright: ignore[reportArgumentType]
        return {row[0] for row in cursor.fetchall()}


@pytest.fixture
def database_tables(configured_postgres: Settings) -> Callable[[], set[str]]:
    """Return a callable giving the current user tables in the database."""

    def _tables() -> set[str]:
        return _query_names(
            configured_postgres,
            "SELECT tablename FROM pg_tables "
            "WHERE schemaname NOT IN ('pg_catalog', 'information_schema')",
        )

    return _tables


@pytest.fixture
def installed_extensions(configured_postgres: Settings) -> Callable[[], set[str]]:
    """Return a callable giving the extensions created in the database."""

    def _extensions() -> set[str]:
        return _query_names(configured_postgres, "SELECT extname FROM pg_extension")

    return _extensions


@pytest.fixture(scope="session")
def repo_root() -> Path:
    """The repository root, for asserting on files rather than the database."""
    return REPO_ROOT
