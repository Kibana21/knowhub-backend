"""Verify that KnowHub's configured dependency endpoints are available.

Developer and CI tooling, **not** application code: it lives in ``scripts/``
and nothing under ``src/knowhub/`` imports it.

Every endpoint comes from the canonical settings model in ``knowhub.config``.
This script defines no parser, precedence, defaults or validation of its own —
a second interpretation of ``KNOWHUB_*`` would drift from the application's
and would then verify endpoints the application never uses
(M00-SPEC-004 R1, plan sequencing rule).

It reads configured endpoints only. It cannot tell, and must not care,
whether a service came from the managed Compose environment, a package
manager, a native installation or any other runtime (R1, R1.2). Availability
is an observed condition, never an assumption (R1.3); this is availability
verification, not an integration test (R24).

Usage:
    uv run python scripts/check_dependencies.py
"""

from __future__ import annotations

import socket
import sys
from dataclasses import dataclass
from typing import TYPE_CHECKING

import httpx
import psycopg

from knowhub.config import (
    ConfigurationError,
    EnvSecretResolver,
    SecretResolutionError,
    get_settings,
)

if TYPE_CHECKING:
    from knowhub.config import BlobSettings, DatabaseSettings, RedisSettings

#: The minimum PostgreSQL major this project supports. The managed Compose
#: environment pins the same major; see the implementation plan.
MINIMUM_POSTGRES_VERSION_NUM = 150000

_TIMEOUT_SECONDS = 5.0


@dataclass(frozen=True)
class CheckResult:
    service: str
    ok: bool
    detail: str


def _check_postgres(settings: DatabaseSettings) -> CheckResult:
    """Connect, assert the major version, and assert pgvector is available.

    The extension is **not** created: M00 needs pgvector to be available, and
    creating it belongs to the milestone that first uses it.

    Connects with discrete settings fields rather than a URL. The canonical
    DSN accessor produces a SQLAlchemy-dialect URL for Alembic, which libpq
    does not accept; composing a second URL here would be the duplication this
    script exists to avoid.
    """
    resolver = EnvSecretResolver()
    try:
        password = resolver.resolve(settings.password_ref).get_secret_value()
    except SecretResolutionError as error:
        return CheckResult("postgresql", False, str(error))

    try:
        with (
            psycopg.connect(
                host=settings.host,
                port=settings.port,
                dbname=settings.name,
                user=settings.user,
                password=password,
                connect_timeout=int(_TIMEOUT_SECONDS),
            ) as connection,
            connection.cursor() as cursor,
        ):
            cursor.execute("SELECT current_setting('server_version_num')::int")
            version_row = cursor.fetchone()
            cursor.execute(
                "SELECT count(*) FROM pg_available_extensions WHERE name = 'vector'"
            )
            vector_row = cursor.fetchone()
    except psycopg.Error as error:
        # str(error) on a connection failure carries host/port/database, which
        # are configuration, not credentials. The password is never in it.
        return CheckResult(
            "postgresql",
            False,
            f"cannot reach {settings.host}:{settings.port}/{settings.name}: "
            f"{type(error).__name__}",
        )

    version_num = int(version_row[0]) if version_row else 0
    if version_num < MINIMUM_POSTGRES_VERSION_NUM:
        return CheckResult(
            "postgresql",
            False,
            f"server_version_num {version_num} is below the supported minimum "
            f"{MINIMUM_POSTGRES_VERSION_NUM}",
        )

    if not vector_row or int(vector_row[0]) == 0:
        return CheckResult(
            "postgresql",
            False,
            "the 'vector' extension is not available on this server; install "
            "pgvector for this PostgreSQL major",
        )

    return CheckResult(
        "postgresql",
        True,
        f"server_version_num {version_num}, pgvector available (not created)",
    )


def _check_redis(settings: RedisSettings) -> CheckResult:
    """Send the Redis inline command ``PING`` and require ``+PONG``.

    A protocol-level exchange, not a socket probe: an open socket proves only
    that something is listening. This is the minimum exchange — no AUTH, no
    further commands, no client library, and nothing here is reusable as an
    application client. Redis application code arrives with the M2
    functionality that uses it (M00-SPEC-004 R5).
    """
    try:
        with socket.create_connection(
            (settings.host, settings.port), timeout=_TIMEOUT_SECONDS
        ) as connection:
            connection.sendall(b"PING\r\n")
            reply = connection.recv(64)
    except OSError as error:
        return CheckResult(
            "redis",
            False,
            f"cannot reach {settings.host}:{settings.port}: {type(error).__name__}",
        )

    if reply.startswith(b"+PONG"):
        return CheckResult("redis", True, "PING answered +PONG")
    if reply.startswith(b"-NOAUTH"):
        return CheckResult(
            "redis",
            False,
            "Redis reachable, credentials required (server answered -NOAUTH). "
            "This is not a healthy unauthenticated connection",
        )
    if reply.startswith(b"-"):
        error_code = reply.split(b" ", 1)[0].decode("ascii", "replace")
        return CheckResult("redis", False, f"Redis answered an error: {error_code}")
    return CheckResult("redis", False, "unexpected reply to PING")


def _check_blob(settings: BlobSettings) -> CheckResult:
    """Make a plain HTTP request to the configured blob endpoint.

    HTTP-level, not a socket probe. Any HTTP status proves the service is
    serving — an unauthenticated request legitimately returns 4xx, so the
    status code is not the signal. No Azure Storage SDK and no Blob client:
    those arrive with the M2 functionality that uses the Blob abstraction
    (M00-SPEC-004 R6).
    """
    try:
        response = httpx.get(settings.endpoint, timeout=_TIMEOUT_SECONDS)
    except httpx.HTTPError as error:
        return CheckResult(
            "blob",
            False,
            f"cannot reach {settings.endpoint}: {type(error).__name__}",
        )
    return CheckResult("blob", True, f"HTTP {response.status_code} from endpoint")


def main() -> int:
    try:
        settings = get_settings()
    except ConfigurationError as error:
        print(str(error), file=sys.stderr)
        return 2

    results = [
        _check_postgres(settings.database),
        _check_redis(settings.redis),
        _check_blob(settings.blob),
    ]

    for result in results:
        marker = "ok  " if result.ok else "FAIL"
        print(f"{marker} {result.service:<11} {result.detail}")

    failed = [result.service for result in results if not result.ok]
    if failed:
        print(f"\nunavailable: {', '.join(failed)}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
