"""Canonical KnowHub configuration.

This module is the single source of configuration semantics for the backend
(M00-SPEC-002 R1). Nothing else — no script, no migration environment, no
test helper — parses ``KNOWHUB_*`` variables, applies its own precedence or
invents its own defaults.

**Namespace.** KnowHub claims the ``KNOWHUB_`` prefix. An unrecognised key
inside that namespace fails validation, because a misspelled KnowHub setting
must not be silently ignored (R2.1). Everything outside the namespace is
ignored, never rejected: the process must not refuse to start because the host
carries unrelated operating-system, container, orchestrator or CI variables
(R2.2).

**Precedence** (R11, R14), widest to narrowest, each overriding the one above:

1. secure platform default — the field defaults in this module
2. environment configuration — process environment, then a local dotenv file
3. enterprise policy — *no content at M00*
4. application/source policy — *no content at M00*

Levels 3 and 4 have no content yet and therefore no source object; the
ordering is expressed here so they attach without redesign. A narrower scope
may make behaviour stricter, never weaker (R12).

**Domains.** §77.1 defines eight configuration domains. M00 populates only
**Platform** — service identity, environment name, the dependency endpoints
M00 uses, and telemetry (R8). Model profile, ingestion, connector, knowledge,
identity and security policy content belongs to the milestones that own those
capabilities (R9).
"""

from __future__ import annotations

import enum
import os
from functools import lru_cache
from typing import Annotated, Any

from pydantic import (
    BaseModel,
    Field,
    SecretStr,
    ValidationError,
    model_validator,
)
from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
)

from knowhub.config.secrets import SecretRef, SecretResolver

__all__ = [
    "MANDATORY_FLOOR_KEY",
    "BlobSettings",
    "ConfigurationError",
    "DatabaseSettings",
    "Environment",
    "RedisSettings",
    "Settings",
    "TelemetryExporter",
    "TelemetrySettings",
    "enforce_mandatory_floors",
    "get_settings",
    "mandatory_floor",
    "reset_settings_cache",
]

Port = Annotated[int, Field(ge=1, le=65535)]

#: The environment namespace KnowHub claims as its own (M00-SPEC-002 R2.1).
OWNED_ENV_PREFIX = "KNOWHUB_"

#: Feature flags live in their own sub-namespace, owned by ``FeatureFlags``.
FEATURE_ENV_PREFIX = "KNOWHUB_FEATURE_"


class ConfigurationError(RuntimeError):
    """Configuration could not be loaded.

    The message names each offending setting and what is wrong with it, and
    nothing else: no rejected value, no resolved credential, no connection
    string, no dump of the environment (M00-SPEC-002 R4).
    """

    @classmethod
    def from_validation_error(cls, error: ValidationError) -> ConfigurationError:
        lines: list[str] = []
        # include_input=False is the point of this method: pydantic's default
        # rendering embeds the rejected input, which for a secret field would
        # be the secret itself.
        for detail in error.errors(include_url=False, include_input=False):
            location = ".".join(str(part) for part in detail["loc"]) or "<root>"
            lines.append(f"  KNOWHUB_{location.upper()}: {detail['msg']}")
        body = "\n".join(lines)
        return cls(f"invalid KnowHub configuration:\n{body}")


class Environment(enum.StrEnum):
    """Deployment environments named by master blueprint §76."""

    LOCAL = "local"
    DEV = "dev"
    SIT = "sit"
    UAT = "uat"
    PROD = "prod"


class TelemetryExporter(enum.StrEnum):
    """Where telemetry is sent. Vendor-neutral (M00-SPEC-003 R5, R7)."""

    OTLP = "otlp"
    CONSOLE = "console"
    NONE = "none"


class _Section(BaseSettings):
    model_config = SettingsConfigDict(extra="forbid", frozen=True)


