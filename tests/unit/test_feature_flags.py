"""The feature-flag mechanism exists and defines no product flag at M00."""

from __future__ import annotations

import pytest

from knowhub.config import FeatureFlags, UnknownFeatureFlagError


def test_no_product_flag_is_defined() -> None:
    assert FeatureFlags().defined_flags() == frozenset()


def test_unknown_flag_raises_rather_than_reading_as_off() -> None:
    """A typo must not quietly mean 'feature disabled'."""
    with pytest.raises(UnknownFeatureFlagError):
        FeatureFlags().is_enabled("nonexistent_feature")
