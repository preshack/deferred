# 🏆 Deferred API: Live Hackathon Demo Script
This guide outlines the EXACT step-by-step flow you should perform on stage tomorrow to wow the judges with your offline payment API.

> **Pro Tip for the Stage:** Keep your terminal font size LARGE so the judges can read the JSON responses easily!

---

## 🛠️ Prep (Before you get on stage)
Make sure your Docker container is running.
```bash
docker compose up -d
```
Generate your clean credentials so you have fresh wallets to start:
```bash
python3 setup_creds.py
```
*(This creates `demo_creds.env`. Sourcing this file will give you `$ALICE_JWT` and `$ALICE_WALLET_ID` which you can use in terminal commands).*

---

## 🎤 Step 1: "The Setup" (Online Mode)
*Explain to the judges that Alice (the customer) is at home on Wi-Fi getting ready for the day.*

**1. Check Alice's Empty Wallet balance:**
Run this `curl` command to show she has $0.
```bash
source demo_creds.env
curl -s -X GET "http://localhost:8000/wallets/$ALICE_WALLET_ID" \
     -H "Authorization: Bearer $ALICE_JWT" | jq '.balances'
```
*(Point out to the judges that her `online_cents` and `offline_available_cents` are both 0).*

**2. Top-Up The Wallet (The Magic Move):**
*Explain: "Alice deposits $200 from her bank. But here's the magic—our API securely segregates $50 of that directly into an offline Secure Element pool on her device."*
```bash
curl -s -X POST "http://localhost:8000/topups" \
     -H "Authorization: Bearer $ALICE_JWT" \
     -H "Content-Type: application/json" \
     -d '{
           "amount_cents": 20000, 
           "offline_allocation_cents": 5000, 
           "wallet_id": "'"$ALICE_WALLET_ID"'", 
           "source": {"type": "card", "id": "tok_mastercard"}
         }' | jq '{amount_cents, offline_allocation_cents, status}'
```

**3. Generate the Offline Emergency QR Code:**
*Explain: "Alice knows she is going to a music festival with terrible cell service. She pre-generates an offline QR token for her $50 offline balance."*
```bash
python3 generate_alice_qr.py
```
*(This script calls `/payments/emergency` and literally pops open `alice_offline_qr.png` on your laptop screen. Keep the image open on one half of your screen!)*

---

## 🔌 Step 2: "The Disconnect" (Offline Mode)
**(Crucial Stage Theatrics: Physically turn off your Mac's Wi-Fi right now!)**

*Explain: "Alice is now at the festival. She has no internet. Bob is selling coffee. His POS system is also completely offline."*

**1. Bob Scans the QR Code:**
*Explain: "Alice wants to buy a $5 coffee. She shows her pre-generated QR code to Bob. Bob uses our Merchant SDK to scan it."*

Open a new terminal tab and run Bob's POS script:
```bash
python3 bob_scan_qr.py
```
- It will prompt: `Enter exactly how much to charge Alice (e.g. 5.00): $`
- You type: `5.00`
- **Your webcam instantly turns on!** Point it at the `alice_offline_qr.png` you have open on screen!

**2. The Offline Verification Result:**
The Python script will instantly draw a green box, beep "Scanned!", and print:
> `✅ Payment Settled Successfully!`
> `Net amount deposited: $4.85` *(It automatically took out Bob's 3% processing fee!)*
> `The cryptographic Secure Element signature was verified offline.`

---

## 🛡️ Step 3: "The Double Spend Defense" (Still Offline)
*Explain to the judges: "What if Alice tries to cheat Bob by showing the EXACT same QR code again for another $5 coffee?"*

**1. Try to scan the exact same QR code again!**
Run the scanner again:
```bash
python3 bob_scan_qr.py
```
- Type: `5.00`
- Point the camera at the *same* `alice_offline_qr.png`.

**2. The Rejection:**
The script will now aggressively fail and print:
> `❌ Transaction Failed`
> `Reason: Token has already been spent`

*Explain: "Our API mathematically destroys the offline token upon first use. Double spending is cryptographically impossible, completely protecting the merchant from chargeback fraud, without ever needing an internet connection."*

---

## 📡 Step 4: "The Reconciliation"
**(Turn your Mac's Wi-Fi back on!)**

*Explain: "At the end of the day, Alice goes home and connects to Wi-Fi. Our API automatically syncs her shadow state."*

**1. Check Alice's Final Balance:**
```bash
curl -s -X GET "http://localhost:8000/wallets/$ALICE_WALLET_ID" \
     -H "Authorization: Bearer $ALICE_JWT" | jq '.balances'
```

*Show the judges the final numbers:*
- Her **Online Balance** is still $150.00 (`15000` cents).
- Her **Offline Balance** was $50.00, she spent $5.00, so it perfectly reconciled to **$45.00** (`4500` cents)!

*(Drop the mic! 🎤)*
