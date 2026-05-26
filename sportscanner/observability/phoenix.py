"""OpenTelemetry OTLP/HTTP tracing bootstrap."""

from __future__ import annotations

import os
from functools import lru_cache
from typing import Optional

from sportscanner.logger import logging
from sportscanner.variables import settings


def _resolve(value: Optional[str], env_name: str) -> Optional[str]:
    candidate = value if value is not None else os.getenv(env_name)
    if candidate is None:
        return None
    cleaned = str(candidate).strip()
    return cleaned or None


@lru_cache(maxsize=1)
def configure_phoenix_tracing() -> bool:
    """
    Configure OTLP/HTTP trace export.

    Reads OTEL_EXPORTER_ENDPOINT and OTEL_PROJECT_ID from settings / env.
    Also honours the standard OTEL_EXPORTER_OTLP_TRACES_ENDPOINT and
    OTEL_EXPORTER_OTLP_HEADERS env vars as fallbacks (the SDK picks these
    up automatically when no explicit args are passed to OTLPSpanExporter).

    Returns True if the provider was registered, False otherwise.
    """
    endpoint = _resolve(settings.OTEL_EXPORTER_ENDPOINT, "OTEL_EXPORTER_ENDPOINT") or _resolve(
        None, "OTEL_EXPORTER_OTLP_TRACES_ENDPOINT"
    )
    project_id = _resolve(settings.OTEL_PROJECT_ID, "OTEL_PROJECT_ID") or "sportscanner-backend"

    if not endpoint:
        logging.info(
            "OTel tracing is disabled. Set OTEL_EXPORTER_ENDPOINT to enable it."
        )
        return False

    try:
        from opentelemetry import trace
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
    except ImportError as exc:
        logging.warning(f"OTel packages missing: {exc}")
        return False

    try:
        exporter = OTLPSpanExporter(
            endpoint=endpoint,
            headers={"x-project-id": project_id},
        )
        provider = TracerProvider()
        provider.add_span_processor(BatchSpanProcessor(exporter))
        trace.set_tracer_provider(provider)

        try:
            from openinference.instrumentation.google_adk import GoogleADKInstrumentor
            GoogleADKInstrumentor().instrument(tracer_provider=provider)
            logging.info("GoogleADKInstrumentor registered.")
        except ImportError:
            logging.warning(
                "openinference-instrumentation-google-adk not installed. "
                "Run: pip install openinference-instrumentation-google-adk"
            )

        try:
            from openinference.instrumentation.litellm import LiteLLMInstrumentor
            LiteLLMInstrumentor().instrument(tracer_provider=provider)
            logging.info("LiteLLMInstrumentor registered.")
        except ImportError:
            logging.warning(
                "openinference-instrumentation-litellm not installed. "
                "Run: pip install openinference-instrumentation-litellm"
            )

        logging.info(
            f"OTel tracing enabled → {endpoint}  (x-project-id: {project_id})"
        )
        return True

    except Exception as exc:
        logging.warning(f"Failed to initialise OTel tracing: {type(exc).__name__}: {exc}")
        return False
