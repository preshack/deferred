"""Full crypto smoke test — writes results to file."""
import os, sys
os.environ["DATABASE_URL"] = "sqlite+aiosqlite://"
os.environ["JWT_SECRET_KEY"] = "test_secret_key_for_testing_only"
os.environ["API_DEBUG"] = "false"

from app.crypto.secure_element import (
    SoftwareSecureElement, KeyDestroyedError, verify_signature, verify_destruction_proof,
)
from app.crypto.keys import HDKeyDerivation
from app.crypto.shamir import ShamirSecretSharing, _EXP_TABLE, _LOG_TABLE

results = []
output_lines = []

def log(msg):
    output_lines.append(msg)

def check(name, fn):
    try:
        ok = fn()
        s = "PASS" if ok else "FAIL"
        results.append((name, s))
        log(f"  {s}: {name}")
    except Exception as e:
        results.append((name, f"ERROR"))
        log(f"  ERROR: {name} -> {e}")

# GF table check
log("=== GF(2^8) table check ===")
log(f"  EXP len: {len(_EXP_TABLE)}")
log(f"  LOG[1]: {_LOG_TABLE[1]}")
log(f"  LOG[3]: {_LOG_TABLE[3]}")
log(f"  EXP[LOG[1]]: {_EXP_TABLE[_LOG_TABLE[1]]}")
log(f"  EXP[LOG[3]]: {_EXP_TABLE[_LOG_TABLE[3]]}")

# SE
se = SoftwareSecureElement()
kp = se.generate_keypair("t1")
check("keygen_32b", lambda: len(kp.public_key) == 32)
kp2 = se.generate_keypair("t2", extractable=True)
check("extractable", lambda: kp2.private_key is not None)
sig = se.sign("t1", b"data")
check("sign_64b", lambda: len(sig) == 64)
check("verify_ok", lambda: verify_signature(kp.public_key, sig, b"data"))
check("verify_bad", lambda: not verify_signature(kp.public_key, sig, b"wrong"))

# Sign-Once
se2 = SoftwareSecureElement()
kp3 = se2.generate_keypair("once")
sig2 = se2.sign("once", b"tx")
check("first_sign", lambda: len(sig2) == 64)
proof = se2.destroy_key("once")
check("proof_valid", lambda: verify_destruction_proof(proof))
check("key_gone", lambda: not se2.has_key("once"))

def resign():
    try:
        se2.sign("once", b"tx2")
        return False
    except KeyDestroyedError:
        return True
check("resign_blocked", resign)

proof2 = se2.destroy_key("once")
check("idempotent", lambda: proof.destruction_hash == proof2.destruction_hash)

# HD Keys
hd1 = HDKeyDerivation(b"\x01" * 32)
hd2 = HDKeyDerivation(b"\x01" * 32)
k1 = hd1.derive_path("m/44'/666'/0'/0'/0/0")
k2 = hd2.derive_path("m/44'/666'/0'/0'/0/0")
check("deterministic", lambda: k1.public_key_bytes == k2.public_key_bytes)
k3 = hd1.derive_path("m/44'/666'/0'/0'/0/1")
check("diff_paths", lambda: k1.public_key_bytes != k3.public_key_bytes)
keys = hd1.derive_wallet_keys(0, 5)
check("batch_5", lambda: len(keys) == 5)
check("all_unique", lambda: len({k.public_key_bytes for k in keys}) == 5)

# Shamir
secret = b"master_seed_32_bytes_exactly_here"
shares = ShamirSecretSharing.split(secret, k=3, n=5)
check("5_shares", lambda: len(shares) == 5)
r1 = ShamirSecretSharing.reconstruct(shares[:3])
check("3of5_reconstruct", lambda: r1 == secret)
if r1 != secret:
    log(f"  DEBUG: secret={secret[:4].hex()}..., reconstructed={r1[:4].hex()}...")
r2 = ShamirSecretSharing.reconstruct(shares[1:4])
check("diff_subset", lambda: r2 == secret)
if r2 != secret:
    log(f"  DEBUG: secret={secret[:4].hex()}..., reconstructed2={r2[:4].hex()}...")
r3 = ShamirSecretSharing.reconstruct(shares[:2])
check("2_shares_wrong", lambda: r3 != secret)
check("verify_shares", lambda: ShamirSecretSharing.verify_shares(shares, k=3))

# Summary
p = sum(1 for _, s in results if s == "PASS")
f = len(results) - p
log(f"\nTOTAL: {p}/{len(results)} passed")

# Write to file
output = "\n".join(output_lines)
with open("test_results.txt", "w") as fh:
    fh.write(output)
print(output)
sys.exit(0 if f == 0 else 1)
