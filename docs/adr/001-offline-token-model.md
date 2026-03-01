# ADR 001: Offline Token Model (Sign-Once)

## Status
**Accepted** — 2024-02-28

## Context
We need a mechanism for offline payments that:
1. Prevents double-spending without network connectivity
2. Provides cryptographic proof that a merchant can verify
3. Minimizes trust requirements between parties

### Alternatives Considered

| Model | Pros | Cons |
|-------|------|------|
| **UTXO (Bitcoin-style)** | Proven, auditable | Complex scripting, large proofs |
| **Account model** | Simple, familiar | Requires network for auth |
| **Pre-signed vouchers** | Simple offline use | No programmability |
| **Sign-Once tokens** ✅ | Simple, provable destruction | Fixed denominations |

## Decision
Use **Sign-Once tokens** with Ed25519 keypairs stored in a Secure Element.

### How It Works
1. **Minting:** Server issues tokens with fresh Ed25519 keypairs. Private key stored in SE.
2. **Spending:** Token signs the transaction hash, then the private key is **cryptographically destroyed**.
3. **Verification:** Merchant verifies signature + destruction proof. If both valid, payment is guaranteed.

### Key Property
A token can only ever sign **one transaction**. After signing, the key is destroyed (SE zeroes the memory). This is enforced at the hardware level in production and cryptographically provable.

### Why Not UTXO?
UTXOs require a scripting engine and produce chain-length proofs. Sign-Once tokens produce a single proof: one signature + one destruction certificate. The proof is O(1) in size regardless of token history.

## Consequences
- **Fixed denominations** ($5, $10, $20, $50, $100) — requires coin selection
- **No partial spends** — a $20 token pays $20, any excess is "change" requiring a new token
- **Requires Secure Element** for production-grade key destruction guarantees
- **Offline state grows linearly** with unsynced transaction count
