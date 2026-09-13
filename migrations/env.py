"""Alembic migration environment.

The database connection comes from the **canonical** KnowHub settings model
and the approved secret-reference resolver. This file defines no settings of
its own, parses no ``KNOWHUB_*`` variable and composes no second database URL:
a migration that reached a different database from the application would be a
silent, expensive class of bug.

``target_metadata`` is ``None`` at M00. There is no domain model yet, so
autogenerate is correctly unusable; it becomes available when M1 introduces
the canonical data model. The revision chain is intentionally empty — M00
carries no business schema migration (M00-SPEC-004 R9, R10).
"""

from __future__ import annotations

from logging.config import fileConfig

from alembic import context
from sqlalchemy import create_engine, pool

from knowhub.config import EnvSecretResolver, get_settings

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

#: No domain model exists at M00, so there is nothing to autogenerate against.
target_metadata = None


def _database_url() -> str:
    """Resolve the database URL at the point of use.

    The URL carries a credential, so it is never stored, cached, logged or
    placed in a configuration file — it is built here and handed straight to
    the engine.
    """
    settings = get_settings()
    return settings.database.dsn(EnvSecretResolver()).get_secret_value()


def run_migrations_offline() -> None:
    """Emit SQL without a live connection."""
    context.configure(
        url=_database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations against a live connection."""
    connectable = create_engine(_database_url(), poolclass=pool.NullPool)
    try:
        with connectable.connect() as connection:
            context.configure(connection=connection, target_metadata=target_metadata)
            with context.begin_transaction():
                context.run_migrations()
    finally:
        connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
