"""Feature flags.

The mechanism exists and is typed (M00-SPEC-002 R10). **No product feature
flag is defined at M00**, because M00 delivers no product capability to gate.
A flag is added by the milestone that ships the capability behind it, as a
typed field on :class:`FeatureFlags` with a safe default (R13).

Asking about a flag that does not exist is an error, not a silent ``False``:
a typo in a flag name must not read as "feature off".
"""

from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict

__all__ = ["FeatureFlags", "UnknownFeatureFlagError"]


class UnknownFeatureFlagError(KeyError):
    """A flag was queried that is not defined."""


class FeatureFlags(BaseSettings):
    """Typed feature flags for the KnowHub backend.

    Flags live in the ``KNOWHUB_FEATURE_`` namespace, separate from the
    settings namespace so a flag can never collide with a setting.
    """

    model_config = SettingsConfigDict(
        env_prefix="KNOWHUB_FEATURE_",
        extra="forbid",
        frozen=True,
    )

    # No flag is defined at M00. Adding one here is how a milestone gates a
    # capability; nothing else is required.

    def is_enabled(self, flag: str) -> bool:
        """Return whether ``flag`` is enabled.

        Raises:
            UnknownFeatureFlagError: if no such flag is defined.
        """
        if flag not in type(self).model_fields:
            msg = f"unknown feature flag '{flag}'"
            raise UnknownFeatureFlagError(msg)
        value = getattr(self, flag)
        return bool(value)

    def defined_flags(self) -> frozenset[str]:
        """Return the names of every defined flag. Empty at M00."""
        return frozenset(type(self).model_fields)
