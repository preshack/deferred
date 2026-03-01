"""Deferred API — Load Test (Locust).

Run: locust -f locustfile.py --host=http://localhost:8000

Simulates a realistic mix of:
- 60% online payments
- 30% offline payments
- 10% wallet operations
"""

from locust import HttpUser, task, between, events


class DeferredUser(HttpUser):
    """Simulates a Deferred API user with mixed operation patterns."""

    wait_time = between(1, 5)

    def on_start(self):
        """Authenticate and create a funded wallet."""
        # Get auth token
        resp = self.client.post(
            "/auth/token",
            json={"customer_id": f"load_test_user_{self.environment.runner.user_count}", "secret": "test_secret"},
        )
        if resp.status_code == 200:
            token = resp.json()["access_token"]
            self.client.headers["Authorization"] = f"Bearer {token}"

        # Create wallet
        resp = self.client.post(
            "/wallets",
            json={
                "offline_allowance_cents": 500000,
                "customer_reference": f"load_user_{self.environment.runner.user_count}",
                "security_tier": "software",
            },
        )
        if resp.status_code == 201:
            self.wallet_id = resp.json()["id"]

            # Fund wallet (online + offline)
            self.client.post(
                "/topups",
                json={
                    "wallet_id": self.wallet_id,
                    "amount_cents": 1000000,
                    "source": {"type": "bank_account", "id": "ba_load_test"},
                    "offline_allocation_cents": 300000,
                },
                headers={"Idempotency-Key": f"load_topup_{self.wallet_id}"},
            )
        else:
            self.wallet_id = None

    @task(6)
    def online_payment(self):
        """Make an online payment (60% of traffic)."""
        if not self.wallet_id:
            return

        import uuid
        self.client.post(
            "/payments",
            json={
                "amount_cents": 1000,
                "wallet_id": self.wallet_id,
                "merchant_id": "merch_load_test",
                "description": "Load test payment",
            },
            headers={
                "X-Deferred-Mode": "online",
                "Idempotency-Key": str(uuid.uuid4()),
            },
        )

    @task(3)
    def offline_payment(self):
        """Make an offline payment (30% of traffic)."""
        if not self.wallet_id:
            return

        import uuid
        self.client.post(
            "/payments",
            json={
                "amount_cents": 500,
                "wallet_id": self.wallet_id,
                "merchant_id": "merch_load_test",
                "description": "Offline load test",
            },
            headers={
                "X-Deferred-Mode": "offline",
                "Idempotency-Key": str(uuid.uuid4()),
            },
        )

    @task(1)
    def check_wallet(self):
        """Check wallet balance (10% of traffic)."""
        if not self.wallet_id:
            return

        self.client.get(f"/wallets/{self.wallet_id}")
