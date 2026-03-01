"""Deferred API — Observability module.

Structured JSON logging, Prometheus metrics, and OpenTelemetry tracing.
"""

from __future__ import annotations

import logging
import sys
import time
from typing import Callable

import structlog
from fastapi import FastAPI, Request, Response
from prometheus_client import (
    CollectorRegistry,
    Counter,
    Histogram,
    generate_latest,
    make_asgi_app,
)

from app.config import settings

# ─── Prometheus Metrics ───────────────────────────────────────────────────────

registry = CollectorRegistry()

# Counters
PAYMENTS_TOTAL = Counter(
    "deferred_payments_total",
    "Total payments processed",
    ["mode", "status"],
    registry=registry,
)

OFFLINE_PAYMENTS_TOTAL = Counter(
    "deferred_offline_payments_total",
    "Total offline payments",
    ["status"],
    registry=registry,
)

DOUBLE_SPEND_ATTEMPTS = Counter(
    "deferred_double_spend_attempts_total",
    "Total double-spend attempts detected",
    registry=registry,
)

SYNC_OPERATIONS = Counter(
    "deferred_sync_operations_total",
    "Total sync operations",
    ["status"],
    registry=registry,
)

SE_OPERATIONS = Counter(
    "deferred_secure_element_operations_total",
    "Total secure element operations",
    ["operation"],
    registry=registry,
)

# Histograms
REQUEST_LATENCY = Histogram(
    "deferred_request_duration_seconds",
    "Request latency in seconds",
    ["method", "endpoint", "status_code"],
    buckets=[0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0],
    registry=registry,
)

SYNC_LATENCY = Histogram(
    "deferred_sync_latency_seconds",
    "Sync operation latency",
    registry=registry,
)

TOKEN_MINTING_DURATION = Histogram(
    "deferred_token_minting_duration_seconds",
    "Token minting operation duration",
    registry=registry,
)

PAYMENT_PROOF_DURATION = Histogram(
    "deferred_payment_proof_generation_seconds",
    "Offline payment proof generation duration",
    registry=registry,
)


# ─── Structured Logging ──────────────────────────────────────────────────────


def setup_logging() -> None:
    """Configure structlog for JSON-formatted structured logging."""
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.StackInfoRenderer(),
            structlog.dev.set_exc_info,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(
            logging.getLevelName(settings.LOG_LEVEL)
        ),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(file=sys.stdout),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str = "deferred-api") -> structlog.BoundLogger:
    """Get a structured logger instance."""
    return structlog.get_logger(name)


# ─── OpenTelemetry Tracing ────────────────────────────────────────────────────


def setup_tracing(app: FastAPI) -> None:
    """Configure OpenTelemetry tracing (best-effort, won't fail startup)."""
    try:
        from opentelemetry import trace
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor

        resource = Resource.create({"service.name": settings.OTEL_SERVICE_NAME})
        provider = TracerProvider(resource=resource)

        try:
            from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import (
                OTLPSpanExporter,
            )
            exporter = OTLPSpanExporter(endpoint=settings.OTEL_EXPORTER_OTLP_ENDPOINT)
            provider.add_span_processor(BatchSpanProcessor(exporter))
        except Exception:
            pass  # OTLP exporter not available — tracing still works locally

        trace.set_tracer_provider(provider)
        FastAPIInstrumentor.instrument_app(app)
    except ImportError:
        pass  # OTel not installed — skip gracefully


# ─── Middleware ───────────────────────────────────────────────────────────────


async def metrics_middleware(request: Request, call_next: Callable) -> Response:
    """Record request latency and count for Prometheus."""
    start = time.perf_counter()
    response = await call_next(request)
    duration = time.perf_counter() - start

    # Normalize path (remove IDs for cardinality control)
    path = request.url.path
    for segment in path.split("/"):
        if segment.startswith(("wallet_", "pay_", "tok_", "stl_", "topup_")):
            path = path.replace(segment, "{id}")

    REQUEST_LATENCY.labels(
        method=request.method,
        endpoint=path,
        status_code=response.status_code,
    ).observe(duration)

    return response


def get_metrics() -> bytes:
    """Generate Prometheus metrics output."""
    return generate_latest(registry)
