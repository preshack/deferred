"""Tests for the Payment API endpoints.

Tests:
- Online payment creation and balance deduction
- Offline payment with proof generation
- Insufficient funds handling
- Payment mode validation
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
class TestOnlinePayments:
    """Test POST /payments in online mode."""

    async def _create_funded_wallet(self, client: AsyncClient) -> str:
        """Helper: create a wallet and fund it."""
        # Create wallet
        resp = await client.post(
            "/wallets",
            json={
                "offline_allowance_cents": 50000,
                "customer_reference": "test_payment",
            },
        )
        wallet_id = resp.json()["id"]

        # Fund it
        await client.post(
            "/topups",
            json={
                "wallet_id": wallet_id,
                "amount_cents": 100000,
                "source": {"type": "bank_account", "id": "ba_test1234"},
                "offline_allocation_cents": 0,
            },
            headers={"Idempotency-Key": "idem_topup_test"},
        )

        return wallet_id

    async def test_online_payment_success(self, client: AsyncClient):
        """Online payment deducts from online balance and returns 201."""
        wallet_id = await self._create_funded_wallet(client)

        response = await client.post(
            "/payments",
            json={
                "amount_cents": 2500,
                "wallet_id": wallet_id,
                "merchant_id": "merch_test",
                "description": "Test payment",
            },
            headers={
                "X-Deferred-Mode": "online",
                "Idempotency-Key": "idem_pay_test",
            },
        )

        assert response.status_code == 201
        data = response.json()
        assert data["status"] == "succeeded"
        assert data["mode"] == "online"
        assert data["amount_cents"] == 2500

    async def test_insufficient_online_funds(self, client: AsyncClient):
        """Payment exceeding balance returns 402."""
        # Create unfunded wallet
        resp = await client.post(
            "/wallets",
            json={
                "offline_allowance_cents": 10000,
                "customer_reference": "test_broke",
            },
        )
        wallet_id = resp.json()["id"]

        response = await client.post(
            "/payments",
            json={
                "amount_cents": 10000,
                "wallet_id": wallet_id,
                "merchant_id": "merch_test",
            },
            headers={"X-Deferred-Mode": "online"},
        )

        assert response.status_code == 402
        data = response.json()
        assert data["detail"]["error"]["code"] == "insufficient_funds"
        assert "how_to_fix" in data["detail"]["error"]


@pytest.mark.asyncio
class TestOfflinePayments:
    """Test POST /payments in offline mode."""

    async def _create_funded_offline_wallet(self, client: AsyncClient) -> str:
        """Helper: create wallet with offline tokens."""
        resp = await client.post(
            "/wallets",
            json={
                "offline_allowance_cents": 50000,
                "customer_reference": "test_offline",
            },
        )
        wallet_id = resp.json()["id"]

        # Fund with offline allocation (mints tokens)
        await client.post(
            "/topups",
            json={
                "wallet_id": wallet_id,
                "amount_cents": 30000,
                "source": {"type": "bank_account", "id": "ba_test5678"},
                "offline_allocation_cents": 30000,
            },
            headers={"Idempotency-Key": "idem_offline_topup"},
        )

        return wallet_id

    async def test_offline_payment_returns_202(self, client: AsyncClient):
        """Offline payment returns 202 with proof."""
        wallet_id = await self._create_funded_offline_wallet(client)

        response = await client.post(
            "/payments",
            json={
                "amount_cents": 2500,
                "wallet_id": wallet_id,
                "merchant_id": "merch_coffee",
                "description": "Coffee and pastry",
            },
            headers={
                "X-Deferred-Mode": "offline",
                "Idempotency-Key": "idem_offline_pay",
            },
        )

        assert response.status_code == 202
        data = response.json()
        assert data["status"] == "pending_sync"
        assert data["mode"] == "offline"
        assert "offline_proof" in data
        assert "settlement_payload" in data["offline_proof"]
        assert "tokens_consumed" in data
        assert len(data["tokens_consumed"]) > 0

    async def test_offline_insufficient_funds(self, client: AsyncClient):
        """Offline payment with insufficient tokens returns 402."""
        # Create wallet with no offline allocation
        resp = await client.post(
            "/wallets",
            json={
                "offline_allowance_cents": 10000,
                "customer_reference": "test_no_offline",
            },
        )
        wallet_id = resp.json()["id"]

        response = await client.post(
            "/payments",
            json={
                "amount_cents": 1000,
                "wallet_id": wallet_id,
                "merchant_id": "merch_test",
            },
            headers={"X-Deferred-Mode": "offline"},
        )

        assert response.status_code == 402

    async def test_invalid_mode_returns_400(self, client: AsyncClient):
        """Invalid X-Deferred-Mode returns 400."""
        response = await client.post(
            "/payments",
            json={
                "amount_cents": 1000,
                "wallet_id": "wallet_test",
                "merchant_id": "merch_test",
            },
            headers={"X-Deferred-Mode": "invalid_mode"},
        )

        assert response.status_code == 400
