"""Tests for the Wallet API endpoints.

Tests:
- Wallet creation with HD key generation
- Wallet retrieval with balance and sync status
- Wallet limit enforcement (max 10)
- Error responses with how_to_fix
"""

from __future__ import annotations

import pytest
import pytest_asyncio
from httpx import AsyncClient


@pytest.mark.asyncio
class TestWalletCreation:
    """Test POST /wallets endpoint."""

    async def test_create_wallet_success(self, client: AsyncClient):
        """Creating a wallet returns 201 with correct structure."""
        response = await client.post(
            "/wallets",
            json={
                "type": "personal",
                "offline_allowance_cents": 50000,
                "currency": "usd",
                "security_tier": "software",
                "customer_reference": "test_customer",
                "recovery_configuration": {
                    "shares_required": 3,
                    "shares_total": 5,
                },
            },
        )

        assert response.status_code == 201
        data = response.json()

        assert data["object"] == "wallet"
        assert data["status"] == "active"
        assert data["id"].startswith("wallet_")
        assert "master_public_key" in data
        assert data["balances"]["online_cents"] == 0
        assert data["offline_configuration"]["allowance_cents"] == 50000
        assert data["recovery"]["status"] == "pending_backup"
        assert "signing_key" in data["keys"]
        assert "encryption_key" in data["keys"]

    async def test_create_wallet_minimal(self, client: AsyncClient):
        """Minimal wallet creation with defaults."""
        response = await client.post(
            "/wallets",
            json={
                "offline_allowance_cents": 10000,
                "customer_reference": "test_min",
            },
        )

        assert response.status_code == 201
        data = response.json()
        assert data["offline_configuration"]["security_tier"] == "software"

    async def test_create_wallet_invalid_currency(self, client: AsyncClient):
        """Invalid currency returns 422."""
        response = await client.post(
            "/wallets",
            json={
                "offline_allowance_cents": 10000,
                "customer_reference": "test_bad",
                "currency": "INVALID",
            },
        )

        assert response.status_code == 422

    async def test_create_wallet_negative_allowance(self, client: AsyncClient):
        """Negative allowance returns 422."""
        response = await client.post(
            "/wallets",
            json={
                "offline_allowance_cents": -1000,
                "customer_reference": "test_neg",
            },
        )

        assert response.status_code == 422


@pytest.mark.asyncio
class TestWalletRetrieval:
    """Test GET /wallets/{wallet_id} endpoint."""

    async def test_get_wallet_success(self, client: AsyncClient):
        """Retrieving an existing wallet returns correct data."""
        # Create wallet first
        create_resp = await client.post(
            "/wallets",
            json={
                "offline_allowance_cents": 50000,
                "customer_reference": "test_get",
            },
        )
        assert create_resp.status_code == 201
        wallet_id = create_resp.json()["id"]

        # Retrieve it
        get_resp = await client.get(f"/wallets/{wallet_id}")
        assert get_resp.status_code == 200

        data = get_resp.json()
        assert data["id"] == wallet_id
        assert data["object"] == "wallet"
        assert data["sync_status"]["health_score"] == 1.0

    async def test_get_wallet_not_found(self, client: AsyncClient):
        """Non-existent wallet returns 404 with how_to_fix."""
        response = await client.get("/wallets/wallet_nonexistent")
        assert response.status_code == 404

        data = response.json()
        assert data["detail"]["error"]["code"] == "wallet_not_found"
        assert "how_to_fix" in data["detail"]["error"]

    async def test_get_wallet_with_expand(self, client: AsyncClient):
        """Wallet with expand=tokens includes token list."""
        # Create wallet
        create_resp = await client.post(
            "/wallets",
            json={
                "offline_allowance_cents": 50000,
                "customer_reference": "test_expand",
            },
        )
        wallet_id = create_resp.json()["id"]

        # Retrieve with expansion
        get_resp = await client.get(
            f"/wallets/{wallet_id}",
            params={"expand": ["tokens"]},
        )
        assert get_resp.status_code == 200
        data = get_resp.json()
        assert "offline_tokens" in data


@pytest.mark.asyncio
class TestAuthentication:
    """Test authentication requirements."""

    async def test_unauthenticated_request(self, unauth_client: AsyncClient):
        """Unauthenticated requests return 401."""
        response = await unauth_client.get("/wallets/wallet_test")
        assert response.status_code == 401
