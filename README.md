# 🎯 Deferred API v1.0

> **"Stripe for the real world"** — An offline-first payment API that processes payments seamlessly offline, synchronizes intelligently when connectivity returns, and maintains cryptographic guarantees against double-spending.

[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://python.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.109+-green.svg)](https://fastapi.tiangolo.com)
[![PostgreSQL 15](https://img.shields.io/badge/PostgreSQL-15-blue.svg)](https://postgresql.org)

---

## ⚡ Quick Start (60 seconds)

### Option A: Docker (recommended)

```bash
# Clone and start everything
cp .env.example .env
docker-compose up --build
```

The API is live at **http://localhost:8000/docs** 🎉

### Option B: Local Development

```bash
# 1. Install dependencies
pip install -e ".[dev]"

# 2. Start infrastructure (PostgreSQL, Redis, RabbitMQ)
docker-compose up db redis rabbitmq -d

# 3. Copy env and run
cp .env.example .env
uvicorn app.main:app --reload
```

---

## 🏗️ Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        DEFERRED API                             │
├─────────────────────────────────────────────────────────────────┤
│  FastAPI Application                                            │
│  ┌───────────┐ ┌──────────┐ ┌───────────┐ ┌──────────────────┐  │ 
│  │  Wallets   ││ Payments││ Settlements│ Sync/Reconcile │  │
│  └─────┬─────┘ └────┬─────┘ └─────┬─────┘ └───────┬─────────┘  │
│        │            │            │                │            │
│  ┌─────┴────────────┴────────────┴────────────────┴────────┐   │
│  │              Service Layer (Business Logic)              │   │
│  └─────┬─────────────┬─────────────┬─────────────────┬──────┘ │
│        │             │             │                 │          │
│  ┌─────┴────┐  ┌─────┴─────┐ ┌────┴────┐  ┌────────┴────────┐ │
│  │  Crypto  │  │ Database  │ │  Redis  │  │   RabbitMQ      │ │
│  │(PyNaCl)  │  │(PostgreSQL)│ │ (Cache) │  │  (Events)       │ │
│  └──────────┘  └───────────┘ └─────────┘  └─────────────────┘ │
└─────────────────────────────────────────────────────────────────┘
```

### Core Technologies

| Component | Technology | Purpose |
|-----------|-----------|---------|
| Runtime | Python 3.11+ / FastAPI | Async API framework |
| Database | PostgreSQL 15 | ACID-compliant persistence |
| Cache | Redis 7 | Idempotency, distributed locking |
| Message Bus | RabbitMQ 3.12 | Event sourcing, webhooks |
| Cryptography | PyNaCl (libsodium) | Ed25519, Shamir's Secret Sharing |
| Observability | Prometheus + structlog | Metrics and structured logs |

---

## 🔌 API Reference

All endpoints return structured errors with `how_to_fix` guidance.

| Method | Endpoint | Description | Status |
|--------|----------|-------------|--------|
| `POST` | `/auth/token` | Get JWT access token | `200` |
| `POST` | `/auth/refresh` | Refresh token | `200` |
| `POST` | `/wallets` | Create wallet (HD key gen) | `201` |
| `GET` | `/wallets/{id}` | Get wallet + sync status | `200` |
| `POST` | `/topups` | Fund wallet | `201` |
| `POST` | `/payments` | Online or offline payment | `201`/`202` |
| `POST` | `/settlements` | Merchant settles proof | `201` |
| `POST` | `/sync/trigger` | Sync pending transactions | `200` |
| `GET` | `/health` | System health check | `200` |
| `GET` | `/metrics` | Prometheus metrics | `200` |

### 7-Line Integration

```python
import httpx

api = httpx.Client(base_url="http://localhost:8000")
token = api.post("/auth/token", json={"customer_id": "cust_1", "secret": "test_secret"}).json()
api.headers["Authorization"] = f"Bearer {token['access_token']}"
wallet = api.post("/wallets", json={"offline_allowance_cents": 50000, "customer_reference": "cust_1"}).json()
api.post("/topups", json={"wallet_id": wallet["id"], "amount_cents": 10000, "source": {"type": "bank_account", "id": "ba_123"}})
payment = api.post("/payments", json={"amount_cents": 2500, "wallet_id": wallet["id"], "merchant_id": "merch_1"}).json()
print(f"Payment {payment['id']}: {payment['status']}")
```

---

## 🔒 Security Model

- **Sign-Once Tokens:** Private keys destroyed after single use
- **BIP-32 HD Keys:** Hierarchical deterministic key derivation
- **Shamir Recovery:** k-of-n secret sharing for wallet recovery
- **Double-Spend Prevention:** Global spend registry with atomic checks
- **Zero-Trust Auth:** JWT + Ed25519 + API keys for merchants

---

## 🧪 Testing

```bash
# Unit + integration tests
pytest tests/ -v

# Crypto tests only
pytest tests/test_crypto.py tests/test_coin_selection.py -v

# Load test
locust -f locustfile.py --host=http://localhost:8000
```

---

## 📁 Project Structure

```
app/
├── main.py              # FastAPI app factory + lifespan
├── config.py            # Pydantic Settings
├── db.py                # Async SQLAlchemy engine
├── models.py            # ORM models (8 entities)
├── schemas.py           # Pydantic request/response
├── auth.py              # JWT + API key authentication
├── middleware.py         # Idempotency, security headers
├── observability.py     # Prometheus, structlog, OpenTelemetry
├── crypto/
│   ├── secure_element.py  # Sign-Once SE abstraction
│   ├── keys.py            # BIP-32 HD key derivation
│   ├── shamir.py          # Shamir's Secret Sharing
│   └── tokens.py          # Token minting + coin selection
├── services/
│   ├── wallet_service.py    # Wallet lifecycle
│   ├── payment_service.py   # Online/offline payments
│   ├── settlement_service.py # Proof verification
│   ├── sync_service.py      # Reconciliation engine
│   └── event_bus.py         # RabbitMQ publisher
└── routers/
    ├── auth_routes.py  # /auth endpoints
    ├── wallets.py      # /wallets endpoints
    ├── topups.py       # /topups endpoints
    ├── payments.py     # /payments endpoints
    ├── settlements.py  # /settlements endpoints
    └── sync.py         # /sync endpoints
```

---

## 📄 License

MIT License — Build the future of payments.
