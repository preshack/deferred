"""Deferred API — Sync Router.

Endpoints:
    POST /sync/trigger — Force synchronization of pending offline transactions
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_customer
from app.db import get_db
from app.schemas import SyncTrigger
from app.services.sync_service import SyncService

router = APIRouter(prefix="/sync", tags=["Sync & Reconciliation"])


@router.post(
    "/trigger",
    response_model=None,
    status_code=status.HTTP_200_OK,
    summary="Trigger sync of pending transactions",
    description="Force synchronization of pending offline transactions. Handles conflict resolution and retries.",
    responses={
        200: {"description": "Sync results with per-transaction status"},
    },
)
async def trigger_sync(
    body: SyncTrigger,
    db: AsyncSession = Depends(get_db),
    customer: dict = Depends(get_current_customer),
):
    """Force synchronization of pending offline transactions.

    For each pending transaction:
    1. Re-verifies token destruction proofs
    2. Submits to the settlement network
    3. Updates transaction status
    4. Handles conflicts (double-spend race conditions)

    Retry logic: exponential backoff, max 10 attempts.
    Failed transactions move to dead-letter queue.

    Priority levels:
    - `normal` (default): Standard processing order
    - `high`: Prioritized ahead of normal
    - `critical`: Immediate processing
    """
    result = await SyncService.trigger_sync(
        db=db,
        wallet_id=body.wallet_id,
        batch_size=body.batch_size,
        priority=body.priority,
    )
    return result
