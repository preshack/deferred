"""Deferred API — SQLAlchemy ORM Models.

All core entities: Wallet, OfflineToken, Transaction, Settlement, TopUp,
GlobalSpend, SyncQueue, IdempotencyStore.
"""

from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    JSON,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import relationship

from app.db import Base


def generate_prefixed_id(prefix: str, length: int = 12) -> str:
    """Generate a prefixed ID like 'wallet_2vXKrKf47CM8M'."""
    charset = "23456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
    random_part = "".join(secrets.choice(charset) for _ in range(length))
    return f"{prefix}_{random_part}"


# ─── Enums ────────────────────────────────────────────────────────────────────

import enum


class WalletStatus(str, enum.Enum):
    PROVISIONING = "provisioning"
    ACTIVE = "active"
    FROZEN = "frozen"
    CLOSED = "closed"


class WalletType(str, enum.Enum):
    PERSONAL = "personal"
    BUSINESS = "business"


class SecurityTier(str, enum.Enum):
    HARDWARE_SE = "hardware_se"
    TEE = "tee"
    SOFTWARE = "software"


class TokenStatus(str, enum.Enum):
    MINTED = "minted"
    SPENT = "spent"
    SETTLED = "settled"
    REVOKED = "revoked"


class TxMode(str, enum.Enum):
    ONLINE = "online"
    OFFLINE = "offline"
    HYBRID = "hybrid"


class TxStatus(str, enum.Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class SyncStatus(str, enum.Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class SettlementStatus(str, enum.Enum):
    PENDING_VALIDATION = "pending_validation"
    GUARANTEED = "guaranteed"
    SETTLED = "settled"
    DISPUTED = "disputed"
    CHARGED_BACK = "charged_back"


class TopUpStatus(str, enum.Enum):
    PROCESSING = "processing"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


# ─── Models ───────────────────────────────────────────────────────────────────


class Wallet(Base):
    __tablename__ = "wallets"

    id = Column(String(32), primary_key=True, default=lambda: generate_prefixed_id("wallet"))
    customer_id = Column(String(32), nullable=False, index=True)
    type = Column(Enum(WalletType), nullable=False, default=WalletType.PERSONAL)
    master_public_key = Column(LargeBinary, nullable=False)
    online_balance_cents = Column(BigInteger, default=0)
    offline_balance_cents = Column(BigInteger, default=0)
    offline_allowance_cents = Column(BigInteger, nullable=False)
    currency = Column(String(3), default="usd")
    security_tier = Column(Enum(SecurityTier), default=SecurityTier.SOFTWARE)
    status = Column(Enum(WalletStatus), default=WalletStatus.ACTIVE)
    device_id = Column(String(64), nullable=True)
    recovery_shares_required = Column(Integer, default=3)
    recovery_shares_total = Column(Integer, default=5)
    recovery_status = Column(String(32), default="pending_backup")
    signing_public_key = Column(LargeBinary, nullable=True)
    encryption_public_key = Column(LargeBinary, nullable=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc),
                        onupdate=lambda: datetime.now(timezone.utc))
    metadata_ = Column("metadata", JSON, default=dict)

    # Relationships
    tokens = relationship("OfflineToken", back_populates="wallet", lazy="selectin")
    transactions = relationship("Transaction", back_populates="wallet", lazy="selectin")
    topups = relationship("TopUp", back_populates="wallet", lazy="selectin")

    __table_args__ = (
        CheckConstraint("online_balance_cents >= 0", name="ck_online_balance_positive"),
        CheckConstraint("offline_balance_cents >= 0", name="ck_offline_balance_positive"),
        CheckConstraint("offline_allowance_cents > 0", name="ck_allowance_positive"),
        CheckConstraint(
            "offline_balance_cents <= offline_allowance_cents",
            name="ck_offline_within_allowance",
        ),
    )


class OfflineToken(Base):
    __tablename__ = "offline_tokens"

    id = Column(String(32), primary_key=True, default=lambda: generate_prefixed_id("tok"))
    wallet_id = Column(String(32), ForeignKey("wallets.id", ondelete="CASCADE"), nullable=False)
    denomination_cents = Column(Integer, nullable=False)
    public_key = Column(LargeBinary, nullable=False)
    private_key_encrypted = Column(LargeBinary, nullable=True)  # Encrypted, SE-managed in prod
    parent_token_id = Column(String(32), ForeignKey("offline_tokens.id"), nullable=True)
    ancestry_chain = Column(JSON, nullable=False, default=list)
    issuance_time = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    expiry_time = Column(DateTime(timezone=True), nullable=False,
                         default=lambda: datetime.now(timezone.utc) + timedelta(days=30))
    status = Column(Enum(TokenStatus), default=TokenStatus.MINTED)
    spent_in_tx = Column(String(32), nullable=True)
    spent_at = Column(DateTime(timezone=True), nullable=True)
    destruction_proof = Column(LargeBinary, nullable=True)
    otp_code = Column(String(50), nullable=True)  # Format: XXXX-XXXX-XXXX-XXXX (or SPENT_XXXX-XXXX-XXXX-XXXX after settlement)

    # Relationships
    wallet = relationship("Wallet", back_populates="tokens")

    __table_args__ = (
        CheckConstraint(
            "denomination_cents IN (500, 1000, 2000, 5000, 10000)",
            name="ck_valid_denomination",
        ),
        Index("idx_tokens_wallet_status", "wallet_id", "status"),
        Index("idx_tokens_expiry", "expiry_time"),
    )


class GlobalSpend(Base):
    __tablename__ = "global_spends"

    token_id = Column(String(32), ForeignKey("offline_tokens.id"), primary_key=True)
    tx_id = Column(String(32), nullable=False)
    spent_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    merkle_root = Column(String(64), nullable=True)
    settlement_id = Column(String(32), nullable=True)


class Transaction(Base):
    __tablename__ = "transactions"

    id = Column(String(32), primary_key=True, default=lambda: generate_prefixed_id("pay"))
    wallet_id = Column(String(32), ForeignKey("wallets.id"), nullable=False)
    merchant_id = Column(String(32), nullable=True)
    mode = Column(Enum(TxMode), nullable=False)
    status = Column(Enum(TxStatus), default=TxStatus.PENDING)
    amount_cents = Column(BigInteger, nullable=False)
    currency = Column(String(3), default="usd")
    description = Column(Text, nullable=True)
    idempotency_key = Column(String(64), unique=True, nullable=True)
    offline_proof = Column(JSON, nullable=True)
    tokens_consumed = Column(JSON, nullable=True)
    error_code = Column(String(50), nullable=True)
    error_message = Column(Text, nullable=True)
    settled_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc),
                        onupdate=lambda: datetime.now(timezone.utc))
    metadata_ = Column("metadata", JSON, default=dict)

    # Relationships
    wallet = relationship("Wallet", back_populates="transactions")

    __table_args__ = (
        CheckConstraint("amount_cents > 0", name="ck_tx_amount_positive"),
        Index("idx_txs_wallet_created", "wallet_id", "created_at"),
        Index("idx_txs_status", "status"),
    )


