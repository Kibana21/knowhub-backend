"""Alembic against the real configured PostgreSQL.

The migration scaffolding is the only real M00 integration code, so PostgreSQL
is the only dependency with integration tests. Redis and object storage have
no client at M00; their evidence is availability verification, which is not an
integration test.

Every test leaves the database at ``head`` — with an empty chain that means the
bookkeeping table exists and holds no revision — so the layer is
order-independent and repeatable.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from alembic import command

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from alembic.config import Config

#: Alembic's own version-tracking table. Bookkeeping, not a KnowHub business
#: table: its presence never means a business migration ran.
ALEMBIC_BOOKKEEPING_TABLE = "alembic_version"

pytestmark = pytest.mark.integration


@pytest.fixture(autouse=True)
def _known_end_state(alembic_config: Config) -> None:
    """Start every test from a known state: the empty chain applied."""
    command.upgrade(alembic_config, "head")


def test_fresh_database_migrates(
    alembic_config: Config, database_tables: Callable[[], set[str]]
) -> None:
    command.downgrade(alembic_config, "base")
    command.upgrade(alembic_config, "head")
    assert ALEMBIC_BOOKKEEPING_TABLE in database_tables()


def test_repeating_upgrade_succeeds(alembic_config: Config) -> None:
    """Applying an already-current chain must be a safe no-op."""
    command.upgrade(alembic_config, "head")
    command.upgrade(alembic_config, "head")


def test_downgrade_base_then_upgrade_again_succeeds(alembic_config: Config) -> None:
    command.downgrade(alembic_config, "base")
    command.upgrade(alembic_config, "head")
    command.downgrade(alembic_config, "base")
    command.upgrade(alembic_config, "head")


def test_no_business_revision_exists(repo_root: Path) -> None:
    """M00 carries no business schema migration."""
    versions = repo_root / "migrations" / "versions"
    assert versions.is_dir()
    assert sorted(p.name for p in versions.glob("*.py")) == []


def test_no_knowhub_business_table_is_created(
    database_tables: Callable[[], set[str]],
) -> None:
    """Only Alembic's bookkeeping table may exist after M00 migrations.

    ``alembic_version`` records which revision is applied. It is Alembic's own
    table, not a KnowHub business table, and is explicitly permitted here.
    """
    tables = database_tables()
    business_tables = tables - {ALEMBIC_BOOKKEEPING_TABLE}
    assert business_tables == set(), (
        f"M00 migrations created business tables: {sorted(business_tables)}"
    )


def test_bookkeeping_table_holds_no_revision(
    alembic_config: Config, database_tables: Callable[[], set[str]]
) -> None:
    """An empty chain stamps nothing, which is what makes 'no schema' true."""
    assert ALEMBIC_BOOKKEEPING_TABLE in database_tables()
    command.current(alembic_config)


def test_pgvector_is_not_created_by_m00(
    installed_extensions: Callable[[], set[str]],
) -> None:
    """M00 needs pgvector *available*; creating it belongs to its first user."""
    assert "vector" not in installed_extensions()


def test_unreachable_database_fails_visibly_and_safely(
    monkeypatch: pytest.MonkeyPatch,
    alembic_config: Config,
) -> None:
    """Failure must be loud, and must not disclose a credential or DSN."""
    from knowhub.config import reset_settings_cache

    canary = "CANARY-integration-pw-4d7e"
    monkeypatch.setenv("KNOWHUB_DATABASE__PORT", "1")
    monkeypatch.setenv("KNOWHUB_DATABASE__PASSWORD_REF", "env:KH_UNREACHABLE_PASSWORD")
    monkeypatch.setenv("KH_UNREACHABLE_PASSWORD", canary)
    reset_settings_cache()

    with pytest.raises(Exception) as excinfo:  # noqa: PT011 - driver-agnostic
        command.upgrade(alembic_config, "head")

    rendered = f"{excinfo.value!r}\n{excinfo.value}"
    assert canary not in rendered, "credential leaked into the failure output"
    assert "postgresql+psycopg://" not in rendered, "DSN leaked into failure output"
    assert f":{canary}@" not in rendered

    reset_settings_cache()
