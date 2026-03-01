"""Deferred API — Authentication module.

JWT authentication for online mode (EdDSA/HS256) and cryptographic proof
validation for offline mode. API key management for merchants.
"""

from __future__ import annotations

import hashlib
import secrets
import time
from datetime import datetime, timedelta, timezone
from typing import Optional

import jwt
from fastapi import Depends, Header, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.config import settings

security = HTTPBearer(auto_error=False)


# ─── JWT Token Management ────────────────────────────────────────────────────


def create_access_token(
    customer_id: str,
    wallet_ids: list[str] | None = None,
    expires_delta: timedelta | None = None,
) -> str:
    """Create a JWT access token.

    Args:
        customer_id: Customer identifier
        wallet_ids: Optional list of wallet IDs this token can access
        expires_delta: Custom expiration (default: 15 minutes)

    Returns:
        Encoded JWT string
    """
    if expires_delta is None:
        expires_delta = timedelta(minutes=settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES)

    now = datetime.now(timezone.utc)
    payload = {
        "sub": customer_id,
        "type": "access",
        "iat": now,
        "exp": now + expires_delta,
        "jti": secrets.token_hex(16),
    }
    if wallet_ids:
        payload["wallet_ids"] = wallet_ids

    return jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def create_refresh_token(customer_id: str) -> str:
    """Create a long-lived refresh token."""
    now = datetime.now(timezone.utc)
    payload = {
        "sub": customer_id,
        "type": "refresh",
        "iat": now,
        "exp": now + timedelta(days=settings.JWT_REFRESH_TOKEN_EXPIRE_DAYS),
        "jti": secrets.token_hex(16),
    }
    return jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def decode_token(token: str) -> dict:
    """Decode and validate a JWT token.

    Raises:
        HTTPException: If token is invalid or expired
    """
    try:
        payload = jwt.decode(
            token,
            settings.JWT_SECRET_KEY,
            algorithms=[settings.JWT_ALGORITHM],
        )
        return payload
    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "error": {
                    "type": "authentication_error",
                    "code": "token_expired",
                    "message": "Access token has expired",
                    "how_to_fix": "Use your refresh token at POST /auth/refresh to get a new access token",
                    "docs_link": "https://deferred.dev/docs/auth#refresh-tokens",
                }
            },
        )
    except jwt.InvalidTokenError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "error": {
                    "type": "authentication_error",
                    "code": "invalid_token",
                    "message": f"Invalid token: {str(e)}",
                    "how_to_fix": "Obtain a new token via POST /auth/token with valid credentials",
                    "docs_link": "https://deferred.dev/docs/auth",
                }
            },
        )


# ─── FastAPI Dependencies ────────────────────────────────────────────────────


async def get_current_customer(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
    x_deferred_mode: Optional[str] = Header(None),
    x_api_key: Optional[str] = Header(None),
) -> dict:
    """FastAPI dependency: extract and validate the current customer.

    Supports:
    1. Bearer JWT token (online mode)
    2. API key (merchant operations)
    3. Offline proof (header indicates offline mode)
    """
    # API key auth (merchants)
    if x_api_key:
        return validate_api_key(x_api_key)

    # Offline mode: relaxed auth (proof in request body)
    if x_deferred_mode and x_deferred_mode.lower() == "offline":
        return {
            "customer_id": "offline_customer",
            "auth_method": "offline_proof",
            "permissions": ["payment:create", "payment:read"],
        }

    # JWT auth (default)
    if not credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "error": {
                    "type": "authentication_error",
                    "code": "missing_credentials",
                    "message": "No authentication credentials provided",
                    "how_to_fix": "Include 'Authorization: Bearer <token>' header or 'X-Api-Key' header",
                    "docs_link": "https://deferred.dev/docs/auth",
                }
            },
            headers={"WWW-Authenticate": "Bearer"},
        )

    payload = decode_token(credentials.credentials)
    return {
        "customer_id": payload["sub"],
        "auth_method": "jwt",
        "token_type": payload.get("type", "access"),
        "wallet_ids": payload.get("wallet_ids"),
        "permissions": ["wallet:*", "payment:*", "topup:*", "sync:*"],
    }


def validate_api_key(api_key: str) -> dict:
    """Validate a merchant API key.

    In production, this would query the database.
    For development, we accept keys prefixed with 'sk_test_'.
    """
    if api_key.startswith("sk_test_") and len(api_key) > 16:
        return {
            "customer_id": f"merchant_{hashlib.sha256(api_key.encode()).hexdigest()[:12]}",
            "auth_method": "api_key",
            "permissions": ["settlement:create", "settlement:read", "payment:read"],
        }

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail={
            "error": {
                "type": "authentication_error",
                "code": "invalid_api_key",
                "message": "Invalid API key",
                "how_to_fix": "Use a valid API key from your dashboard. Test keys start with 'sk_test_'",
                "docs_link": "https://deferred.dev/docs/auth#api-keys",
            }
        },
    )


def generate_api_key(prefix: str = "sk_test") -> str:
    """Generate a new API key."""
    return f"{prefix}_{secrets.token_hex(24)}"
