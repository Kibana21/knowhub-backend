"""KnowHub configuration — the canonical settings mechanism.

Every component that needs a configured value imports it from here. Nothing
else parses ``KNOWHUB_*`` variables or defines its own defaults or precedence.

``policies.py`` is deliberately absent: M00 has no policy content, and an
empty module would be structure without code behind it. It arrives with the
milestone that has policy to express.
"""

from knowhub.config.feature_flags import FeatureFlags, UnknownFeatureFlagError
from knowhub.config.secrets import (
    EnvSecretResolver,
    SecretRef,
    SecretResolutionError,
    SecretResolver,
)
from knowhub.config.settings import (
    BlobSettings,
    ConfigurationError,
    DatabaseSettings,
    Environment,
    RedisSettings,
    Settings,
    TelemetryExporter,
    TelemetrySettings,
    enforce_mandatory_floors,
    get_settings,
    mandatory_floor,
    reset_settings_cache,
)

__all__ = [
    "BlobSettings",
    "ConfigurationError",
    "DatabaseSettings",
    "EnvSecretResolver",
    "Environment",
    "FeatureFlags",
    "RedisSettings",
    "SecretRef",
    "SecretResolutionError",
    "SecretResolver",
    "Settings",
    "TelemetryExporter",
    "TelemetrySettings",
    "UnknownFeatureFlagError",
    "enforce_mandatory_floors",
    "get_settings",
    "mandatory_floor",
    "reset_settings_cache",
]
