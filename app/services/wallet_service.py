"""Deferred API — Wallet Service.

Business logic for wallet creation, retrieval, and management.
Orchestrates crypto operations, database writes, and token minting.
"""

from __future__ import annotations

import base64
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.crypto.keys import HDKeyDerivation
from app.crypto.shamir import ShamirSecretSharing
from app.crypto.tokens import TokenManager
from app.models import (
    OfflineToken,
    SyncQueue,
    Transaction,
    Wallet,
    WalletStatus,
    TokenStatus,
    TxStatus,
    generate_prefixed_id,
)
from app.observability import SE_OPERATIONS, get_logger

logger = get_logger("wallet_service")


class WalletService:
    """Handles all wallet lifecycle operations."""

    # Global wallet counter for HD derivation index
    _wallet_counter = 0

    @classmethod
    async def create_wallet(
        cls,
        db: AsyncSession,
        customer_id: str,
        wallet_type: str,
        offline_allowance_cents: int,
        currency: str = "usd",
        security_tier: str = "software",
        device_id: Optional[str] = None,
        recovery_shares_required: int = 3,
        recovery_shares_total: int = 5,
    ) -> dict:
        """Create a new wallet with HD key generation and optional token pre-minting.

        Steps:
        1. Check customer wallet limit (max 10)
        2. Generate master seed and derive keypairs (BIP-32)
        3. Split seed via Shamir's Secret Sharing
        4. Create wallet record
        5. Queue initial token batch minting

        Returns:
            Wallet response dict matching the API spec
        """
        # 1. Check wallet limit
        count_result = await db.execute(
            select(func.count()).where(
                Wallet.customer_id == customer_id,
                Wallet.status != WalletStatus.CLOSED,
            )
        )
        wallet_count = count_result.scalar() or 0
        if wallet_count >= 10:
            raise WalletLimitError(customer_id)

        # 2. Generate master seed and derive keys
        cls._wallet_counter += 1
        hd = HDKeyDerivation()
        master_public_key = hd.get_master_public_key()

        # Derive signing and encryption keypairs
        signing_key = hd.derive_path(f"m/44'/666'/{cls._wallet_counter}'/0'/0/0")
        encryption_key = hd.derive_path(f"m/44'/666'/{cls._wallet_counter}'/0'/1/0")

        SE_OPERATIONS.labels(operation="key_generation").inc(2)

        # 3. Shamir's Secret Sharing
        shares = ShamirSecretSharing.split(
            hd.master_seed,
            k=recovery_shares_required,
            n=recovery_shares_total,
        )

        SE_OPERATIONS.labels(operation="shamir_split").inc()

        # 4. Create wallet record
        wallet_id = generate_prefixed_id("wallet")
        wallet = Wallet(
            id=wallet_id,
            customer_id=customer_id,
            type=wallet_type,
            master_public_key=master_public_key,
            online_balance_cents=0,
            offline_balance_cents=0,
            offline_allowance_cents=offline_allowance_cents,
            currency=currency,
            security_tier=security_tier,
            status=WalletStatus.ACTIVE,
            device_id=device_id,
            recovery_shares_required=recovery_shares_required,
            recovery_shares_total=recovery_shares_total,
            signing_public_key=signing_key.public_key_bytes,
            encryption_public_key=encryption_key.public_key_bytes,
        )

        db.add(wallet)
        await db.flush()

        logger.info(
            "wallet_created",
            wallet_id=wallet_id,
            customer_id=customer_id,
            security_tier=security_tier,
            offline_allowance_cents=offline_allowance_cents,
        )

        # 5. Build response
        return {
            "id": wallet_id,
            "object": "wallet",
            "status": wallet.status.value,
            "master_public_key": base64.b64encode(master_public_key).decode(),
            "balances": {
                "online_cents": 0,
                "offline_reserved_cents": 0,
                "offline_available_cents": 0,
                "pending_sync_cents": 0,
            },
            "offline_configuration": {
                "allowance_cents": offline_allowance_cents,
                "security_tier": security_tier,
                "tokens_minted": 0,
                "tokens_pending": 0,
            },
            "recovery": {
                "status": "pending_backup",
                "backup_url": f"https://deferred.dev/recovery/{wallet_id}",
            },
            "keys": {
                "signing_key": base64.b64encode(signing_key.public_key_bytes).decode(),
                "encryption_key": base64.b64encode(encryption_key.public_key_bytes).decode(),
            },
            "created_at": wallet.created_at.isoformat(),
        }

    @classmethod
    async def get_wallet(
        cls,
        db: AsyncSession,
        wallet_id: str,
        include_pending: bool = True,
        expand: list[str] | None = None,
    ) -> dict:
        """Retrieve wallet state with optional expansions.

        Steps:
        1. Fetch wallet
        2. Calculate sync health score
        3. Optionally expand tokens and recent transactions

        Returns:
            Wallet detail response dict
        """
        wallet = await db.get(Wallet, wallet_id)
        if not wallet:
            raise WalletNotFoundError(wallet_id)

        expand = expand or []

        # Calculate pending sync count and amount
        pending_result = await db.execute(
            select(
                func.count().label("count"),
                func.coalesce(func.sum(Transaction.amount_cents), 0).label("amount"),
            ).where(
                Transaction.wallet_id == wallet_id,
                Transaction.status == TxStatus.PENDING,
            )
        )
        pending = pending_result.first()
        pending_count = pending.count if pending else 0
        pending_cents = pending.amount if pending else 0

        # Sync health score
        health_score = 1.0
        if pending_count > 0:
            health_score = max(0.0, 1.0 - (pending_count * 0.02))

        # Token stats
        token_result = await db.execute(
            select(func.count()).where(
                OfflineToken.wallet_id == wallet_id,
                OfflineToken.status == TokenStatus.MINTED,
            )
        )
        tokens_minted = token_result.scalar() or 0

        # Build response
        response = {
            "id": wallet.id,
            "object": "wallet",
            "status": wallet.status.value,
            "master_public_key": base64.b64encode(wallet.master_public_key).decode(),
            "balances": {
                "online_cents": wallet.online_balance_cents,
                "offline_reserved_cents": wallet.offline_balance_cents,
                "offline_available_cents": wallet.offline_balance_cents,
                "pending_sync_cents": pending_cents,
            },
            "sync_status": {
                "last_sync_at": None,
                "pending_count": pending_count,
                "health_score": round(health_score, 2),
                "estimated_sync": None,
            },
            "offline_configuration": {
                "allowance_cents": wallet.offline_allowance_cents,
                "security_tier": wallet.security_tier.value if wallet.security_tier else "software",
                "tokens_minted": tokens_minted,
                "tokens_pending": 0,
            },
            "recovery": {
                "status": wallet.recovery_status,
                "backup_url": f"https://deferred.dev/recovery/{wallet.id}",
            },
            "keys": {
                "signing_key": base64.b64encode(wallet.signing_public_key).decode() if wallet.signing_public_key else "",
                "encryption_key": base64.b64encode(wallet.encryption_public_key).decode() if wallet.encryption_public_key else "",
            },
            "security": {
                "tier": wallet.security_tier.value if wallet.security_tier else "software",
                "last_attestation": None,
                "device_integrity": "valid",
            },
            "created_at": wallet.created_at.isoformat(),
        }

        # Expand tokens
        if "tokens" in expand:
            tokens = await db.execute(
                select(OfflineToken)
                .where(
                    OfflineToken.wallet_id == wallet_id,
                    OfflineToken.status == TokenStatus.MINTED,
                )
                .limit(50)
            )
            token_list = tokens.scalars().all()
            response["offline_tokens"] = {
                "object": "list",
                "data": [
                    {
                        "id": t.id,
                        "denomination": t.denomination_cents,
                        "expiry": t.expiry_time.isoformat(),
                    }
                    for t in token_list
                ],
                "has_more": len(token_list) >= 50,
            }

        return response


class WalletLimitError(Exception):
    def __init__(self, customer_id: str):
        self.customer_id = customer_id
        super().__init__(f"Customer {customer_id} has reached the maximum wallet limit (10)")


class WalletNotFoundError(Exception):
    def __init__(self, wallet_id: str):
        self.wallet_id = wallet_id
        super().__init__(f"Wallet {wallet_id} not found")
