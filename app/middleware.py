"""Deferred API — Middleware.

Idempotency enforcement, security headers, request ID injection,
and structured error formatting.
"""

from __future__ import annotations

import hashlib
import json
import time
import uuid
from typing import Callable, Optional

from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from app.config import settings


class RequestIdMiddleware(BaseHTTPMiddleware):
    """Inject a unique request ID into every request/response."""

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        request_id = request.headers.get("X-Request-Id", str(uuid.uuid4()))
        request.state.request_id = request_id

        response = await call_next(request)
        response.headers["X-Request-Id"] = request_id
        return response


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Add security headers to every response."""

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        response = await call_next(request)

        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Strict-Transport-Security"] = (
            "max-age=31536000; includeSubDomains"
        )
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
        response.headers["Pragma"] = "no-cache"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"

        return response


class IdempotencyMiddleware(BaseHTTPMiddleware):
    """Enforce idempotency for POST requests with Idempotency-Key header.

    If a request with the same Idempotency-Key has been seen before (within 24h),
    return the cached response instead of processing again.

    Uses Redis for distributed idempotency across API instances.
    """

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        # Only enforce on POST/PUT
        if request.method not in ("POST", "PUT"):
            return await call_next(request)

        idempotency_key = request.headers.get("Idempotency-Key")
        if not idempotency_key:
            return await call_next(request)

        # Check Redis cache
        redis = getattr(request.app.state, "redis", None)
        if redis is None:
            return await call_next(request)

        cache_key = f"idempotency:{idempotency_key}"

        try:
            cached = await redis.get(cache_key)
            if cached:
                cached_data = json.loads(cached)
                return JSONResponse(
                    content=cached_data["body"],
                    status_code=cached_data["status_code"],
                    headers={"X-Idempotency-Replay": "true"},
                )
        except Exception:
            pass  # Redis failure: proceed without idempotency

        # Process request
        response = await call_next(request)

        # Cache successful responses
        if 200 <= response.status_code < 300:
            try:
                body = b""
                async for chunk in response.body_iterator:
                    body += chunk

                cache_data = json.dumps({
                    "body": json.loads(body),
                    "status_code": response.status_code,
                })
                await redis.setex(cache_key, 86400, cache_data)  # 24h TTL

                return Response(
                    content=body,
                    status_code=response.status_code,
                    headers=dict(response.headers),
                    media_type=response.media_type,
                )
            except Exception:
                pass

        return response


class ErrorFormattingMiddleware(BaseHTTPMiddleware):
    """Ensure all errors follow the Deferred error schema."""

    ERROR_DOCS = {
        400: "https://deferred.dev/docs/errors#bad-request",
        401: "https://deferred.dev/docs/errors#unauthorized",
        403: "https://deferred.dev/docs/errors#forbidden",
        404: "https://deferred.dev/docs/errors#not-found",
        409: "https://deferred.dev/docs/errors#conflict",
        422: "https://deferred.dev/docs/errors#validation-error",
        429: "https://deferred.dev/docs/errors#rate-limited",
        500: "https://deferred.dev/docs/errors#internal",
    }

    FIX_HINTS = {
        400: "Check your request body against the API reference",
        401: "Verify your authentication credentials are valid",
        403: "You don't have permission for this action. Check your API key scopes",
        404: "Verify the resource ID exists and you have access to it",
        409: "This resource already exists or conflicts with current state",
        422: "Fix the validation errors listed in the response",
        429: "Slow down your requests. Check the Retry-After header",
        500: "This is a server error. Please try again or contact support",
    }

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        try:
            response = await call_next(request)
            return response
        except Exception as exc:
            request_id = getattr(request.state, "request_id", "unknown")
            status_code = getattr(exc, "status_code", 500)

            error_body = {
                "error": {
                    "type": "api_error",
                    "code": type(exc).__name__.lower(),
                    "message": str(exc),
                    "how_to_fix": self.FIX_HINTS.get(status_code, "Contact support"),
                    "docs_link": self.ERROR_DOCS.get(status_code, "https://deferred.dev/docs/errors"),
                    "request_id": request_id,
                }
            }

            return JSONResponse(
                status_code=status_code,
                content=error_body,
            )


def setup_middleware(app: FastAPI) -> None:
    """Register all middleware in correct order (outermost first)."""
    app.add_middleware(ErrorFormattingMiddleware)
    app.add_middleware(SecurityHeadersMiddleware)
    app.add_middleware(RequestIdMiddleware)
    app.add_middleware(IdempotencyMiddleware)
