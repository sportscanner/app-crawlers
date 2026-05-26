import os
import sys
import types

from sportscanner.observability.phoenix import configure_phoenix_tracing
from sportscanner.variables import settings


def test_configure_phoenix_tracing_disabled_without_required_env(monkeypatch):
    configure_phoenix_tracing.cache_clear()
    monkeypatch.setattr(settings, "PHOENIX_API_KEY", None)
    monkeypatch.setattr(settings, "PHOENIX_COLLECTOR_ENDPOINT", None)
    monkeypatch.delenv("PHOENIX_API_KEY", raising=False)
    monkeypatch.delenv("PHOENIX_COLLECTOR_ENDPOINT", raising=False)

    enabled = configure_phoenix_tracing()
    assert enabled is False
    assert "PHOENIX_API_KEY" not in os.environ
    assert "PHOENIX_COLLECTOR_ENDPOINT" not in os.environ


def test_configure_phoenix_tracing_registers_when_configured(monkeypatch):
    configure_phoenix_tracing.cache_clear()

    called: dict[str, object] = {}

    def fake_register(
        *,
        project_name,
        protocol,
        auto_instrument,
        verbose,
        **kwargs,
    ):
        called["endpoint"] = kwargs.get("endpoint")
        called["project_name"] = project_name
        called["protocol"] = protocol
        called["auto_instrument"] = auto_instrument
        called["verbose"] = verbose
        return object()

    fake_phoenix_module = types.ModuleType("phoenix")
    fake_otel_module = types.ModuleType("phoenix.otel")
    fake_otel_module.register = fake_register
    fake_phoenix_module.otel = fake_otel_module

    monkeypatch.setitem(sys.modules, "phoenix", fake_phoenix_module)
    monkeypatch.setitem(sys.modules, "phoenix.otel", fake_otel_module)

    monkeypatch.setattr(settings, "PHOENIX_API_KEY", "phoenix-key")
    monkeypatch.setattr(
        settings,
        "PHOENIX_COLLECTOR_ENDPOINT",
        "https://app.phoenix.arize.com/s/demo",
    )
    monkeypatch.setattr(settings, "PHOENIX_CLIENT_HEADERS", "api_key=phoenix-key")
    monkeypatch.setattr(settings, "PHOENIX_PROJECT_NAME", "sportscanner-tests")
    monkeypatch.setattr(settings, "PHOENIX_AUTO_INSTRUMENT", True)
    monkeypatch.delenv("PHOENIX_API_KEY", raising=False)
    monkeypatch.delenv("PHOENIX_COLLECTOR_ENDPOINT", raising=False)
    monkeypatch.delenv("PHOENIX_CLIENT_HEADERS", raising=False)

    enabled = configure_phoenix_tracing()

    assert enabled is True
    assert os.environ["PHOENIX_API_KEY"] == "phoenix-key"
    assert (
        os.environ["PHOENIX_COLLECTOR_ENDPOINT"]
        == "https://app.phoenix.arize.com/s/demo"
    )
    assert os.environ["PHOENIX_CLIENT_HEADERS"] == "api_key=phoenix-key"
    assert called == {
        "endpoint": None,
        "project_name": "sportscanner-tests",
        "protocol": "http/protobuf",
        "auto_instrument": True,
        "verbose": False,
    }
