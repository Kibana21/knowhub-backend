"""Secret references: a reference is never a value, and never rendered."""

from __future__ import annotations

import pytest

from knowhub.config import (
    ConfigurationError,
    EnvSecretResolver,
    SecretResolutionError,
    get_settings,
)


@pytest.mark.parametrize(
    "inline",
    [
        "hunter2",
        "postgresql://user:password@host/db",
        "no-scheme-here",
        "",
        "   ",
    ],
    ids=["password", "connection-string", "bare-token", "empty", "whitespace"],
)
def test_plaintext_secret_is_rejected(
    monkeypatch: pytest.MonkeyPatch, inline: str
) -> None:
    """A raw value assigned to a reference fails at load, not at review."""
    monkeypatch.setenv("KNOWHUB_DATABASE__PASSWORD_REF", inline)
    with pytest.raises(ConfigurationError) as excinfo:
        get_settings()
    assert inline.strip() == "" or inline not in str(excinfo.value)


def test_unsupported_scheme_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("KNOWHUB_DATABASE__PASSWORD_REF", "vault:some/path")
    with pytest.raises(ConfigurationError, match="unsupported secret scheme"):
        get_settings()


def test_reference_renders_as_a_pointer_not_a_value() -> None:
    ref = get_settings().database.password_ref
    assert str(ref) == "env:KH_TEST_DB_PASSWORD"
    assert "SecretRef" in repr(ref)


def test_unresolvable_reference_names_the_reference_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("KNOWHUB_DATABASE__PASSWORD_REF", "env:DEFINITELY_NOT_SET")
    settings = get_settings()
    with pytest.raises(SecretResolutionError) as excinfo:
        settings.database.dsn(EnvSecretResolver())
    assert "env:DEFINITELY_NOT_SET" in str(excinfo.value)


def test_no_representation_of_settings_renders_a_resolved_secret(
    test_db_password: str,
) -> None:
    settings = get_settings()
    renderings = [
        repr(settings),
        str(settings),
        settings.model_dump_json(),
        f"{settings}",
        repr(settings.database),
        settings.database.model_dump_json(),
    ]
    for rendering in renderings:
        assert test_db_password not in rendering
