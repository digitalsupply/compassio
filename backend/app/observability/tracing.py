"""OpenTelemetry tracing setup.

Observability must never become an availability dependency: if the SDK is
missing, the endpoint is unset, or initialisation raises, the application
still starts and the manual spans become no-ops (``opentelemetry-api`` ships
a default no-op tracer).
"""

from __future__ import annotations

import logging
import os
from contextlib import contextmanager
from typing import Iterator

from opentelemetry import trace
from opentelemetry.trace import Span

logger = logging.getLogger("compassio.tracing")

DEFAULT_ENDPOINT = "http://otel-collector.opentelemetry.svc:4317"
DEFAULT_SERVICE_NAME = "compassio-backend"

_initialized = False


def _resolve_endpoint() -> str:
    """Explicitly-set (possibly empty) env wins; otherwise the cluster default."""
    if "OTEL_EXPORTER_OTLP_ENDPOINT" in os.environ:
        return os.environ["OTEL_EXPORTER_OTLP_ENDPOINT"].strip()
    return DEFAULT_ENDPOINT


def setup_tracing(app=None) -> bool:
    """Best-effort OTLP/gRPC tracer + auto-instrumentation.

    Returns ``True`` when tracing was configured, ``False`` otherwise.  Never
    raises.
    """
    global _initialized
    if _initialized:
        return True

    endpoint = _resolve_endpoint()
    if not endpoint:
        logger.info("tracing disabled (OTEL_EXPORTER_OTLP_ENDPOINT empty)")
        return False

    try:
        from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import (
            OTLPSpanExporter,
        )
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor

        service_name = os.getenv("OTEL_SERVICE_NAME", DEFAULT_SERVICE_NAME)
        resource = Resource.create({"service.name": service_name})
        provider = TracerProvider(resource=resource)
        exporter = OTLPSpanExporter(endpoint=endpoint, insecure=True)
        provider.add_span_processor(BatchSpanProcessor(exporter))
        trace.set_tracer_provider(provider)
        _initialized = True
        logger.info("tracing enabled endpoint=%s service=%s", endpoint, service_name)
    except Exception:  # pragma: no cover - depends on optional deps
        logger.warning("tracing init failed; continuing without traces", exc_info=True)
        return False

    if app is not None:
        _instrument(app)
    return True


def _instrument(app) -> None:
    try:
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

        FastAPIInstrumentor.instrument_app(app)
    except Exception:  # pragma: no cover
        logger.warning("fastapi instrumentation failed", exc_info=True)

    try:
        from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor

        HTTPXClientInstrumentor().instrument()
    except Exception:  # pragma: no cover
        logger.warning("httpx instrumentation failed", exc_info=True)

    # SQLAlchemy instrumentation is optional; it can conflict with the async
    # engine on some versions, so a failure here is non-fatal.
    try:
        from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor

        from app.db import get_engine

        SQLAlchemyInstrumentor().instrument(engine=get_engine().sync_engine)
    except Exception:  # pragma: no cover
        logger.warning("sqlalchemy instrumentation skipped", exc_info=True)


def get_tracer():
    return trace.get_tracer("compassio")


def current_trace_ids() -> tuple[str | None, str | None]:
    """Return ``(trace_id, span_id)`` as lowercase hex, or ``(None, None)``."""
    try:
        ctx = trace.get_current_span().get_span_context()
        if ctx is not None and ctx.is_valid:
            return format(ctx.trace_id, "032x"), format(ctx.span_id, "016x")
    except Exception:  # pragma: no cover
        pass
    return None, None


@contextmanager
def start_span(name: str, attributes: dict | None = None) -> Iterator[Span]:
    """Create a current span.  Safe/no-op when the SDK is not installed."""
    span = get_tracer().start_span(name)
    try:
        if attributes:
            for key, value in attributes.items():
                if value is not None:
                    try:
                        span.set_attribute(key, value)
                    except Exception:
                        pass
        with trace.use_span(span, end_on_exit=True):
            yield span
    except Exception:  # pragma: no cover
        raise


def set_span_attributes(span: Span | None, attributes: dict) -> None:
    if span is None:
        return
    for key, value in attributes.items():
        if value is None:
            continue
        try:
            span.set_attribute(key, value)
        except Exception:  # pragma: no cover
            pass


def set_current_span_attributes(attributes: dict) -> None:
    """Attach attributes to the active span (no-op without tracing)."""
    try:
        span = trace.get_current_span()
    except Exception:  # pragma: no cover
        return
    set_span_attributes(span, attributes)


__all__ = [
    "DEFAULT_ENDPOINT",
    "DEFAULT_SERVICE_NAME",
    "setup_tracing",
    "get_tracer",
    "current_trace_ids",
    "start_span",
    "set_span_attributes",
    "set_current_span_attributes",
]
