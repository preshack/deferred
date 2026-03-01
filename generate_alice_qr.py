import os
import urllib.request
import urllib.parse
import json
import uuid
import sys
import subprocess
import ssl

API_URL = "http://localhost:8000"
CRED_FILE = "demo_creds.env"

def main():
    if not os.path.exists(CRED_FILE):
        print(f"Error: {CRED_FILE} not found. Please run setup_creds.py first.")
        sys.exit(1)

    with open(CRED_FILE, "r") as f:
        creds = {}
        for line in f:
            if "=" in line:
                k, v = line.strip().split("=", 1)
                creds[k] = v

    alice_jwt = creds.get("ALICE_JWT")
    alice_wallet_id = creds.get("ALICE_WALLET_ID")

    if not alice_jwt or not alice_wallet_id:
        print("Error: Alice credentials missing.")
        sys.exit(1)

    # Check Alice's current offline balance first
    req_check = urllib.request.Request(
        f"{API_URL}/wallets/{alice_wallet_id}",
        headers={"Authorization": f"Bearer {alice_jwt}"},
        method="GET"
    )
    try:
        with urllib.request.urlopen(req_check) as r:
            wallet_data = json.loads(r.read().decode())
            offline_available = wallet_data.get("balances", {}).get("offline_available_cents", 0)
    except Exception:
        offline_available = 0

    otp_amount_cents = 5000  # $50 offline OTP

    if offline_available < otp_amount_cents:
        needed_online = 20000  # $200 online
        needed_offline = otp_amount_cents - offline_available
        print(f"1. Offline balance too low ({offline_available}¢). Topping up Alice's wallet (+${needed_online/100:.2f} Online, +${needed_offline/100:.2f} Offline)...")
        topup_body = {
            "amount_cents": needed_online,
            "offline_allocation_cents": needed_offline,
            "wallet_id": alice_wallet_id,
            "source": {"type": "card", "id": "tok_mastercard"}
        }
        req = urllib.request.Request(
            f"{API_URL}/topups",
            data=json.dumps(topup_body).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {alice_jwt}",
                "Content-Type": "application/json",
                "Idempotency-Key": str(uuid.uuid4())
            },
            method="POST"
        )
        try:
            with urllib.request.urlopen(req) as response:
                print("   ✅ Topup Successful!")
        except urllib.error.HTTPError as e:
            print(f"   ⚠️ Topup HTTP Error: {e.read().decode('utf-8')}")
    else:
        print(f"1. Alice already has sufficient offline balance ({offline_available}¢). Skipping topup.")

    print("\n2. Generating One-Time Offline Token for $50.00...")
    emergency_body = {
        "wallet_id": alice_wallet_id,
        "amount_cents": otp_amount_cents
    }
    req2 = urllib.request.Request(
        f"{API_URL}/payments/emergency",
        data=json.dumps(emergency_body).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {alice_jwt}",
            "Content-Type": "application/json",
            "Idempotency-Key": str(uuid.uuid4())
        },
        method="POST"
    )
    
    try:
        with urllib.request.urlopen(req2) as response2:
            resp_data2 = json.loads(response2.read().decode())
            otp_code = resp_data2["otp_code"]
            print(f"   ✅ Token Generated! Code: {otp_code}")
    except urllib.error.HTTPError as e:
        err = e.read().decode('utf-8')
        print(f"   ❌ Failed to generate Token: {err}")
        sys.exit(1)

    print("\n3. Downloading QR Code image...")
    qr_url = f"https://api.qrserver.com/v1/create-qr-code/?size=400x400&data={urllib.parse.quote(otp_code)}"
    
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    
    with urllib.request.urlopen(qr_url, context=ctx) as response, open("alice_offline_qr.png", 'wb') as out_file:
        out_file.write(response.read())
        
    print("   ✅ Saved to 'alice_offline_qr.png'.")

    # Try to open the image automatically
    if sys.platform == "darwin":
        subprocess.call(["open", "alice_offline_qr.png"])
    elif sys.platform == "win32":
        os.startfile("alice_offline_qr.png")
    else:
        subprocess.call(["xdg-open", "alice_offline_qr.png"])

    print("\n🎉 DONE! \nTo Demo:")
    print("1. Alice turns OFF her internet.")
    print("2. Alice shows the 'alice_offline_qr.png' on her screen to Bob.")
    print("3. Bob opens 'merchant_pos.html' (Bob has internet, or will sync later).")
    print("4. Bob clicks 'Scan', points the webcam at Alice's QR code.")
    print("5. Bob enters 5.00 for the coffee and clicks 'Verify & Settle Payment'!")

if __name__ == "__main__":
    main()
