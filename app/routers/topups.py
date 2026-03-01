"""Deferred API — TopUp Router.

Endpoints:
    POST /topups — Fund a wallet from an external source
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Header, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_customer
from app.db import get_db
from app.models import (
    OfflineToken,
    TopUp,
    Wallet,
    TokenStatus,
    TopUpStatus,
    generate_prefixed_id,
)
from app.crypto.tokens import TokenManager, VALID_DENOMINATIONS
from app.crypto.secure_element import SoftwareSecureElement
from app.schemas import TopUpCreate
from app.observability import TOKEN_MINTING_DURATION, get_logger

import time

logger = get_logger("topup_router")

router = APIRouter(prefix="/topups", tags=["Funding"])


@router.post(
    "",
    response_model=None,
    status_code=status.HTTP_201_CREATED,
    summary="Fund a wallet",
    description="Move funds from an external source to a wallet and optionally allocate to offline reserve.",
    responses={
        201: {"description": "Top-up initiated"},
        400: {"description": "Invalid source"},
        404: {"description": "Wallet not found"},
        422: {"description": "Validation error"},
    },
)
async def create_topup(
    body: TopUpCreate,
    idempotency_key: str = Header(None, alias="Idempotency-Key"),
    db: AsyncSession = Depends(get_db),
    customer: dict = Depends(get_current_customer),
):
    """Fund a wallet with external funds.

    Steps:
    1. Idempotency check (via middleware)
    2. Source validation (simulated)
    3. Atomic balance update (online + offline allocation)
    4. If offline_allocation > 0: mint tokens immediately
    5. Emit webhook events (async)

    Requires `Idempotency-Key` header for safe retries.
    """
    # Fetch wallet
    wallet = await db.get(Wallet, body.wallet_id)
    if not wallet:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error": {
                    "type": "not_found",
                    "code": "wallet_not_found",
                    "message": f"Wallet {body.wallet_id} does not exist",
                    "how_to_fix": "Verify the wallet ID. Use POST /wallets to create one first",
                    "docs_link": "https://deferred.dev/docs/wallets",
                }
            },
        )

    # Validate offline allocation doesn't exceed allowance
    new_offline_total = wallet.offline_balance_cents + body.offline_allocation_cents
    if new_offline_total > wallet.offline_allowance_cents:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "error": {
                    "type": "validation_error",
                    "code": "offline_allowance_exceeded",
                    "message": (
                        f"Offline allocation would exceed allowance: "
                        f"{new_offline_total} > {wallet.offline_allowance_cents}"
                    ),
                    "how_to_fix": "Reduce offline_allocation_cents or increase the wallet's offline allowance",
                    "docs_link": "https://deferred.dev/docs/topups#offline-allocation",
                }
            },
        )

    # Atomic balance update
    online_amount = body.amount_cents - body.offline_allocation_cents
    wallet.online_balance_cents += online_amount
    wallet.offline_balance_cents += body.offline_allocation_cents
    wallet.updated_at = datetime.now(timezone.utc)

    # Create topup record
    topup_id = generate_prefixed_id("topup")
    topup = TopUp(
        id=topup_id,
        wallet_id=body.wallet_id,
        amount_cents=body.amount_cents,
        offline_allocation_cents=body.offline_allocation_cents,
        currency=body.currency,
        status=TopUpStatus.SUCCEEDED,  # Simulated instant success
        source_type=body.source.type,
        source_id=body.source.id,
        source_last4=body.source.id[-4:] if len(body.source.id) >= 4 else body.source.id,
        idempotency_key=idempotency_key,
        expected_availability=datetime.now(timezone.utc) + timedelta(days=3),
        metadata_=body.metadata,
    )
    db.add(topup)

    # Mint offline tokens if allocation > 0
    tokens_minted = 0
    if body.offline_allocation_cents > 0:
        mint_start = time.perf_counter()
        se = SoftwareSecureElement()
        manager = TokenManager(se)
        minted = manager.mint_tokens(body.wallet_id, body.offline_allocation_cents)

        for m_token in minted:
            db_token = OfflineToken(
                id=m_token.token_id,
                wallet_id=body.wallet_id,
                denomination_cents=m_token.denomination_cents,
                public_key=m_token.public_key,
                ancestry_chain=m_token.ancestry_chain,
                expiry_time=datetime.fromtimestamp(m_token.expiry_time, tz=timezone.utc),
                status=TokenStatus.MINTED,
            )
            db.add(db_token)
            tokens_minted += 1

        TOKEN_MINTING_DURATION.observe(time.perf_counter() - mint_start)

    await db.flush()

    logger.info(
        "topup_created",
        topup_id=topup_id,
        wallet_id=body.wallet_id,
        amount_cents=body.amount_cents,
        offline_allocation_cents=body.offline_allocation_cents,
        tokens_minted=tokens_minted,
    )

    return {
        "id": topup_id,
        "object": "topup",
        "amount_cents": body.amount_cents,
        "offline_allocation_cents": body.offline_allocation_cents,
        "status": "succeeded",
        "source": {
            "type": body.source.type,
            "last4": topup.source_last4,
        },
        "wallet": {
            "id": body.wallet_id,
            "online_balance_cents": wallet.online_balance_cents,
            "offline_balance_cents": wallet.offline_balance_cents,
        },
        "expected_availability": topup.expected_availability.isoformat(),
        "metadata": body.metadata,
    }
