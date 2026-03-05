🎯 Deferred API v1.0
Offline‑First Payments Infrastructure for the Real World
“Stripe for the real world.”  
Deferred API is an offline‑capable payments engine that authorizes, signs, and settles transactions even without internet connectivity — then syncs automatically with cryptographic protection against double‑spending.

Built for fintechs, embedded finance, retail, mobility, and any environment where connectivity is unreliable but payments must never fail.

[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://python.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.109+-green.svg)](https://fastapi.tiangolo.com)
[![PostgreSQL 15](https://img.shields.io/badge/PostgreSQL-15-blue.svg)](https://postgresql.org)

---

🚀 Why Deferred API?
Modern payment systems assume constant connectivity. Real life doesn’t.

Deferred API provides:

Guaranteed offline payments with cryptographic proofs

Automatic reconciliation when devices reconnect

Double‑spend prevention using atomic global spend registry

Secure ephemeral signing keys (destroyed after use)

Merchant‑friendly settlement flows

Developer‑first API design with FastAPI + Pydantic

This makes it ideal for:

Field sales

Mobility & transit

Rural commerce

Disaster‑resilient payments

IoT devices

Offline‑first fintech apps

⚡ Quick Start (60 Seconds)
Option A — Docker (Recommended)
bash
cp .env.example .env
docker-compose up --build
Your API is now live at:
👉 http://localhost:8000/docs

Option B — Local Development
bash
# 1. Install dependencies
pip install -e ".[dev]"

# 2. Start infrastructure
docker-compose up db redis rabbitmq -d

# 3. Configure and run
cp .env.example .env
uvicorn app.main:app --reload
🏗️ System Architecture
Code
┌─────────────────────────────────────────────────────────────────┐
│                           DEFERRED API                          │
├─────────────────────────────────────────────────────────────────┤
│  FastAPI Application                                             │
│  ┌───────────┐ ┌──────────┐ ┌───────────┐ ┌──────────────────┐ │
│  │  Wallets   ││ Payments ││ Settlements││ Sync/Reconcile   │ │
│  └─────┬─────┘ └────┬─────┘ └─────┬─────┘ └───────┬─────────┘ │
│        │             │             │                │           │
│  ┌─────┴─────────────┴─────────────┴────────────────┴────────┐ │
│  │                 Service Layer (Business Logic)              │ │
│  └─────┬─────────────┬─────────────┬─────────────────┬────────┘ │
│        │             │             │                 │           │
│  ┌─────┴────┐  ┌─────┴─────┐ ┌────┴────┐  ┌────────┴────────┐ │
│  │  Crypto  │  │ Database  │ │  Redis  │  │   RabbitMQ      │ │
│  │ (PyNaCl) │  │PostgreSQL │ │  Cache  │  │   Events        │ │
│  └──────────┘  └───────────┘ └─────────┘  └─────────────────┘ │
└─────────────────────────────────────────────────────────────────┘
🧩 Core Technologies
Component	Technology	Purpose
Runtime	Python 3.11+ / FastAPI	High‑performance async API
Database	PostgreSQL 15	Durable ACID storage
Cache	Redis 7	Idempotency + distributed locks
Message Bus	RabbitMQ 3.12	Event sourcing + webhooks
Cryptography	PyNaCl	Ed25519, Shamir, secure token minting
Observability	Prometheus + structlog	Metrics + structured logs
🔌 API Reference
All endpoints return structured error objects with actionable how_to_fix guidance.

Method	Endpoint	Description	Status
POST	/auth/token	Issue JWT access token	200
POST	/auth/refresh	Refresh access token	200
POST	/wallets	Create wallet (HD key generation)	201
GET	/wallets/{id}	Retrieve wallet + sync state	200
POST	/topups	Add funds to wallet	201
POST	/payments	Online or offline payment	201 / 202
POST	/settlements	Merchant submits settlement proof	201
POST	/sync/trigger	Force sync of pending ops	200
GET	/health	Health check	200
GET	/metrics	Prometheus metrics	200
🧪 7‑Line Integration Example
python
import httpx

api = httpx.Client(base_url="http://localhost:8000")
token = api.post("/auth/token", json={"customer_id": "cust_1", "secret": "test_secret"}).json()
api.headers["Authorization"] = f"Bearer {token['access_token']}"

wallet = api.post("/wallets", json={
    "offline_allowance_cents": 50000,
    "customer_reference": "cust_1"
}).json()

api.post("/topups", json={
    "wallet_id": wallet["id"],
    "amount_cents": 10000,
    "source": {"type": "bank_account", "id": "ba_123"}
})

payment = api.post("/payments", json={
    "amount_cents": 2500,
    "wallet_id": wallet["id"],
    "merchant_id": "merch_1"
}).json()

print(f"Payment {payment['id']}: {payment['status']}")
🔒 Security Model
Deferred API is designed for high‑trust, adversarial environments.

Ephemeral signing keys — private keys destroyed after a single use

BIP‑32 HD key hierarchy — deterministic wallet trees

Shamir secret sharing — k‑of‑n recovery

Atomic double‑spend prevention — global spend registry

Zero‑trust authentication — JWT + Ed25519 + merchant API keys

🧪 Testing & Load Simulation
bash
# Full test suite
pytest tests/ -v

# Crypto-only tests
pytest tests/test_crypto.py tests/test_coin_selection.py -v

# Load testing
locust -f locustfile.py --host=http://localhost:8000
📁 Project Structure
Code
app/
├── main.py                 # FastAPI app + lifespan
├── config.py               # Pydantic settings
├── db.py                   # Async SQLAlchemy engine
├── models.py               # ORM entities
├── schemas.py              # Pydantic I/O models
├── auth.py                 # JWT + API key auth
├── middleware.py           # Idempotency + security headers
├── observability.py        # Metrics + logging
├── crypto/
│   ├── secure_element.py   # Sign-once secure element
│   ├── keys.py             # BIP-32 derivation
│   ├── shamir.py           # Secret sharing
│   └── tokens.py           # Token minting + coin selection
├── services/
│   ├── wallet_service.py
│   ├── payment_service.py
│   ├── settlement_service.py
│   ├── sync_service.py
│   └── event_bus.py
└── routers/
    ├── auth_routes.py
    ├── wallets.py
    ├── topups.py
    ├── payments.py
    ├── settlements.py
    └── sync.py


html
<!--
offline payments api, deferred payments, offline-first fintech, python payments backend,
fastapi payments api, cryptographic payments, ed25519 payments, shamir secret sharing wallet,
double spend prevention api, fintech infrastructure python, embedded finance offline,
iot payments offline, mobile payments offline, stripe alternative offline
-->
📄 License
MIT License — build the future of offline‑first payments.
