"""Deferred API — Settlement Router.

Endpoints:
    POST /settlements — Merchant accepts offline payment proof
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_customer
from app.db import get_db
from app.schemas import SettlementCreate, EmergencySettlementCreate
from app.services.settlement_service import (
    SettlementService,
    SettlementError,
    DoubleSpendError,
)

router = APIRouter(prefix="/settlements", tags=["Settlements"])


@router.post(
    "",
    response_model=None,
    status_code=status.HTTP_201_CREATED,
    summary="Settle an offline payment",
    description="Merchant submits an offline payment proof for settlement. Verifies cryptographic proofs and guarantees funds.",
    responses={
        201: {"description": "Settlement created with guarantee"},
        400: {"description": "Invalid or expired proof"},
        409: {"description": "Double-spend detected"},
    },
)
async def create_settlement(
    body: SettlementCreate,
    db: AsyncSession = Depends(get_db),
):
    """Merchant accepts an offline payment and receives guaranteed funds.

    The settlement process:
    1. **Decode proof** — Validates the base64url-encoded payment proof
    2. **Verify merchant lock** — Ensures proof was generated for this merchant
    3. **Verify expiry** — Rejects expired proofs
    4. **Verify tokens** — Validates each token's signature and destruction proof
    5. **Double-spend check** — Queries global spend registry
    6. **Atomic settlement** — Marks tokens spent, creates settlement, queues payout

    The merchant receives a **guarantee** that funds will be available within 24h,
    with a 7-day dispute window.
    """
    try:
        result = await SettlementService.settle_payment(
            db=db,
            payment_proof=body.payment_proof,
            merchant_id=body.merchant_id,
            device_id=body.device_id,
            acceptance_timestamp=body.acceptance_timestamp,
        )
        return result
    except DoubleSpendError as e:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "error": {
                    "type": "settlement_error",
                    "code": "double_spend_detected",
                    "message": f"Token {e.token_id} has already been spent",
                    "how_to_fix": "This token was already redeemed. Reject the payment and ask the customer for a different token",
                    "docs_link": "https://deferred.dev/docs/settlements#double-spend",
                }
            },
        )
    except SettlementError as e:
        status_code = status.HTTP_400_BAD_REQUEST
        if e.code == "proof_expired":
            status_code = status.HTTP_400_BAD_REQUEST
        elif e.code == "merchant_mismatch":
            status_code = status.HTTP_403_FORBIDDEN

        raise HTTPException(
            status_code=status_code,
            detail={
                "error": {
                    "type": "settlement_error",
                    "code": e.code,
                    "message": e.message,
                    "how_to_fix": "Verify the payment proof is valid and intended for your merchant account",
                    "docs_link": "https://deferred.dev/docs/settlements#errors",
                }
            },
        )

@router.post(
    "/emergency",
    response_model=None,
    status_code=status.HTTP_201_CREATED,
    summary="Settle a 16-digit Emergency OTP Payment",
)
async def create_emergency_settlement(
    body: EmergencySettlementCreate,
    db: AsyncSession = Depends(get_db),
):
    try:
        result = await SettlementService.settle_emergency_code(
            db=db,
            merchant_id=body.merchant_id,
            amount_cents=body.amount_cents,
            otp_code=body.otp_code,
        )
        return result
    except SettlementError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error": {
                    "type": "settlement_error",
                    "code": e.code,
                    "message": e.message,
                }
            },
        )
