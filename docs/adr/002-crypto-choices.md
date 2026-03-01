# ADR 002: Cryptographic Choices

## Status
**Accepted** — 2024-02-28

## Context
The system handles real money in adversarial environments. Every cryptographic choice must balance security, performance, and auditability.

## Decisions

### Signatures: Ed25519 (RFC 8032)
- **Why:** Deterministic signatures (no nonce reuse risk), 64-byte signatures, fast verification
- **Alternative rejected:** ECDSA (secp256k1) — non-deterministic, larger signatures, WeakRNG attacks
- **Usage:** Token signing, JWT authentication, ancestry chain integrity

### Key Derivation: SLIP-0010 (Ed25519 HD keys)
- **Why:** BIP-32 doesn't natively support Ed25519. SLIP-0010 adapts HD derivation for Ed25519
- **Path:** `m/44'/666'/wallet_index'/account'/change/index`
- **Property:** All derivation is hardened (Ed25519 requirement)

### Symmetric Encryption: XChaCha20-Poly1305
- **Why:** Nonce-misuse resistant (24-byte nonce), no padding oracle attacks
- **Alternative rejected:** AES-GCM — catastrophic nonce reuse, shorter nonce
- **Usage:** Encrypting stored key material, shards, local wallet cache

### Password Hashing: Argon2id
- **Why:** Memory-hard (resists ASIC/GPU attacks), hybrid approach (side-channel resistant)
- **Parameters:** memory=64MB, iterations=3, parallelism=4
- **Usage:** Customer passphrase processing for shard encryption

### Hashing: SHA-256 (external) + BLAKE2b (internal)
- **SHA-256:** Ancestry chains, proof verification (interoperable)
- **BLAKE2b:** Internal hashing, cache keys (faster, keyed mode available)

### Randomness: os.urandom / getrandom()
- **Why:** Kernel CSPRNG, never blocks (urandom), properly seeded
- **Rejected:** `/dev/random` (blocks unnecessarily), `random.random()` (not cryptographic)

## Consequences
- All chosen algorithms are in the **libsodium** library (PyNaCl)
- No custom cryptography — only audited, standardized primitives
- Ed25519 determinism eliminates a class of RNG-related vulnerabilities
- XChaCha20-Poly1305 + Argon2id are OWASP-recommended
