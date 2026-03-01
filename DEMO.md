# 🚀 Deferred API — Interactive Demo & API Guide

Welcome to the **Deferred API**! This guide walks you through the complete lifecycle of our flagship feature: **Cryptographically secure offline payments**.

## 💡 Why This Matters

The ability to securely transact without internet connectivity transforms the digital payment landscape:
- **Works in disaster zones** when critical infrastructure fails.
- **Works in rural, low-connectivity regions** expanding financial inclusion.
- **Reduces merchant chargeback risk** with cryptographic irrefutability.
- **Enables hardware-secure offline micropayments.**

**Ideal for:**
- 🚆 Transit systems and airplanes
- 🌍 Developing markets
- 🎪 Events/festivals with congested networks
- 🪖 Military field ops

## 🧠 Architectural Strengths

- **Clean lifecycle separation**: Setup → Offline Generation → Settlement → Sync
- **Auth clearly scoped per actor**: Bearer JWT (Users) vs API Key (Merchants)
- **Mode switching via header**: `x-deferred-mode`
- **Explicit offline allocation accounting**: Transparent segregation of online vs offline balances
- **Good financial clarity**: Strict integer cents representation (`amount_cents`)

---

## 💻 The Interactive Demo
This section is designed for **PowerShell**, so you can copy and paste these commands directly into your terminal.

---

## 🏗️ Phase 1: Setup & Wallets (Online)

Before devices go offline, they need wallets and funds. We will create two users:
- **Alice**: The customer who wants to pay offline.
- **Bob**: The merchant (e.g., a coffee shop) who will receive the offline payment.

### 1. Authenticate

Get an access token for Alice.
```powershell
$authResp = Invoke-RestMethod -Uri "http://localhost:8000/auth/token" -Method Post -ContentType "application/json" -Body '{"customer_id": "alice_user", "secret": "test_secret"}'
$aliceToken = $authResp.access_token
Write-Host "🔑 Alice's Token: ${aliceToken}"
```

### 2. Create Alice's Wallet
Creates a wallet capable of storing offline funds securely.
```powershell
$aliceWalletBody = @{
    type = "personal"
    offline_allowance_cents = 5000  # She can take up to $50 offline
    currency = "usd"
    security_tier = "software"
    customer_reference = "alice"
} | ConvertTo-Json

$aliceWallet = Invoke-RestMethod -Uri "http://localhost:8000/wallets" -Method Post -Headers @{Authorization="Bearer $aliceToken"} -ContentType "application/json" -Body $aliceWalletBody
$aliceWalletId = $aliceWallet.id
Write-Host "👛 Alice's Wallet ID: ${aliceWalletId}"
```

### 3. Top-Up Alice's Wallet
Add $100 to Alice's wallet, allocating $20 specifically for offline use.
```powershell
$topupBody = @{
    wallet_id = $aliceWalletId
    amount_cents = 10000  # Total $100
    offline_allocation_cents = 2000  # Move $20 to offline Secure Element
    source = @{
        type = "bank_account"
        id = "alice_chase_account"
    }
} | ConvertTo-Json -Depth 3

$topup = Invoke-RestMethod -Uri "http://localhost:8000/topups" -Method Post -Headers @{Authorization="Bearer $aliceToken"} -ContentType "application/json" -Body $topupBody
Write-Host "💰 Alice's Balances - Online: $($topup.wallet.online_balance_cents)¢ | Offline: $($topup.wallet.offline_balance_cents)¢"
```

### 4. Create Bob (The Merchant)
Bob needs an API key to settle transactions later.
```powershell
# In a real app, Bob gets this from a dashboard. We use a test key here.
$bobApiKey = "sk_test_1234567890abcdef1234567890abcdef"
```

---

## � Security Model & Double-Spend Prevention

How do we prevent Alice from spending the same offline funds twice?
Offline funds are represented as **single-use signed spend tokens** derived from an HD (Hierarchical Deterministic) wallet branch.

1. **The Offline Payload** includes:
   - Wallet public key
   - Merchant ID
   - Amount
   - Cryptographic Nonce
   - Expiry timestamp
   - Digital signature (Ed25519)
2. **Key Destruction (Sign-Once)**: Each token is cryptographically invalidated after signing. The Secure Element (or software fallback) physically destroys the specific derived private key used for that transaction.
3. **Server Validation**: When the merchant uploads the proof, the server validates:
   - Signature authenticity
   - Token non-reuse (idempotency check against the token ID)
   - Expiry window
   - Merchant legitimacy

---

## �📴 Phase 2: The Offline Payment (No Internet!)

Alice walks into Bob's coffee shop. **Neither of them has internet.**

