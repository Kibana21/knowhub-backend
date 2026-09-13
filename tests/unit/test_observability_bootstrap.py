"""Telemetry bootstrap: vendor-neutral, configuration-driven, fails loudly."""

from __future__ import annotations

import importlib.metadata
import subprocess
import sys

import pytest

from knowhub.config import get_settings
from knowhub.observability import TelemetryInitialisationError
from knowhub.observability import bootstrap as bootstrap_module
from knowhub.observability.bootstrap import _build_metric_reader, _build_span_exporter


def test_exporter_none_produces_no_exporter(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("KNOWHUB_TELEMETRY__EXPORTER", "none")
    settings = get_settings()
    assert _build_span_exporter(settings) is None
    assert _build_metric_reader(settings) is None


def test_console_exporter_is_selected_by_configuration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Selected by configuration, and wrapped in the span-safety boundary."""
    from opentelemetry.sdk.trace.export import ConsoleSpanExporter

    from knowhub.observability import SafeSpanExporter

    monkeypatch.setenv("KNOWHUB_TELEMETRY__EXPORTER", "console")
    settings = get_settings()
    exporter = _build_span_exporter(settings)
    assert isinstance(exporter, SafeSpanExporter)
    assert isinstance(exporter._wrapped, ConsoleSpanExporter)
    assert _build_metric_reader(settings) is not None


def test_otlp_exporter_is_selected_by_configuration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Selected by configuration, and wrapped in the span-safety boundary."""
    from knowhub.observability import SafeSpanExporter

    monkeypatch.setenv("KNOWHUB_TELEMETRY__EXPORTER", "otlp")
    settings = get_settings()
    exporter = _build_span_exporter(settings)
    assert isinstance(exporter, SafeSpanExporter)
    assert type(exporter._wrapped).__name__ == "OTLPSpanExporter"
    assert _build_metric_reader(settings) is not None


def test_initialisation_failure_is_visible_not_silent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A process must never serve believing it is traced when it is not."""

    def exploding_provider(**_kwargs: object) -> object:
        message = "provider exploded"
        raise RuntimeError(message)

    monkeypatch.setenv("KNOWHUB_TELEMETRY__EXPORTER", "console")
    monkeypatch.setattr(bootstrap_module, "TracerProvider", exploding_provider)
    with pytest.raises(TelemetryInitialisationError, match="could not be initialised"):
        bootstrap_module.configure_observability(get_settings())


def test_no_vendor_telemetry_sdk_is_installed() -> None:
    """Application Insights is an export destination, not an instrumentation API."""
    installed = {
        distribution.metadata["Name"].lower()
        for distribution in importlib.metadata.distributions()
        if distribution.metadata["Name"]
    }
    vendor = sorted(
        name
        for name in installed
        if "azure" in name or "applicationinsights" in name or "opencensus" in name
    )
    assert vendor == []


def test_observability_package_imports_no_web_framework() -> None:
    """Keeps the correlation context reusable by a future worker process."""
    program = (
        "import sys, knowhub.observability;"
        "print([m for m in sys.modules if m.split('.')[0] in {'fastapi','starlette'}])"
    )
    completed = subprocess.run(  # noqa: S603 - fixed argv, no shell, test-only
        [sys.executable, "-c", program],
        capture_output=True,
        text=True,
        check=True,
    )
    assert completed.stdout.strip() == "[]"
