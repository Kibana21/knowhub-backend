"""Unit-test fixtures.

Unit tests require no external service and must not reach one.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

import pytest

from knowhub.config import reset_settings_cache

#: Synthetic, never a plausible credential.
TEST_DB_PASSWORD = "test-only-not-a-real-secret"  # noqa: S105 - synthetic by design


@pytest.fixture(autouse=True)
def isolate_from_dotenv(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Run each unit test from a scratch directory.

    The settings model reads a local ``.env`` when one is present, resolved
    relative to the working directory. A developer's own ``.env`` would
    otherwise change results between machines, so unit tests run somewhere
    that has none. This is what makes assertions about *default* values mean
    anything.
    """
    monkeypatch.chdir(tmp_path)


@pytest.fixture(autouse=True)
def clean_knowhub_env(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Give every unit test the same known configuration starting point.

    Clears the whole KnowHub namespace first, so a variable exported in the
    developer's shell cannot change a result, then supplies the minimum
    required configuration. Unit tests never reach an external service, so
    these values need not resolve to anything real.
    """
    for key in [k for k in os.environ if k.upper().startswith("KNOWHUB_")]:
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("KNOWHUB_DATABASE__PASSWORD_REF", "env:KH_TEST_DB_PASSWORD")
    monkeypatch.setenv("KH_TEST_DB_PASSWORD", TEST_DB_PASSWORD)
    monkeypatch.setenv("KNOWHUB_TELEMETRY__EXPORTER", "none")
    reset_settings_cache()
    yield
    reset_settings_cache()


@pytest.fixture
def test_db_password() -> str:
    """The synthetic password the unit settings fixture resolves to."""
    return TEST_DB_PASSWORD
