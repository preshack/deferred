"""Deferred API — Payment Service.

Business logic for online and offline payment processing.
Handles token selection, proof generation, and sync queue management.
"""

from __future__ import annotations

import base64
import hashlib
import json
import time
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.crypto.secure_element import SoftwareSecureElement
from app.crypto.tokens import (
    MintedToken,
    TokenManager,
    TransactionPayload,
    select_tokens,
)
from app.models import (
    GlobalSpend,
    OfflineToken,
    SyncQueue,
    Transaction,
    Wallet,
    TokenStatus,
    TxMode,
    TxStatus,
    SyncStatus,
    generate_prefixed_id,
)
from app.observability import (
    OFFLINE_PAYMENTS_TOTAL,
    PAYMENTS_TOTAL,
    PAYMENT_PROOF_DURATION,
    SE_OPERATIONS,
    get_logger,
)

logger = get_logger("payment_service")

# Module-level secure element (shared across requests in dev mode)
_secure_element = SoftwareSecureElement()
_token_manager = TokenManager(_secure_element)


class PaymentService:
    """Handles online and offline payment processing."""

    @classmethod
    async def create_payment(
        cls,
        db: AsyncSession,
        wallet_id: str,
        merchant_id: str,
        amount_cents: int,
        currency: str = "usd",
        mode: str = "online",
        description: Optional[str] = None,
        idempotency_key: Optional[str] = None,
        metadata: Optional[dict] = None,
    ) -> dict:
        """Create a payment in either online or offline mode.

        Online: Immediate, synchronous balance deduction
        Offline: Cryptographic proof generation + sync queue

        Returns:
            Payment response dict matching the API spec
        """
        if mode == "offline":
            return await cls._create_offline_payment(
                db, wallet_id, merchant_id, amount_cents, currency,
                description, idempotency_key, metadata,
            )
        else:
            return await cls._create_online_payment(
                db, wallet_id, merchant_id, amount_cents, currency,
                description, idempotency_key, metadata,
            )

    @classmethod
    async def _create_online_payment(
        cls,
        db: AsyncSession,
        wallet_id: str,
        merchant_id: str,
        amount_cents: int,
        currency: str,
        description: Optional[str],
        idempotency_key: Optional[str],
        metadata: Optional[dict],
    ) -> dict:
        """Process an online (synchronous) payment."""
        wallet = await db.get(Wallet, wallet_id)
        if not wallet:
            raise PaymentError("wallet_not_found", f"Wallet {wallet_id} not found")

        if wallet.online_balance_cents < amount_cents:
            raise InsufficientFundsError(
                wallet.online_balance_cents, amount_cents, "online"
            )

        # Atomic balance deduction
        wallet.online_balance_cents -= amount_cents
        wallet.updated_at = datetime.now(timezone.utc)

        # Create transaction record
        tx_id = generate_prefixed_id("pay")
        tx = Transaction(
            id=tx_id,
            wallet_id=wallet_id,
            merchant_id=merchant_id,
            mode=TxMode.ONLINE,
            status=TxStatus.SUCCEEDED,
            amount_cents=amount_cents,
            currency=currency,
            description=description,
            idempotency_key=idempotency_key,
            settled_at=datetime.now(timezone.utc),
            metadata_=metadata or {},
        )
        db.add(tx)
        await db.flush()

        PAYMENTS_TOTAL.labels(mode="online", status="succeeded").inc()

        logger.info(
            "online_payment_created",
            tx_id=tx_id,
            wallet_id=wallet_id,
            merchant_id=merchant_id,
            amount_cents=amount_cents,
        )

        return {
            "id": tx_id,
            "object": "payment",
            "amount_cents": amount_cents,
            "currency": currency,
            "status": "succeeded",
            "mode": "online",
            "wallet_id": wallet_id,
            "merchant_id": merchant_id,
            "created_at": tx.created_at.isoformat(),
        }

    @classmethod
    async def _create_offline_payment(
        cls,
        db: AsyncSession,
        wallet_id: str,
        merchant_id: str,
        amount_cents: int,
        currency: str,
        description: Optional[str],
        idempotency_key: Optional[str],
        metadata: Optional[dict],
    ) -> dict:
        """Process an offline payment with cryptographic proof generation.

        Phase 1: Validate offline balance
        Phase 2: Select tokens + generate proofs (Sign-Once)
        Phase 3: Queue for sync
        """
        start_time = time.perf_counter()

        wallet = await db.get(Wallet, wallet_id)
        if not wallet:
            raise PaymentError("wallet_not_found", f"Wallet {wallet_id} not found")

        if wallet.offline_balance_cents < amount_cents:
            raise InsufficientFundsError(
                wallet.offline_balance_cents, amount_cents, "offline"
            )

        # Phase 1: Load available tokens
        token_result = await db.execute(
            select(OfflineToken).where(
                OfflineToken.wallet_id == wallet_id,
                OfflineToken.status == TokenStatus.MINTED,
            )
        )
        db_tokens = token_result.scalars().all()

        # Convert to MintedToken objects for coin selection
        available = [
            MintedToken(
                token_id=t.id,
                denomination_cents=t.denomination_cents,
                public_key=t.public_key,
                key_id=f"token:{t.id}",
                ancestry_chain=t.ancestry_chain or [],
                expiry_time=t.expiry_time.timestamp(),
                wallet_id=wallet_id,
            )
            for t in db_tokens
        ]

        # Phase 2: Select tokens
        try:
            selected = select_tokens(available, amount_cents)
        except ValueError as e:
            raise InsufficientFundsError(
                sum(t.denomination_cents for t in available),
                amount_cents,
                "offline",
            )

        # Create transaction payload
        tx_id = generate_prefixed_id("pay")
        now = time.time()
        tx_payload = TransactionPayload(
            tx_id=tx_id,
            merchant_id=merchant_id,
            amount_cents=amount_cents,
            currency=currency,
            timestamp=now,
            nonce=int(now * 1000) % 2**32,
            expiry=now + 86400,  # 24h expiry
        )

        # Generate spend proofs (Sign-Once for each token)
        proofs = []
        consumed_token_ids = []

        for token in selected:
            try:
                # Ensure keypair exists in SE for this token
                key_id = f"token:{token.token_id}"
                if not _secure_element.has_key(key_id):
                    keypair = _secure_element.generate_keypair(key_id, extractable=True)

                proof = _token_manager.spend_token(token, tx_payload)
                proofs.append({
                    "token_id": proof.token_id,
                    "signature": base64.b64encode(proof.signature).decode(),
                    "public_key": base64.b64encode(proof.public_key).decode(),
                    "destruction_proof": base64.b64encode(
                        proof.destruction_proof.serialize()
                    ).decode(),
                })
                consumed_token_ids.append(token.token_id)

                SE_OPERATIONS.labels(operation="sign_and_destroy").inc()
            except Exception as e:
                logger.error("token_spend_failed", token_id=token.token_id, error=str(e))
                raise PaymentError("token_spend_failed", f"Failed to spend token: {e}")

        # Phase 3: Update database
        # Mark tokens as spent
        for token_id in consumed_token_ids:
            db_token = await db.get(OfflineToken, token_id)
            if db_token:
                db_token.status = TokenStatus.SPENT
                db_token.spent_in_tx = tx_id
                db_token.spent_at = datetime.now(timezone.utc)

        # Deduct offline balance
        total_spent = sum(t.denomination_cents for t in selected)
        wallet.offline_balance_cents -= total_spent
        wallet.updated_at = datetime.now(timezone.utc)

        # Create transaction record
        settlement_payload = base64.urlsafe_b64encode(
            json.dumps({
                "version": "1.0",
                "tx_id": tx_id,
                "merchant_id": merchant_id,
                "amount_cents": amount_cents,
                "proofs": proofs,
                "expiry": tx_payload.expiry,
            }).encode()
        ).decode()

        verification_hash = hashlib.sha256(settlement_payload.encode()).hexdigest()

        tx = Transaction(
            id=tx_id,
            wallet_id=wallet_id,
            merchant_id=merchant_id,
            mode=TxMode.OFFLINE,
            status=TxStatus.PENDING,
            amount_cents=amount_cents,
            currency=currency,
            description=description,
            idempotency_key=idempotency_key,
            offline_proof={"proofs": proofs, "expiry": tx_payload.expiry},
            tokens_consumed=consumed_token_ids,
            metadata_=metadata or {},
        )
        db.add(tx)
        
        # Flush transaction to DB so SyncQueue foreign key is satisfied
        await db.flush()

        # Queue for sync
        sync_item = SyncQueue(
            tx_id=tx_id,
            priority=5,
            status=SyncStatus.PENDING,
        )
        db.add(sync_item)
        await db.flush()

        duration = time.perf_counter() - start_time
        PAYMENT_PROOF_DURATION.observe(duration)
        OFFLINE_PAYMENTS_TOTAL.labels(status="pending_sync").inc()

        logger.info(
            "offline_payment_created",
            tx_id=tx_id,
            wallet_id=wallet_id,
            merchant_id=merchant_id,
            amount_cents=amount_cents,
            tokens_consumed=len(consumed_token_ids),
            latency_ms=round(duration * 1000),
        )

        return {
            "id": tx_id,
            "object": "payment",
            "amount_cents": amount_cents,
            "currency": currency,
            "status": "pending_sync",
            "mode": "offline",
            "wallet_id": wallet_id,
            "merchant_id": merchant_id,
            "offline_proof": {
                "expires_at": datetime.fromtimestamp(
                    tx_payload.expiry, tz=timezone.utc
                ).isoformat(),
                "settlement_payload": settlement_payload,
                "qr_code": "",  # QR generation would go here
                "verification_hash": f"sha256:{verification_hash}",
            },
            "tokens_consumed": consumed_token_ids,
            "sync": {
                "state": "queued_locally",
                "queue_position": 0,
                "estimated_sync": "unknown (awaiting connectivity)",
            },
            "created_at": tx.created_at.isoformat(),
        }

    @classmethod
    async def generate_emergency_code(
        cls,
        db: AsyncSession,
        wallet_id: str,
        amount_cents: int,
    ) -> dict:
        """Generate a 16-digit one-time emergency payment code."""
        wallet = await db.get(Wallet, wallet_id)
        if not wallet:
            raise PaymentError("wallet_not_found", f"Wallet {wallet_id} not found")

        if wallet.offline_balance_cents < amount_cents:
            raise InsufficientFundsError(
                wallet.offline_balance_cents, amount_cents, "offline"
            )

        # Phase 1: Load available tokens that aren't already locked to an OTP
        token_result = await db.execute(
            select(OfflineToken).where(
                OfflineToken.wallet_id == wallet_id,
                OfflineToken.status == TokenStatus.MINTED,
                OfflineToken.otp_code.is_(None)
            )
        )
        db_tokens = list(token_result.scalars().all())

        # Simple greedy selection
        db_tokens.sort(key=lambda t: t.denomination_cents, reverse=True)
        selected = []
        collected = 0
        for t in db_tokens:
            if collected < amount_cents:
                selected.append(t)
                collected += t.denomination_cents

        if collected < amount_cents:
             raise InsufficientFundsError(
                collected,
                amount_cents,
                "offline",
            )
            
        import random
        # Generate 16 digit numeric code
        code = f"{random.randint(1000, 9999):04d}-{random.randint(1000, 9999):04d}-{random.randint(1000, 9999):04d}-{random.randint(1000, 9999):04d}"

        for token in selected:
            token.otp_code = code

        # Deduct from offline balance right away to prevent reuse
        wallet.offline_balance_cents -= sum(t.denomination_cents for t in selected)
        await db.flush()

        return {
            "otp_code": code,
            "amount_cents": amount_cents,
            "currency": wallet.currency,
            "tokens_consumed": [t.id for t in selected]
        }


class PaymentError(Exception):
    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message
        super().__init__(message)


class InsufficientFundsError(Exception):
    def __init__(self, available: int, required: int, mode: str):
        self.available = available
        self.required = required
        self.mode = mode
        super().__init__(
            f"Insufficient {mode} funds: have {available} cents, need {required} cents"
        )
