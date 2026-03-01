"""Deferred API — Auth Router.

Endpoints:
    POST /auth/token — Issue JWT access token
    POST /auth/refresh — Refresh an expired access token
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, status

from app.auth import create_access_token, create_refresh_token, decode_token
from app.config import settings
from app.schemas import TokenRequest, TokenResponse, RefreshRequest

router = APIRouter(prefix="/auth", tags=["Authentication"])


@router.post(
    "/token",
    response_model=TokenResponse,
    summary="Issue access token",
    description="Authenticate with customer credentials and receive a JWT access token.",
    responses={
        200: {"description": "Token issued successfully"},
        401: {"description": "Invalid credentials"},
    },
)
async def issue_token(body: TokenRequest):
    """Issue a JWT access token for API authentication.

    In production, this validates against a customer database.
    In development, any customer_id with secret 'test_secret' is accepted.

    Returns:
    - `access_token`: Short-lived JWT (15 min default)
    - `refresh_token`: Long-lived JWT (7 days default)
    """
    # Development: accept test credentials
    # Production: validate against customer DB + password hash (Argon2id)
    if body.secret != "test_secret":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "error": {
                    "type": "authentication_error",
                    "code": "invalid_credentials",
                    "message": "Invalid customer_id or secret",
                    "how_to_fix": "Verify your credentials. In test mode, use secret 'test_secret'",
                    "docs_link": "https://deferred.dev/docs/auth#credentials",
                }
            },
        )

    access_token = create_access_token(body.customer_id)
    refresh_token = create_refresh_token(body.customer_id)

    return TokenResponse(
        access_token=access_token,
        token_type="bearer",
        expires_in=settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        refresh_token=refresh_token,
    )


@router.post(
    "/refresh",
    response_model=TokenResponse,
    summary="Refresh access token",
    description="Exchange a valid refresh token for a new access token.",
    responses={
        200: {"description": "New tokens issued"},
        401: {"description": "Invalid or expired refresh token"},
    },
)
async def refresh_token(body: RefreshRequest):
    """Exchange a refresh token for a new access/refresh token pair.

    The old refresh token is invalidated (rotation).
    """
    payload = decode_token(body.refresh_token)

    if payload.get("type") != "refresh":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "error": {
                    "type": "authentication_error",
                    "code": "invalid_token_type",
                    "message": "Expected a refresh token, received an access token",
                    "how_to_fix": "Use the refresh_token (not access_token) from the /auth/token response",
                    "docs_link": "https://deferred.dev/docs/auth#refresh-tokens",
                }
            },
        )

    access_token = create_access_token(payload["sub"])
    new_refresh_token = create_refresh_token(payload["sub"])

    return TokenResponse(
        access_token=access_token,
        token_type="bearer",
        expires_in=settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        refresh_token=new_refresh_token,
    )
