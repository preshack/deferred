import urllib.request
import json
import uuid
import random

API_URL = "http://localhost:8000"

def create_user(name):
    print(f"Creating user {name}...")
    # 1. Generate JWT
    customer_id = f"{name}_demo_{random.randint(1000, 9999)}"
    req = urllib.request.Request(
        f"{API_URL}/auth/token",
        data=json.dumps({"customer_id": customer_id, "secret": "test_secret"}).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST"
    )
    with urllib.request.urlopen(req) as response:
        resp_data = json.loads(response.read().decode())
        jwt = resp_data["access_token"]

    # 2. Create Wallet
    wallet_body = {
        "type": "personal",
        "offline_allowance_cents": 10000,
        "customer_reference": f"{name}_ref_{random.randint(1000, 9999)}"
    }
    req2 = urllib.request.Request(
        f"{API_URL}/wallets",
        data=json.dumps(wallet_body).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {jwt}",
            "Idempotency-Key": str(uuid.uuid4()),
            "Content-Type": "application/json"
        },
        method="POST"
    )
    with urllib.request.urlopen(req2) as response2:
        resp_data2 = json.loads(response2.read().decode())
        wallet_id = resp_data2["id"]

    return jwt, wallet_id

try:
    alice_jwt, alice_wallet = create_user("alice")
    bob_jwt, bob_wallet = create_user("bob")

    env_content = f"""ALICE_JWT={alice_jwt}
ALICE_WALLET_ID={alice_wallet}
BOB_JWT={bob_jwt}
BOB_WALLET_ID={bob_wallet}
"""

    with open("demo_creds.env", "w") as f:
        f.write(env_content)

    print("\nSuccessfully generated credentials and saved to demo_creds.env!")
    print(f"Alice Wallet: {alice_wallet}")
    print(f"Bob Wallet: {bob_wallet}")
except Exception as e:
    print(f"Error: {e}")
