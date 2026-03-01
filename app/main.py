"""Deferred API — Application entry point.

FastAPI application factory with lifespan management, middleware registration,
router inclusion, and interactive OpenAPI documentation.
"""

from __future__ import annotations

from contextlib import asynccontextmanager

import redis.asyncio as aioredis
from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.config import settings
from app.db import init_db, close_db
from app.middleware import setup_middleware
from app.observability import (
    get_logger,
    get_metrics,
    metrics_middleware,
    setup_logging,
    setup_tracing,
)

# Initialize structured logging
setup_logging()
logger = get_logger("main")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifecycle: startup and shutdown events."""
    logger.info("starting_deferred_api", version=settings.API_VERSION)

    # Initialize database (create tables in dev mode)
    try:
        await init_db()
        logger.info("database_initialized")
    except Exception as e:
        logger.error("database_init_failed", error=str(e))

    # Connect to Redis
    try:
        app.state.redis = aioredis.from_url(
            settings.REDIS_URL,
            decode_responses=True,
            socket_connect_timeout=5,
        )
        await app.state.redis.ping()
        logger.info("redis_connected")
    except Exception as e:
        logger.warning("redis_connection_failed", error=str(e))
        app.state.redis = None

    # Connect to RabbitMQ (best-effort)
    try:
        from app.services.event_bus import event_bus
        await event_bus.connect()
    except Exception as e:
        logger.warning("rabbitmq_connection_failed", error=str(e))

    yield

    # Shutdown
    logger.info("shutting_down_deferred_api")
    if hasattr(app.state, "redis") and app.state.redis:
        await app.state.redis.close()
    await close_db()

    try:
        from app.services.event_bus import event_bus
        await event_bus.close()
    except Exception:
        pass


# ─── App Factory ──────────────────────────────────────────────────────────────

app = FastAPI(
    title=settings.API_TITLE,
    version=settings.API_VERSION,
    description=(
        "**Deferred** — Offline-first payment API.\n\n"
        "Stripe for the real world. Process payments seamlessly offline, "
        "synchronize intelligently when connectivity returns, and maintain "
        "cryptographic guarantees against double-spending.\n\n"
        "## Quick Start\n"
        "1. Authenticate: `POST /auth/token`\n"
        "2. Create wallet: `POST /wallets`\n"
        "3. Fund wallet: `POST /topups`\n"
        "4. Make payment: `POST /payments` (use `X-Deferred-Mode: offline` for offline)\n"
        "5. Settle: `POST /settlements`\n"
        "6. Sync: `POST /sync/trigger`\n"
    ),
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
    lifespan=lifespan,
    servers=[
        {"url": "http://localhost:8000", "description": "Local development"},
    ],
)

# ─── CORS ─────────────────────────────────────────────────────────────────────

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS if settings.CORS_ORIGINS != ["*"] else [],
    allow_origin_regex=".*" if settings.CORS_ORIGINS == ["*"] else None,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ─── Custom Middleware ────────────────────────────────────────────────────────

setup_middleware(app)

# ─── Tracing ──────────────────────────────────────────────────────────────────

setup_tracing(app)

# ─── Metrics Middleware ───────────────────────────────────────────────────────

@app.middleware("http")
async def _metrics_middleware(request: Request, call_next):
    return await metrics_middleware(request, call_next)


# ─── Routers ──────────────────────────────────────────────────────────────────

from app.routers import auth_routes, wallets, topups, payments, settlements, sync

app.include_router(auth_routes.router)
app.include_router(wallets.router)
app.include_router(topups.router)
app.include_router(payments.router)
app.include_router(settlements.router)
app.include_router(sync.router)


# ─── Utility Endpoints ───────────────────────────────────────────────────────


@app.get("/health", tags=["System"], summary="Health check")
async def health_check(request: Request):
    """System health check. Returns service connectivity status."""
    services = {"database": "unknown", "redis": "unknown", "rabbitmq": "unknown"}

    # Check Redis
    try:
        if hasattr(request.app.state, "redis") and request.app.state.redis:
            await request.app.state.redis.ping()
            services["redis"] = "healthy"
        else:
            services["redis"] = "disconnected"
    except Exception:
        services["redis"] = "unhealthy"

    # Database check (lightweight)
    try:
        from app.db import engine
        async with engine.connect() as conn:
            await conn.execute(__import__("sqlalchemy").text("SELECT 1"))
        services["database"] = "healthy"
    except Exception:
        services["database"] = "unhealthy"

    # RabbitMQ check
    try:
        from app.services.event_bus import event_bus
        if event_bus._connection:
            services["rabbitmq"] = "healthy"
        else:
            services["rabbitmq"] = "disconnected"
    except Exception:
        services["rabbitmq"] = "disconnected"

    overall = "healthy" if all(
        v in ("healthy", "disconnected") for v in services.values()
    ) else "degraded"

    return {
        "status": overall,
        "version": settings.API_VERSION,
        "services": services,
    }


@app.get("/metrics", tags=["System"], summary="Prometheus metrics")
async def prometheus_metrics():
    """Prometheus-compatible metrics endpoint."""
    return Response(
        content=get_metrics(),
        media_type="text/plain; charset=utf-8",
    )