class Settlement(Base):
    __tablename__ = "settlements"

    id = Column(String(32), primary_key=True, default=lambda: generate_prefixed_id("stl"))
    payment_id = Column(String(32), ForeignKey("transactions.id"), nullable=False)
    merchant_id = Column(String(32), nullable=False)
    status = Column(Enum(SettlementStatus), default=SettlementStatus.PENDING_VALIDATION)
    amount_cents = Column(BigInteger, nullable=False)
    fee_cents = Column(BigInteger, default=0)
    net_cents = Column(BigInteger, nullable=False)
    guarantee_expires_at = Column(DateTime(timezone=True), nullable=True)
    funds_available_at = Column(DateTime(timezone=True), nullable=True)
    payout_destination = Column(String(128), nullable=True)
    payout_estimated_arrival = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc),
                        onupdate=lambda: datetime.now(timezone.utc))


class TopUp(Base):
    __tablename__ = "topups"

    id = Column(String(32), primary_key=True, default=lambda: generate_prefixed_id("topup"))
    wallet_id = Column(String(32), ForeignKey("wallets.id"), nullable=False)
    amount_cents = Column(BigInteger, nullable=False)
    offline_allocation_cents = Column(BigInteger, default=0)
    currency = Column(String(3), default="usd")
    status = Column(Enum(TopUpStatus), default=TopUpStatus.PROCESSING)
    source_type = Column(String(32), nullable=False)
    source_id = Column(String(64), nullable=False)
    source_last4 = Column(String(4), nullable=True)
    idempotency_key = Column(String(64), unique=True, nullable=True)
    expected_availability = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc),
                        onupdate=lambda: datetime.now(timezone.utc))
    metadata_ = Column("metadata", JSON, default=dict)

    # Relationships
    wallet = relationship("Wallet", back_populates="topups")

    __table_args__ = (
        CheckConstraint("amount_cents > 0", name="ck_topup_amount_positive"),
    )


class SyncQueue(Base):
    __tablename__ = "sync_queue"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    tx_id = Column(String(32), ForeignKey("transactions.id"), unique=True, nullable=False)
    priority = Column(Integer, default=5)
    status = Column(Enum(SyncStatus), default=SyncStatus.PENDING)
    attempts = Column(Integer, default=0)
    next_retry_at = Column(DateTime(timezone=True), nullable=True)
    error_log = Column(JSON, default=list)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    __table_args__ = (
        CheckConstraint("priority BETWEEN 1 AND 10", name="ck_sync_priority_range"),
        Index("idx_sync_status_retry", "status", "next_retry_at"),
    )


class IdempotencyStore(Base):
    __tablename__ = "idempotency_store"

    key = Column(String(64), primary_key=True)
    request_hash = Column(String(64), nullable=False)
    response = Column(JSON, nullable=False)
    status_code = Column(Integer, nullable=False, default=200)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    expires_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc) + timedelta(hours=24),
    )
