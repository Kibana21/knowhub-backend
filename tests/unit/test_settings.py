"""Configuration loading, validation, precedence and the KnowHub namespace."""

from __future__ import annotations

import pytest
from pydantic import BaseModel, Field

from knowhub.config import (
    ConfigurationError,
    Environment,
    Settings,
    TelemetryExporter,
    enforce_mandatory_floors,
    get_settings,
    mandatory_floor,
)
from knowhub.config.settings import MANDATORY_FLOOR_KEY


def test_typed_settings_load_with_secure_defaults() -> None:
    settings = get_settings()
    assert settings.service_name == "knowhub-backend"
    assert settings.environment is Environment.LOCAL
    assert settings.database.host == "127.0.0.1"
    assert settings.database.port == 5432
    assert settings.redis.port == 6379


def test_invalid_type_is_rejected_at_load(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("KNOWHUB_DATABASE__PORT", "not-a-number")
    with pytest.raises(ConfigurationError) as excinfo:
        get_settings()
    assert "DATABASE.PORT" in str(excinfo.value)


def test_out_of_range_value_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("KNOWHUB_DATABASE__PORT", "70000")
    with pytest.raises(ConfigurationError):
        get_settings()


@pytest.mark.parametrize(
    "key",
    [
        "KNOWHUB_NONSENSE",
        "KNOWHUB_DATABSE__HOST",
        "KNOWHUB_DATABASE__NOPE",
        "KNOWHUB_A__B__C",
    ],
    ids=["flat-unknown", "misspelled-section", "unknown-leaf", "deep-unknown"],
)
def test_unknown_knowhub_key_is_rejected(
    monkeypatch: pytest.MonkeyPatch, key: str
) -> None:
    """A misspelled KnowHub setting must never be silently ignored (R2.1).

    ``extra="forbid"`` alone does not achieve this: pydantic-settings drops
    environment variables matching no known field before validation runs, so
    the namespace is checked explicitly.
    """
    monkeypatch.setenv(key, "value")
    with pytest.raises(ConfigurationError) as excinfo:
        get_settings()
    assert key.split("__")[0].upper() in str(excinfo.value).upper()


def test_feature_namespace_is_not_claimed_by_settings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``KNOWHUB_FEATURE_*`` belongs to the feature-flag mechanism."""
    monkeypatch.setenv("KNOWHUB_FEATURE_SOMETHING", "1")
    assert get_settings().service_name == "knowhub-backend"


def test_unrelated_environment_variables_are_tolerated(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Host, container, orchestrator and CI variables must not block startup."""
    for key, value in {
        "CI": "true",
        "GITHUB_ACTIONS": "true",
        "KUBERNETES_SERVICE_HOST": "10.0.0.1",
        "HOSTNAME": "container-abc",
        "AWS_REGION": "eu-west-1",
        "LANG": "en_US.UTF-8",
    }.items():
        monkeypatch.setenv(key, value)
    assert get_settings().environment is Environment.LOCAL


def test_missing_required_setting_fails_at_startup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("KNOWHUB_DATABASE__PASSWORD_REF", raising=False)
    with pytest.raises(ConfigurationError) as excinfo:
        get_settings()
    assert "DATABASE.PASSWORD_REF" in str(excinfo.value)


def test_failure_message_names_the_setting_and_leaks_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The rejected value must not be echoed: it may be the secret itself."""
    inline_secret = "sup3r-s3cret-inline-value"  # noqa: S105 - synthetic by design
    monkeypatch.setenv("KNOWHUB_DATABASE__PASSWORD_REF", inline_secret)
    with pytest.raises(ConfigurationError) as excinfo:
        get_settings()
    message = str(excinfo.value)
    assert "DATABASE.PASSWORD_REF" in message
    assert inline_secret not in message
    assert "PATH" not in message
    assert "HOME" not in message


def test_environment_value_overrides_platform_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert get_settings().database.host == "127.0.0.1"
    monkeypatch.setenv("KNOWHUB_DATABASE__HOST", "db.internal")
    from knowhub.config import reset_settings_cache

    reset_settings_cache()
    assert get_settings().database.host == "db.internal"


@pytest.mark.parametrize("exporter", ["otlp", "console", "none"])
def test_exporter_is_configuration_driven(
    monkeypatch: pytest.MonkeyPatch, exporter: str
) -> None:
    monkeypatch.setenv("KNOWHUB_TELEMETRY__EXPORTER", exporter)
    assert get_settings().telemetry.exporter is TelemetryExporter(exporter)


def test_no_production_setting_declares_a_mandatory_floor() -> None:
    """M00 defines no product policy. The mechanism exists; nothing uses it."""

    def floors(model: type[BaseModel], prefix: str = "") -> list[str]:
        found: list[str] = []
        for name, field in model.model_fields.items():
            annotation = field.annotation
            if isinstance(annotation, type) and issubclass(annotation, BaseModel):
                found += floors(annotation, f"{prefix}{name}.")
            extra = field.json_schema_extra
            if isinstance(extra, dict) and MANDATORY_FLOOR_KEY in extra:
                found.append(f"{prefix}{name}")
        return found

    assert floors(Settings) == []


def test_telemetry_can_be_disabled_in_any_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """M00-SPEC-003 R7 permits ``none``; M00 adds no environment-specific rule."""
    monkeypatch.setenv("KNOWHUB_ENVIRONMENT", "prod")
    monkeypatch.setenv("KNOWHUB_TELEMETRY__EXPORTER", "none")
    settings = get_settings()
    assert settings.environment is Environment.PROD
    assert settings.telemetry.exporter is TelemetryExporter.NONE


class _FloorExample(BaseModel):
    """Test-only model. Declaring a floor here creates no KnowHub policy."""

    require_verification: bool = Field(True, json_schema_extra=mandatory_floor(True))
    minimum_rounds: int = Field(4, json_schema_extra=mandatory_floor(4))


class _NestedFloorExample(BaseModel):
    control: _FloorExample


def test_mandatory_floor_accepts_the_floor_and_stricter_values() -> None:
    enforce_mandatory_floors(_FloorExample(require_verification=True, minimum_rounds=4))
    enforce_mandatory_floors(_FloorExample(require_verification=True, minimum_rounds=9))


@pytest.mark.parametrize(
    "weaker",
    [
        _FloorExample(require_verification=False, minimum_rounds=4),
        _FloorExample(require_verification=True, minimum_rounds=1),
    ],
    ids=["boolean-control-disabled", "numeric-minimum-lowered"],
)
def test_mandatory_floor_rejects_weakening(weaker: _FloorExample) -> None:
    with pytest.raises(ValueError, match="mandatory floor"):
        enforce_mandatory_floors(weaker)


def test_mandatory_floor_is_enforced_through_nested_sections() -> None:
    nested = _NestedFloorExample(
        control=_FloorExample(require_verification=False, minimum_rounds=4)
    )
    with pytest.raises(ValueError, match="mandatory floor"):
        enforce_mandatory_floors(nested)


def test_local_profile_is_selected_by_configuration_alone(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert get_settings().environment is Environment.LOCAL
    monkeypatch.setenv("KNOWHUB_ENVIRONMENT", "sit")
    from knowhub.config import reset_settings_cache

    reset_settings_cache()
    assert get_settings().environment is Environment.SIT


def test_database_password_is_resolved_only_at_point_of_use(
    test_db_password: str,
) -> None:
    from knowhub.config import EnvSecretResolver

    dsn = get_settings().database.dsn(EnvSecretResolver())
    assert test_db_password in dsn.get_secret_value()
    assert test_db_password not in repr(dsn)
    assert test_db_password not in str(dsn)
