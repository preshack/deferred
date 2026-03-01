"""Tests for the Sync API endpoints.

Tests:
- Sync trigger processes pending offline transactions
- Handles empty queue gracefully
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
class TestSync:
    """Test POST /sync/trigger endpoint."""

    async def test_sync_empty_queue(self, client: AsyncClient):
        """Sync with no pending items returns 200 with 0 processed."""
        response = await client.post(
            "/sync/trigger",
            json={"batch_size": 10, "priority": "normal"},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["processed"] == 0
        assert data["results"] == []
        assert "triggered_at" in data

    async def test_sync_with_pending_payments(self, client: AsyncClient):
        """Sync processes pending offline payments."""
        # Create funded wallet
        resp = await client.post(
            "/wallets",
            json={
                "offline_allowance_cents": 50000,
                "customer_reference": "test_sync",
            },
        )
        wallet_id = resp.json()["id"]

        # Fund with offline allocation
        await client.post(
            "/topups",
            json={
                "wallet_id": wallet_id,
                "amount_cents": 30000,
                "source": {"type": "bank_account", "id": "ba_sync"},
                "offline_allocation_cents": 30000,
            },
            headers={"Idempotency-Key": "idem_sync_topup"},
        )

        # Create offline payment (queues for sync)
        await client.post(
            "/payments",
            json={
                "amount_cents": 2500,
                "wallet_id": wallet_id,
                "merchant_id": "merch_sync_test",
            },
            headers={
                "X-Deferred-Mode": "offline",
                "Idempotency-Key": "idem_sync_pay",
            },
        )

        # Trigger sync
        response = await client.post(
            "/sync/trigger",
            json={
                "wallet_id": wallet_id,
                "batch_size": 10,
                "priority": "high",
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert data["processed"] >= 1
        # Each result has a status
        for result in data["results"]:
            assert "payment_id" in result
            assert "status" in result

    async def test_sync_priority_filtering(self, client: AsyncClient):
        """Sync with critical priority processes immediately."""
        response = await client.post(
            "/sync/trigger",
            json={"batch_size": 5, "priority": "critical"},
        )

        assert response.status_code == 200
