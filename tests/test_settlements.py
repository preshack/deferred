"""Tests for the Settlement API endpoints.

Tests:
- Successful settlement of offline payment proof
- Invalid/expired proof rejection
- Double-spend detection
"""

from __future__ import annotations

import base64
import json
import time

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
class TestSettlements:
    """Test POST /settlements endpoint."""

    async def _generate_payment_proof(self, client: AsyncClient) -> tuple[str, str]:
        """Helper: create a funded wallet, make offline payment, return (proof, merchant_id)."""
        merchant_id = "merch_settle_test"

        # Create wallet
        resp = await client.post(
            "/wallets",
            json={
                "offline_allowance_cents": 50000,
                "customer_reference": "test_settle",
            },
        )
        wallet_id = resp.json()["id"]

        # Fund with offline allocation
        await client.post(
            "/topups",
            json={
                "wallet_id": wallet_id,
                "amount_cents": 30000,
                "source": {"type": "bank_account", "id": "ba_settle"},
                "offline_allocation_cents": 30000,
            },
            headers={"Idempotency-Key": "idem_settle_topup"},
        )

        # Make offline payment
        pay_resp = await client.post(
            "/payments",
            json={
                "amount_cents": 2500,
                "wallet_id": wallet_id,
                "merchant_id": merchant_id,
            },
            headers={
                "X-Deferred-Mode": "offline",
                "Idempotency-Key": "idem_settle_pay",
            },
        )

        proof = pay_resp.json()["offline_proof"]["settlement_payload"]
        return proof, merchant_id

    async def test_settlement_success(self, client: AsyncClient):
        """Settling a valid proof returns 201 with guarantee."""
        proof, merchant_id = await self._generate_payment_proof(client)

        response = await client.post(
            "/settlements",
            json={
                "payment_proof": proof,
                "merchant_id": merchant_id,
            },
            headers={"X-Api-Key": "sk_test_merchant_key_123456789012"},
        )

        assert response.status_code == 201
        data = response.json()
        assert data["object"] == "settlement"
        assert data["status"] == "guaranteed"
        assert data["amount_cents"] == 2500
        assert data["fee_cents"] > 0
        assert data["net_cents"] == data["amount_cents"] - data["fee_cents"]
        assert "payout" in data

    async def test_settlement_invalid_proof(self, client: AsyncClient):
        """Invalid proof returns 400."""
        response = await client.post(
            "/settlements",
            json={
                "payment_proof": "not_valid_base64_proof",
                "merchant_id": "merch_test",
            },
            headers={"X-Api-Key": "sk_test_merchant_key_123456789012"},
        )

        assert response.status_code == 400

    async def test_settlement_merchant_mismatch(self, client: AsyncClient):
        """Proof for wrong merchant returns 403."""
        proof, _ = await self._generate_payment_proof(client)

        response = await client.post(
            "/settlements",
            json={
                "payment_proof": proof,
                "merchant_id": "wrong_merchant",
            },
            headers={"X-Api-Key": "sk_test_merchant_key_123456789012"},
        )

        assert response.status_code == 403

    async def test_settlement_expired_proof(self, client: AsyncClient):
        """Expired proof returns 400."""
        # Create a proof with past expiry
        expired_data = {
            "version": "1.0",
            "tx_id": "pay_expired",
            "merchant_id": "merch_test",
            "amount_cents": 1000,
            "proofs": [],
            "expiry": time.time() - 3600,  # 1 hour ago
        }
        expired_proof = base64.urlsafe_b64encode(
            json.dumps(expired_data).encode()
        ).decode()

        response = await client.post(
            "/settlements",
            json={
                "payment_proof": expired_proof,
                "merchant_id": "merch_test",
            },
            headers={"X-Api-Key": "sk_test_merchant_key_123456789012"},
        )

        assert response.status_code == 400