class DatabaseSettings(_Section):
    """PostgreSQL connection settings.

    Discrete fields rather than one connection string, so no setting is ever a
    credential-bearing URL. The password is a *reference*; the DSN is composed
    at the point of use and never stored.
    """

    host: str = "127.0.0.1"
    port: Port = 5432
    name: str = "knowhub"
    user: str = "knowhub"
    # Required: no safe default exists for a credential (R3, R13).
    password_ref: SecretRef

    def dsn(self, resolver: SecretResolver) -> SecretStr:
        """Compose the DSN, resolving the password at the point of use.

        Returned wrapped so it cannot be rendered by accident: the DSN carries
        a credential (M00-SPEC-002 R17).
        """
        password = resolver.resolve(self.password_ref).get_secret_value()
        return SecretStr(
            f"postgresql+psycopg://{self.user}:{password}"
            f"@{self.host}:{self.port}/{self.name}"
        )


class RedisSettings(_Section):
    """Redis endpoint.

    M00 configures the endpoint only. No Redis client exists in this
    repository until the M2 functionality that uses one (M00-SPEC-004 R5).
    """

    host: str = "127.0.0.1"
    port: Port = 6379
    password_ref: SecretRef | None = None


class BlobSettings(_Section):
    """Object-storage endpoint.

    As with Redis, M00 configures the endpoint and implements no client
    (M00-SPEC-004 R6).
    """

    endpoint: str = "http://127.0.0.1:10000/devstoreaccount1"


class TelemetrySettings(_Section):
    """OpenTelemetry destination, selected by configuration alone."""

    exporter: TelemetryExporter = TelemetryExporter.OTLP
    otlp_endpoint: str = "http://127.0.0.1:4318"


#: Marks a field as carrying a mandatory floor. A narrower configuration scope
#: may move the value in the stricter direction only (M00-SPEC-002 R12).
MANDATORY_FLOOR_KEY = "knowhub_mandatory_floor"


def mandatory_floor(floor: object) -> dict[str, object]:
    """Declare a mandatory floor for a field.

    Pass the result as ``json_schema_extra``. Strictness is ordered by the
    field's own comparison: a stricter value compares greater than or equal to
    the floor, so ``True`` is stricter than ``False`` and a larger minimum is
    stricter than a smaller one.

    No M00 setting uses this. It is the attachment point for the milestone
    that first has a mandatory control to express.
    """
    return {MANDATORY_FLOOR_KEY: floor}


def enforce_mandatory_floors(model: BaseModel) -> None:
    """Reject any value that weakens a declared mandatory floor.

    Recurses into nested sections, so a floor declared on a section field is
    enforced wherever that section is mounted.

    Raises:
        ValueError: if a field's value is weaker than its declared floor.
    """
    for name, field in type(model).model_fields.items():
        value = getattr(model, name)
        if isinstance(value, BaseModel):
            enforce_mandatory_floors(value)
            continue
        extra = field.json_schema_extra
        if not isinstance(extra, dict) or MANDATORY_FLOOR_KEY not in extra:
            continue
        floor = extra[MANDATORY_FLOOR_KEY]
        try:
            weaker = value < floor
        except TypeError:
            weaker = value != floor
        if weaker:
            msg = (
                f"{name} may not be weakened below its mandatory floor; "
                "a narrower scope may only make this control stricter"
            )
            raise ValueError(msg)


