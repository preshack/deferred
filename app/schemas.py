"""Deferred API — Pydantic Request/Response Schemas.

Stripe-style response objects with `object` field, structured errors with
`how_to_fix` and `docs_link`, and full validation for all endpoints.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field, field_validator


# ─── Base & Errors ────────────────────────────────────────────────────────────


class ErrorResponse(BaseModel):
    """Structured API error with remediation guidance."""
    error: ErrorDetail


class ErrorDetail(BaseModel):
    type: str = Field(..., description="Error type category")
    code: str = Field(..., description="Machine-readable error code")
    message: str = Field(..., description="Human-readable description")
    how_to_fix: str = Field(..., description="Actionable fix instructions")
    docs_link: str = Field(..., description="Relevant documentation URL")
    param: Optional[str] = None
    request_id: Optional[str] = None


# ─── Wallet Schemas ───────────────────────────────────────────────────────────


class DeviceBinding(BaseModel):
    device_id: str = Field(..., min_length=1, max_length=64)
    attestation: str = Field(default="", description="Base64 attestation certificate")


class RecoveryConfiguration(BaseModel):
    shares_required: int = Field(default=3, ge=2, le=10)
    shares_total: int = Field(default=5, ge=3, le=20)

    @field_validator("shares_total")
    @classmethod
    def shares_total_gte_required(cls, v: int, info) -> int:
        if info.data.get("shares_required") and v < info.data["shares_required"]:
            raise ValueError("shares_total must be >= shares_required")
        return v


class WalletCreate(BaseModel):
    type: Literal["personal", "business"] = "personal"
    offline_allowance_cents: int = Field(..., gt=0, le=1_000_000)
    currency: str = Field(default="usd", pattern=r"^[a-z]{3}$")
    security_tier: Literal["hardware_se", "tee", "software"] = "software"
    customer_reference: str = Field(..., min_length=1, max_length=64)
    device_binding: Optional[DeviceBinding] = None
    recovery_configuration: RecoveryConfiguration = RecoveryConfiguration()


class WalletBalance(BaseModel):
    online_cents: int = 0
    offline_reserved_cents: int = 0
    offline_available_cents: int = 0
    pending_sync_cents: int = 0


class SyncStatusInfo(BaseModel):
    last_sync_at: Optional[datetime] = None
    pending_count: int = 0
    health_score: float = 1.0
    estimated_sync: Optional[datetime] = None


class OfflineTokenInfo(BaseModel):
    id: str
    denomination: int
    expiry: datetime


class OfflineTokenList(BaseModel):
    object: str = "list"
    data: List[OfflineTokenInfo] = []
    has_more: bool = False


class OfflineConfig(BaseModel):
    allowance_cents: int
    security_tier: str
    tokens_minted: int = 0
    tokens_pending: int = 0


class RecoveryInfo(BaseModel):
    status: str = "pending_backup"
    backup_url: Optional[str] = None


class KeysInfo(BaseModel):
    signing_key: str
    encryption_key: str


class SecurityInfo(BaseModel):
    tier: str
    last_attestation: Optional[datetime] = None
    device_integrity: str = "valid"


class WalletResponse(BaseModel):
    id: str
    object: str = "wallet"
    status: str
    master_public_key: str
    balances: WalletBalance
    offline_configuration: OfflineConfig
    recovery: RecoveryInfo
    keys: KeysInfo
    created_at: datetime

    model_config = {"from_attributes": True}


class WalletDetailResponse(WalletResponse):
    sync_status: SyncStatusInfo = SyncStatusInfo()
    offline_tokens: Optional[OfflineTokenList] = None
    security: SecurityInfo = SecurityInfo(tier="software")


# ─── TopUp Schemas ────────────────────────────────────────────────────────────


class TopUpSource(BaseModel):
    type: Literal["bank_account", "card", "crypto"] = "bank_account"
    id: str = Field(..., min_length=1, max_length=64)


class TopUpCreate(BaseModel):
    wallet_id: str = Field(..., min_length=1)
    amount_cents: int = Field(..., gt=0, le=10_000_000)
    currency: str = Field(default="usd", pattern=r"^[a-z]{3}$")
    source: TopUpSource
    offline_allocation_cents: int = Field(default=0, ge=0)
    metadata: Dict[str, Any] = Field(default_factory=dict)

    @field_validator("offline_allocation_cents")
    @classmethod
    def allocation_within_amount(cls, v: int, info) -> int:
        if info.data.get("amount_cents") and v > info.data["amount_cents"]:
            raise ValueError("offline_allocation_cents cannot exceed amount_cents")
        return v


class TopUpWalletInfo(BaseModel):
    id: str
    online_balance_cents: int
    offline_balance_cents: int


class TopUpSourceInfo(BaseModel):
    type: str
    last4: str


class TopUpResponse(BaseModel):
    id: str
    object: str = "topup"
    amount_cents: int
    offline_allocation_cents: int
    status: str
    source: TopUpSourceInfo
    wallet: TopUpWalletInfo
    expected_availability: Optional[datetime] = None
    metadata: Dict[str, Any] = {}

    model_config = {"from_attributes": True}


# ─── Payment Schemas ──────────────────────────────────────────────────────────


class PaymentCreate(BaseModel):
    amount_cents: int = Field(..., gt=0, le=10_000_000)
    currency: str = Field(default="usd", pattern=r"^[a-z]{3}$")
    wallet_id: str = Field(..., min_length=1)
    merchant_id: str = Field(..., min_length=1)
    description: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)


class OfflineProofInfo(BaseModel):
    expires_at: Optional[datetime] = None
    settlement_payload: str = ""
    qr_code: str = ""
    verification_hash: str = ""


class PaymentSyncInfo(BaseModel):
    state: str = "queued_locally"
    queue_position: int = 0
    estimated_sync: Optional[str] = "unknown (awaiting connectivity)"


class PaymentResponse(BaseModel):
    id: str
    object: str = "payment"
    amount_cents: int
    currency: str = "usd"
    status: str
    mode: str
    wallet_id: str
    merchant_id: str
    offline_proof: Optional[OfflineProofInfo] = None
    tokens_consumed: Optional[List[str]] = None
    sync: Optional[PaymentSyncInfo] = None
    created_at: datetime

    model_config = {"from_attributes": True}


# ─── Settlement Schemas ───────────────────────────────────────────────────────


class SettlementCreate(BaseModel):
    payment_proof: str = Field(..., min_length=1, description="Base64url encoded settlement payload")
    merchant_id: str = Field(..., min_length=1)
    device_id: str = Field(default="", max_length=64)
    acceptance_timestamp: Optional[datetime] = None


class PayoutInfo(BaseModel):
    destination: str = ""
    estimated_arrival: Optional[datetime] = None


class SettlementResponse(BaseModel):
    id: str
    object: str = "settlement"
    payment_id: str
    status: str
    amount_cents: int
    fee_cents: int
    net_cents: int
    guarantee_expires_at: Optional[datetime] = None
    funds_available_at: Optional[datetime] = None
    payout: PayoutInfo = PayoutInfo()

    model_config = {"from_attributes": True}


class EmergencySettlementCreate(BaseModel):
    merchant_id: str = Field(..., min_length=1)
    amount_cents: int = Field(..., gt=0)
    otp_code: str = Field(..., description="16-digit Emergency OTP Code")
    payee_wallet_id: Optional[str] = Field(default=None, description="Wallet ID to credit with net settlement amount")

class EmergencyPaymentCreate(BaseModel):
    wallet_id: str = Field(..., min_length=1)
    amount_cents: int = Field(..., gt=0)

# ─── Sync Schemas ─────────────────────────────────────────────────────────────


class SyncTrigger(BaseModel):
    wallet_id: Optional[str] = None
    batch_size: int = Field(default=10, ge=1, le=100)
    priority: Literal["normal", "high", "critical"] = "normal"


class SyncResultItem(BaseModel):
    payment_id: str
    status: str
    settlement_id: Optional[str] = None
    latency_ms: Optional[int] = None
    error: Optional[str] = None
    retryable: Optional[bool] = None


class SyncResponse(BaseModel):
    triggered_at: datetime
    processed: int
    results: List[SyncResultItem] = []


# ─── Auth Schemas ─────────────────────────────────────────────────────────────


class TokenRequest(BaseModel):
    customer_id: str = Field(..., min_length=1)
    secret: str = Field(..., min_length=1)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    refresh_token: str


class RefreshRequest(BaseModel):
    refresh_token: str = Field(..., min_length=1)


# ─── Health ───────────────────────────────────────────────────────────────────


class HealthResponse(BaseModel):
    status: str = "healthy"
    version: str = "1.0.0"
    services: Dict[str, str] = {}
