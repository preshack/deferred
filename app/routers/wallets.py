"""Deferred API — Wallet Router.

Endpoints:
    POST /wallets — Create a new wallet with HD key generation
    GET  /wallets/{wallet_id} — Retrieve wallet with balances and sync status
"""

from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_customer
from app.db import get_db
from app.schemas import WalletCreate, WalletResponse, WalletDetailResponse
from app.services.wallet_service import WalletService, WalletLimitError, WalletNotFoundError

router = APIRouter(prefix="/wallets", tags=["Wallets"])


@router.post(
    "",
    response_model=None,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new wallet",
    description="Create a hierarchical wallet with offline capability, HD key generation, and Shamir recovery.",
    responses={
        201: {"description": "Wallet created successfully"},
        400: {"description": "Device lacks required security tier"},
        409: {"description": "Customer has maximum wallets (10)"},
        422: {"description": "Invalid currency or negative allowance"},
    },
)
async def create_wallet(
    body: WalletCreate,
    db: AsyncSession = Depends(get_db),
    customer: dict = Depends(get_current_customer),
):
    """Create a new wallet with offline payment capability.

    This endpoint:
    1. Validates device attestation
    2. Generates a master seed (32 bytes, CSPRNG)
    3. Derives BIP-32 path keypairs
    4. Splits master seed via Shamir's Secret Sharing
    5. Creates the wallet record

    Returns the wallet with public keys and recovery information.
    """
    try:
        result = await WalletService.create_wallet(
            db=db,
            customer_id=body.customer_reference,
            wallet_type=body.type,
            offline_allowance_cents=body.offline_allowance_cents,
            currency=body.currency,
            security_tier=body.security_tier,
            device_id=body.device_binding.device_id if body.device_binding else None,
            recovery_shares_required=body.recovery_configuration.shares_required,
            recovery_shares_total=body.recovery_configuration.shares_total,
        )
        return result
    except WalletLimitError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "error": {
                    "type": "conflict",
                    "code": "wallet_limit_reached",
                    "message": "Customer has reached the maximum number of wallets (10)",
                    "how_to_fix": "Close an existing wallet before creating a new one",
                    "docs_link": "https://deferred.dev/docs/wallets#limits",
                }
            },
        )


@router.get(
    "/{wallet_id}",
    response_model=None,
    summary="Retrieve wallet details",
    description="Get wallet state including balances, sync status, and optional token expansion.",
    responses={
        200: {"description": "Wallet details"},
        404: {"description": "Wallet not found"},
    },
)
async def get_wallet(
    wallet_id: str,
    include_pending: bool = Query(True, description="Include un-synced offline transactions"),
    expand: Optional[List[str]] = Query(None, description="Expand related objects: tokens, recent_transactions"),
    db: AsyncSession = Depends(get_db),
    customer: dict = Depends(get_current_customer),
):
    """Retrieve wallet state with sync status and optional expansions.

    Query Parameters:
    - `include_pending`: Include pending offline transactions in balance
    - `expand[]`: Expand objects — `tokens` (unspent offline tokens)
    """
    try:
        result = await WalletService.get_wallet(
            db=db,
            wallet_id=wallet_id,
            include_pending=include_pending,
            expand=expand or [],
        )
        return result
    except WalletNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error": {
                    "type": "not_found",
                    "code": "wallet_not_found",
                    "message": f"Wallet {wallet_id} does not exist",
                    "how_to_fix": "Verify the wallet ID. Use GET /wallets to list your wallets",
                    "docs_link": "https://deferred.dev/docs/wallets#get",
                }
            },
        )
