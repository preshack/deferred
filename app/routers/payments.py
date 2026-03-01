"""Deferred API — Payment Router.

Endpoints:
    POST /payments — Create a payment (online or offline mode)
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Header, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_customer
from app.db import get_db
from app.schemas import PaymentCreate, EmergencyPaymentCreate
from app.services.payment_service import (
    PaymentService,
    PaymentError,
    InsufficientFundsError,
)

router = APIRouter(prefix="/payments", tags=["Payments"])


@router.post(
    "",
    response_model=None,
    status_code=status.HTTP_201_CREATED,
    summary="Create a payment",
    description="Create a payment in online or offline mode. Offline payments generate cryptographic proofs for merchant settlement.",
    responses={
        201: {"description": "Payment created (online: succeeded, offline: 202 pending_sync)"},
        402: {"description": "Insufficient funds"},
        404: {"description": "Wallet not found"},
        422: {"description": "Validation error"},
    },
)
async def create_payment(
    body: PaymentCreate,
    x_deferred_mode: str = Header("online", alias="X-Deferred-Mode"),
    idempotency_key: str = Header(None, alias="Idempotency-Key"),
    db: AsyncSession = Depends(get_db),
    customer: dict = Depends(get_current_customer),
):
    """Create a payment. Works in airplane mode via `X-Deferred-Mode: offline`.

    **Online Mode** (default):
    - Immediate, synchronous balance deduction
    - Returns status `succeeded`
    - Requires network connectivity

    **Offline Mode** (`X-Deferred-Mode: offline`):
    - Cryptographic proof generation (Sign-Once)
    - Token selection and key destruction
    - Queued for sync when connectivity returns
    - Returns status `pending_sync` with settlement payload

    Headers:
    - `X-Deferred-Mode`: `online` (default) or `offline`
    - `Idempotency-Key`: UUID-v4 for safe retries (required for production)
    """
    mode = x_deferred_mode.lower() if x_deferred_mode else "online"
    if mode not in ("online", "offline"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error": {
                    "type": "invalid_request",
                    "code": "invalid_mode",
                    "message": f"Invalid deferred mode: '{mode}'. Must be 'online' or 'offline'",
                    "how_to_fix": "Set X-Deferred-Mode header to 'online' or 'offline'",
                    "docs_link": "https://deferred.dev/docs/payments#modes",
                }
            },
        )

    try:
        result = await PaymentService.create_payment(
            db=db,
            wallet_id=body.wallet_id,
            merchant_id=body.merchant_id,
            amount_cents=body.amount_cents,
            currency=body.currency,
            mode=mode,
            description=body.description,
            idempotency_key=idempotency_key,
            metadata=body.metadata,
        )

        # Offline payments return 202 Accepted
        status_code = 202 if mode == "offline" else 201
        from fastapi.responses import JSONResponse
        return JSONResponse(content=result, status_code=status_code)

    except InsufficientFundsError as e:
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail={
                "error": {
                    "type": "payment_error",
                    "code": "insufficient_funds",
                    "message": str(e),
                    "how_to_fix": f"Top up your wallet with POST /topups. You need {e.required} cents but have {e.available} cents in {e.mode} balance",
                    "docs_link": "https://deferred.dev/docs/payments#insufficient-funds",
                }
            },
        )
    except PaymentError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error": {
                    "type": "payment_error",
                    "code": e.code,
                    "message": e.message,
                    "how_to_fix": "Check the error code and message for details",
                    "docs_link": "https://deferred.dev/docs/payments#errors",
                }
            },
        )

@router.post(
    "/emergency",
    response_model=None,
    status_code=status.HTTP_201_CREATED,
    summary="Create a 16-digit Emergency OTP Payment",
)
async def create_emergency_payment(
    body: EmergencyPaymentCreate,
    db: AsyncSession = Depends(get_db),
    customer: dict = Depends(get_current_customer),
):
    try:
        result = await PaymentService.generate_emergency_code(
            db=db,
            wallet_id=body.wallet_id,
            amount_cents=body.amount_cents,
        )
        from fastapi.responses import JSONResponse
        return JSONResponse(content=result, status_code=201)

    except InsufficientFundsError as e:
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail={
                "error": {
                    "type": "payment_error",
                    "code": "insufficient_funds",
                    "message": str(e),
                }
            },
        )
    except PaymentError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error": {
                    "type": "payment_error",
                    "code": e.code,
                    "message": e.message,
                }
            },
        )
