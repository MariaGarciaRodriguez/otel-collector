"""Observability bootstrap for a centrally managed OTLP Collector.

The archetype knows only the central Collector endpoint. Backend endpoints,
credentials and routing policy belong to the observability account.
"""
from __future__ import annotations

import os

from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
from opentelemetry.instrumentation.pymongo import PymongoInstrumentor
from src.utils.logger import get_logger
from src.observability.agent365 import register_agent365_span_processor
from traceloop.sdk import Traceloop

logger = get_logger(__name__)
_httpx_instrumented = False
_pymongo_instrumented = False


def init_telemetry() -> None:
    enabled = os.getenv("OTEL_ENABLED", "true").lower() in {"1", "true", "yes"}
    if not enabled:
        logger.info("OpenTelemetry/OpenLLMetry disabled by OTEL_ENABLED")
        return

    # One endpoint owned by the platform. Keep TRACELOOP_BASE_URL compatible
    # without requiring a second user-facing variable in the archetype.
    collector_endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT")
    traceloop_base_url = os.getenv("TRACELOOP_BASE_URL") or collector_endpoint
    api_key = os.getenv("TRACELOOP_API_KEY")

    if traceloop_base_url and not os.getenv("TRACELOOP_BASE_URL"):
        os.environ["TRACELOOP_BASE_URL"] = traceloop_base_url

    if not traceloop_base_url and not api_key:
        logger.warning("OpenLLMetry not initialized: OTEL_EXPORTER_OTLP_ENDPOINT is not configured")
        return

    project_name = os.getenv("AGENT_NAME", "react-pattern-archetype")
    Traceloop.init(app_name=project_name)

    # Currently remains disabled by default. When the central Agent365 design
    # is finalized this application-specific processor can be retired/moved.
    register_agent365_span_processor()
    logger.info("OpenLLMetry initialized app_name=%s", project_name)


def instrument_httpx() -> None:
    global _httpx_instrumented
    enabled = os.getenv("OTEL_INSTRUMENT_HTTPX", "true").lower() in {"1", "true", "yes"}
    if enabled and not _httpx_instrumented:
        HTTPXClientInstrumentor().instrument()
        _httpx_instrumented = True
        logger.info("OpenTelemetry HTTPX instrumentation enabled")


def instrument_fastapi(app) -> None:
    enabled = os.getenv("OTEL_INSTRUMENT_FASTAPI", "true").lower() in {"1", "true", "yes"}
    if enabled:
        FastAPIInstrumentor.instrument_app(app, exclude_spans=["send", "receive"])
        logger.info("OpenTelemetry FastAPI instrumentation enabled")


def instrument_pymongo() -> None:
    global _pymongo_instrumented
    enabled = os.getenv("OTEL_INSTRUMENT_PYMONGO", "true").lower() in {"1", "true", "yes"}
    if enabled and not _pymongo_instrumented:
        PymongoInstrumentor().instrument(capture_statement=False)
        _pymongo_instrumented = True
        logger.info("OpenTelemetry PyMongo instrumentation enabled")