class Settings(BaseSettings):
    """Root KnowHub configuration — the Platform domain at M00."""

    model_config = SettingsConfigDict(
        env_prefix="KNOWHUB_",
        env_nested_delimiter="__",
        # Unknown keys *within* the KnowHub namespace are an error; keys
        # outside it are never collected in the first place (R2.1, R2.2).
        extra="forbid",
        frozen=True,
        env_file=".env",
        env_file_encoding="utf-8",
    )

    service_name: str = "knowhub-backend"
    environment: Environment = Environment.LOCAL

    database: DatabaseSettings
    redis: RedisSettings = Field(default_factory=RedisSettings)
    blob: BlobSettings = Field(default_factory=BlobSettings)
    telemetry: TelemetrySettings = Field(default_factory=TelemetrySettings)

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        """Order the precedence chain, narrowest first.

        pydantic-settings consults sources left to right and the first to
        supply a value wins, so this tuple reads narrowest → widest. Enterprise
        and application/source policy attach between ``init_settings`` and
        ``env_settings`` when a milestone gives them content; see the module
        docstring.
        """
        return (
            init_settings,  # explicit override, e.g. a test constructing Settings
            env_settings,  # environment configuration
            dotenv_settings,  # local dotenv, same scope as the environment
            file_secret_settings,  # secrets-directory convention
        )
        # Platform defaults are the field defaults above, and are widest.

    @classmethod
    def _recognised_env_keys(cls) -> frozenset[str]:
        """Every environment variable name this model can consume."""

        def walk(model: type[BaseModel], prefix: str) -> set[str]:
            names: set[str] = set()
            for field_name, field in model.model_fields.items():
                key = f"{prefix}{field_name.upper()}"
                annotation = field.annotation
                if isinstance(annotation, type) and issubclass(annotation, BaseModel):
                    # The section may be supplied whole (as JSON) or per leaf.
                    names.add(key)
                    names |= walk(annotation, f"{key}__")
                else:
                    names.add(key)
            return names

        return frozenset(walk(cls, OWNED_ENV_PREFIX))

    @model_validator(mode="before")
    @classmethod
    def _reject_unknown_namespace_keys(cls, data: Any) -> Any:  # noqa: ANN401
        """Fail on an unrecognised key inside KnowHub's own namespace.

        ``extra="forbid"`` alone is not sufficient: pydantic-settings discards
        environment variables that match no known field *before* validation
        sees them, so a misspelled top-level key would be silently ignored —
        exactly the failure R2.1 exists to prevent. Keys outside the namespace
        are never examined, so unrelated operating-system, container,
        orchestrator or CI variables cannot block startup (R2.2).
        """
        recognised = cls._recognised_env_keys()
        unknown = sorted(
            name
            for name in os.environ
            if name.upper().startswith(OWNED_ENV_PREFIX)
            and not name.upper().startswith(FEATURE_ENV_PREFIX)
            and name.upper() not in recognised
        )
        if unknown:
            listed = ", ".join(unknown)
            msg = (
                f"unrecognised setting(s) in the KnowHub namespace: {listed}. "
                "Check for a misspelled name."
            )
            raise ValueError(msg)
        if isinstance(data, dict):
            # Present every section so a missing leaf reports its own path
            # rather than collapsing to "database: Field required" (R4).
            for section, annotation in cls.model_fields.items():
                target = annotation.annotation
                if (
                    isinstance(target, type)
                    and issubclass(target, BaseModel)
                    and section not in data
                ):
                    data[section] = {}
        return data

    @model_validator(mode="after")
    def _enforce_mandatory_floors(self) -> Settings:
        """A narrower scope may tighten a control, never weaken it (R12).

        **No M00 setting declares a floor.** Like the feature-flag mechanism,
        this exists so the milestone that introduces a mandatory control
        attaches it here rather than inventing a second mechanism (R14). M00
        defines no product policy of its own.
        """
        enforce_mandatory_floors(self)
        return self


def _load() -> Settings:
    try:
        return Settings()  # pyright: ignore[reportCallIssue]
    except ValidationError as error:
        raise ConfigurationError.from_validation_error(error) from None


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the process-wide settings, loading and validating them once.

    Raises :class:`ConfigurationError` if configuration is missing or invalid,
    so a misconfigured process fails at startup rather than at first use (R3).
    """
    return _load()


def reset_settings_cache() -> None:
    """Clear the cached settings. For tests and for reloading in a REPL."""
    get_settings.cache_clear()