How does she pay?
1. **Alice's Phone** cryptographically signs a payment payload using her Secure Element (or software fallback), consuming one of her pre-allocated "offline tokens".
2. **Alice's Phone** generates a QR code containing this signature.
3. **Bob's Point of Sale** scans the QR code and validates the signature using Deferred's offline public keys (which Bob's POS synced earlier).

*Note: In the real world, this happens via Bluetooth/NFC/QR codes between physical devices. To simulate this via our API, we tell the API to act as Alice's local device by passing the `x-deferred-mode: offline` header.*

```powershell
$paymentBody = @{
    wallet_id = $aliceWalletId
    merchant_id = "merchant_bob"
    amount_cents = 450  # $4.50 for a latte
    currency = "usd"
    description = "Latte"
} | ConvertTo-Json

# NOTICE the headers: No Bearer token! Only an offline indicator.
$payment = Invoke-RestMethod -Uri "http://localhost:8000/payments" -Method Post -Headers @{"x-deferred-mode"="offline"} -ContentType "application/json" -Body $paymentBody

$offlinePayload = $payment.offline_proof.settlement_payload
Write-Host "📱 Alice generated QR Payload: ${offlinePayload}"
```

At this moment, Alice can take her coffee and leave. The payment is cryptographically guaranteed because her Secure Element physically destroyed the key required to spend those exact funds again (preventing double-spending).

---

## 📡 Phase 3: Settlement (Online Reconnected)

Later that night, Bob's Point of Sale connects to the restaurant's Wi-Fi. It takes the QR payloads it scanned all day and sends them to the Deferred API for settlement.

```powershell
$settlementBody = @{
    merchant_id = "merchant_bob"
    payment_proof = $offlinePayload  # Bob uploads what he scanned from Alice
} | ConvertTo-Json

# Bob authenticates using his Merchant API Key
$settlement = Invoke-RestMethod -Uri "http://localhost:8000/settlements" -Method Post -Headers @{"x-api-key"=$bobApiKey} -ContentType "application/json" -Body $settlementBody

# The API returns a full settlement confirmation
$settlement | ConvertTo-Json -Depth 3
```

**Example Settlement Response:**
```json
{
  "id": "stl_01j7h8v9pw2tq",
  "object": "settlement",
  "payment_id": "pay_offline_9f8d",
  "status": "settled",
  "amount_cents": 450,
  "fee_cents": 14,
  "net_cents": 436,
  "guarantee_expires_at": null,
  "funds_available_at": "2026-03-01T00:00:00Z",
  "payout": {
    "destination": "bank_account_bob",
    "estimated_arrival": "2026-03-02T12:00:00Z"
  }
}
```

---

## 🔄 Phase 4: Sync & Audit

When Alice's phone reconnects to the internet, it silently syncs state with the server to update her visible balances and replenish her offline tokens if her allowance permits.

```powershell
$syncBody = @{
    wallet_id = $aliceWalletId
    priority = "high"
} | ConvertTo-Json

$sync = Invoke-RestMethod -Uri "http://localhost:8000/sync" -Method Post -Headers @{Authorization="Bearer $aliceToken"} -ContentType "application/json" -Body $syncBody

Write-Host "🔄 Sync Processed: $($sync.processed) transactions"
```

To verify, let's look at Alice's wallet balance now:

```powershell
$finalWallet = Invoke-RestMethod -Uri "http://localhost:8000/wallets/$aliceWalletId" -Method Get -Headers @{Authorization="Bearer $aliceToken"}
Write-Host "🏦 Final Online Balance: $($finalWallet.balances.online_cents)¢"      # Stays at $80 (10000 - 2000 allocation)
Write-Host "🏦 Final Offline Pool: $($finalWallet.balances.offline_available_cents)¢" # Drops to $15.50 (2000 - 450 spent)
```

---

## ⚠️ Failure Scenarios & Edge Cases

Real-world APIs handle edge cases gracefully. The Deferred API returns structured `4xx` error responses with `how_to_fix` guidance.

- ❌ **Token already spent** → `409 Conflict` (Idempotency violation or Double-Spend attempt)
- ❌ **Signature invalid** → `400 Bad Request` (Payload tampering or cryptographic failure)
- ❌ **Expired proof** → `422 Unprocessable Entity` (Token used outside of its validity window)
- ❌ **Merchant not authorized** → `403 Forbidden` (Invalid `x-api-key` or permissions)

---

## 🛠️ Complete API Reference

| Endpoint | Method | Auth Required | Purpose |
|----------|--------|---------------|---------|
| `/auth/token` | `POST` | None | Authenticate customer, returns JWT. |
| `/wallets` | `POST` | `Bearer` | Create an HD Wallet with Shamir Recovery. |
| `/wallets/{id}` | `GET` | `Bearer` | Retrieve wallet balances and configuration. |
| `/topups` | `POST` | `Bearer` | Move fiat funds into the wallet & offline token pool. |
| `/payments` | `POST` | `x-deferred-mode` | Generate cryptographic proofs for offline spending. |
| `/settlements`| `POST` | `x-api-key` | Merchants upload proofs to settle transactions and get paid. |
| `/sync` | `POST` | `Bearer` | Reconcile shadow state and fetch new token keys. |
| `/health` | `GET` | None | System status and observability ping. |
