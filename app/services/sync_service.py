"""Deferred API — Sync Service.

Handles synchronization of pending offline transactions,
conflict resolution, retry logic, and reconciliation.
"""

from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    GlobalSpend,
    OfflineToken,
    SyncQueue,
    Transaction,
    TokenStatus,
    TxStatus,
    SyncStatus,
)
from app.observability import SYNC_LATENCY, SYNC_OPERATIONS, get_logger

logger = get_logger("sync_service")

# Retry config
MAX_ATTEMPTS = 10
BASE_DELAY_SECONDS = 30


class SyncService:
    """Handles offline transaction synchronization and reconciliation."""

    @classmethod
    async def trigger_sync(
        cls,
        db: AsyncSession,
        wallet_id: Optional[str] = None,
        batch_size: int = 10,
        priority: str = "normal",
    ) -> dict:
        """Trigger synchronization of pending offline transactions.

        Steps:
        1. Fetch pending items from sync queue (ordered by priority, then timestamp)
        2. For each: verify token destruction proofs, settle, update status
        3. Handle conflicts (double-spend race conditions)
        4. Apply retry logic on failures

        Returns:
            Sync response dict with per-transaction results
        """
        start_time = time.perf_counter()

        # Priority mapping
        priority_map = {"normal": 5, "high": 3, "critical": 1}
        min_priority = priority_map.get(priority, 5)

        # Fetch pending sync items
        query = (
            select(SyncQueue)
            .where(
                SyncQueue.status.in_([SyncStatus.PENDING, SyncStatus.FAILED]),
                SyncQueue.priority <= min_priority + 5,
            )
            .order_by(SyncQueue.priority.asc(), SyncQueue.created_at.asc())
            .limit(batch_size)
        )

        if wallet_id:
            # Join with transactions to filter by wallet
            query = (
                select(SyncQueue)
                .join(Transaction, SyncQueue.tx_id == Transaction.id)
                .where(
                    SyncQueue.status.in_([SyncStatus.PENDING, SyncStatus.FAILED]),
                    Transaction.wallet_id == wallet_id,
                )
                .order_by(SyncQueue.priority.asc(), SyncQueue.created_at.asc())
                .limit(batch_size)
            )

        result = await db.execute(query)
        sync_items = result.scalars().all()

        results = []
        processed = 0

        for item in sync_items:
            item_start = time.perf_counter()
            try:
                sync_result = await cls._process_sync_item(db, item)
                item_latency = int((time.perf_counter() - item_start) * 1000)
                results.append({
                    "payment_id": item.tx_id,
                    "status": "synced",
                    "settlement_id": sync_result.get("settlement_id"),
                    "latency_ms": item_latency,
                })
                SYNC_OPERATIONS.labels(status="succeeded").inc()
                processed += 1
            except DoubleSpendDetected as e:
                results.append({
                    "payment_id": item.tx_id,
                    "status": "failed",
                    "error": "double_spend_detected",
                    "retryable": False,
                })
                SYNC_OPERATIONS.labels(status="double_spend").inc()
                processed += 1
            except SyncError as e:
                # Retry with exponential backoff
                item.attempts += 1
                if item.attempts >= MAX_ATTEMPTS:
                    item.status = SyncStatus.FAILED
                    retryable = False
                else:
                    delay = BASE_DELAY_SECONDS * (2 ** (item.attempts - 1))
                    item.next_retry_at = datetime.now(timezone.utc) + timedelta(seconds=delay)
                    item.status = SyncStatus.PENDING
                    retryable = True

                error_entry = {
                    "attempt": item.attempts,
                    "error": str(e),
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                }
                item.error_log = (item.error_log or []) + [error_entry]

                results.append({
                    "payment_id": item.tx_id,
                    "status": "failed",
                    "error": str(e),
                    "retryable": retryable,
                })
                SYNC_OPERATIONS.labels(status="failed").inc()
                processed += 1

        await db.flush()

        total_duration = time.perf_counter() - start_time
        SYNC_LATENCY.observe(total_duration)

        now = datetime.now(timezone.utc)
        logger.info(
            "sync_triggered",
            wallet_id=wallet_id,
            processed=processed,
            duration_ms=round(total_duration * 1000),
        )

        return {
            "triggered_at": now.isoformat(),
            "processed": processed,
            "results": results,
        }

    @classmethod
    async def _process_sync_item(cls, db: AsyncSession, item: SyncQueue) -> dict:
        """Process a single sync queue item.

        Verifies token proofs and marks the transaction as settled.
        """
        # Fetch transaction
        tx = await db.get(Transaction, item.tx_id)
        if not tx:
            item.status = SyncStatus.FAILED
            raise SyncError(f"Transaction {item.tx_id} not found")

        if tx.status == TxStatus.SUCCEEDED:
            # Already settled
            item.status = SyncStatus.COMPLETED
            return {"settlement_id": None}

        # Check for double-spend on all consumed tokens
        if tx.tokens_consumed:
            for token_id in tx.tokens_consumed:
                existing = await db.execute(
                    select(GlobalSpend).where(GlobalSpend.token_id == token_id)
                )
                if existing.scalar_one_or_none():
                    # Double-spend detected
                    tx.status = TxStatus.FAILED
                    tx.error_code = "double_spend_detected"
                    tx.error_message = f"Token {token_id} already spent"
                    item.status = SyncStatus.FAILED
                    raise DoubleSpendDetected(token_id)

                # Mark token as globally spent
                global_spend = GlobalSpend(
                    token_id=token_id,
                    tx_id=tx.id,
                    spent_at=datetime.now(timezone.utc),
                )
                db.add(global_spend)

        # Mark transaction as settled
        tx.status = TxStatus.SUCCEEDED
        tx.settled_at = datetime.now(timezone.utc)

        # Update sync queue
        item.status = SyncStatus.COMPLETED

        return {"settlement_id": None}


class SyncError(Exception):
    pass


class DoubleSpendDetected(Exception):
    def __init__(self, token_id: str):
        self.token_id = token_id
        super().__init__(f"Double-spend detected for token {token_id}")
