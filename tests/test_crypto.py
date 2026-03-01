"""Tests for the cryptographic module.

Tests:
- Ed25519 key generation and signing
- Sign-Once: key destruction prevents re-signing
- Destruction proof verification
- BIP-32 HD key derivation determinism
- Shamir's Secret Sharing roundtrip (k-of-n reconstruction)
"""

from __future__ import annotations

import pytest

from app.crypto.secure_element import (
    KeyDestroyedError,
    KeyNotFoundError,
    SoftwareSecureElement,
    verify_destruction_proof,
    verify_signature,
)
from app.crypto.keys import HDKeyDerivation
from app.crypto.shamir import ShamirSecretSharing, Share


# ─── Secure Element Tests ────────────────────────────────────────────────────


class TestSecureElement:
    """Tests for the SoftwareSecureElement implementation."""

    def test_generate_keypair(self):
        """Keypair generation produces valid Ed25519 keys."""
        se = SoftwareSecureElement()
        kp = se.generate_keypair("test_key_1")

        assert len(kp.public_key) == 32  # Ed25519 public key
        assert kp.private_key is None  # Non-extractable by default
        assert kp.key_id == "test_key_1"

    def test_generate_keypair_extractable(self):
        """Extractable keypairs expose the private key."""
        se = SoftwareSecureElement()
        kp = se.generate_keypair("test_key_2", extractable=True)

        assert kp.private_key is not None
        assert len(kp.private_key) == 32

    def test_sign_and_verify(self):
        """Sign-then-verify roundtrip succeeds."""
        se = SoftwareSecureElement()
        kp = se.generate_keypair("sign_test")
        data = b"Hello, Deferred API!"

        signature = se.sign("sign_test", data)
        assert len(signature) == 64  # Ed25519 signature

        assert verify_signature(kp.public_key, signature, data)

    def test_sign_verify_wrong_data(self):
        """Verification fails with tampered data."""
        se = SoftwareSecureElement()
        kp = se.generate_keypair("tamper_test")
        data = b"Original data"

        signature = se.sign("tamper_test", data)
        assert not verify_signature(kp.public_key, signature, b"Tampered data")

    def test_sign_nonexistent_key(self):
        """Signing with non-existent key raises error."""
        se = SoftwareSecureElement()
        with pytest.raises(KeyNotFoundError):
            se.sign("nonexistent_key", b"data")


class TestSignOnce:
    """Critical: Sign-Once semantics — the core security property."""

    def test_key_destruction_prevents_resign(self):
        """Critical: Destroyed key cannot sign again."""
        se = SoftwareSecureElement()
        kp = se.generate_keypair("one_time_key")
        data = b"Transaction data"

        # First sign succeeds
        sig = se.sign("one_time_key", data)
        assert verify_signature(kp.public_key, sig, data)

        # Destroy key
        proof = se.destroy_key("one_time_key")
        assert verify_destruction_proof(proof)

        # Second sign MUST fail
        with pytest.raises(KeyDestroyedError):
            se.sign("one_time_key", data)

    def test_destruction_is_idempotent(self):
        """Destroying an already-destroyed key returns the same proof."""
        se = SoftwareSecureElement()
        se.generate_keypair("idempotent_key")

        proof1 = se.destroy_key("idempotent_key")
        proof2 = se.destroy_key("idempotent_key")

        assert proof1.key_id == proof2.key_id
        assert proof1.destruction_hash == proof2.destruction_hash

    def test_destruction_proof_structure(self):
        """Destruction proof contains all required fields."""
        se = SoftwareSecureElement()
        se.generate_keypair("proof_test")
        proof = se.destroy_key("proof_test")

        assert proof.key_id == "proof_test"
        assert len(proof.public_key) == 32
        assert len(proof.destruction_hash) == 32
        assert len(proof.nonce) == 16
        assert proof.timestamp > 0

    def test_has_key_reflects_destruction(self):
        """has_key returns False after destruction."""
        se = SoftwareSecureElement()
        se.generate_keypair("lifecycle_key")

        assert se.has_key("lifecycle_key") is True
        se.destroy_key("lifecycle_key")
        assert se.has_key("lifecycle_key") is False


# ─── HD Key Derivation Tests ─────────────────────────────────────────────────


class TestHDKeyDerivation:
    """Tests for BIP-32-style HD key derivation."""

    def test_deterministic_derivation(self):
        """Same seed + path = same keys."""
        seed = b"\x01" * 32
        hd1 = HDKeyDerivation(seed)
        hd2 = HDKeyDerivation(seed)

        key1 = hd1.derive_path("m/44'/666'/0'/0'/0/0")
        key2 = hd2.derive_path("m/44'/666'/0'/0'/0/0")

        assert key1.public_key_bytes == key2.public_key_bytes

    def test_different_paths_different_keys(self):
        """Different paths produce different keys."""
        seed = b"\x02" * 32
        hd = HDKeyDerivation(seed)

        key1 = hd.derive_path("m/44'/666'/0'/0'/0/0")
        key2 = hd.derive_path("m/44'/666'/0'/0'/0/1")

        assert key1.public_key_bytes != key2.public_key_bytes

    def test_different_seeds_different_keys(self):
        """Different seeds produce different keys."""
        hd1 = HDKeyDerivation(b"\x01" * 32)
        hd2 = HDKeyDerivation(b"\x02" * 32)

        key1 = hd1.derive_path("m/44'/666'/0'/0'/0/0")
        key2 = hd2.derive_path("m/44'/666'/0'/0'/0/0")

        assert key1.public_key_bytes != key2.public_key_bytes

    def test_batch_derivation(self):
        """Batch derivation produces unique keys."""
        hd = HDKeyDerivation()
        keys = hd.derive_wallet_keys(wallet_index=0, count=10)

        assert len(keys) == 10
        pubkeys = {k.public_key_bytes for k in keys}
        assert len(pubkeys) == 10  # All unique

    def test_master_public_key(self):
        """Master public key is 32 bytes."""
        hd = HDKeyDerivation()
        mpk = hd.get_master_public_key()
        assert len(mpk) == 32

    def test_short_seed_rejected(self):
        """Seeds shorter than 16 bytes are rejected."""
        with pytest.raises(ValueError, match="at least 16 bytes"):
            HDKeyDerivation(b"\x01" * 8)


# ─── Shamir's Secret Sharing Tests ───────────────────────────────────────────


class TestShamirSecretSharing:
    """Tests for secret splitting and reconstruction."""

    def test_basic_roundtrip_3_of_5(self):
        """3-of-5 split and reconstruct recovers the secret."""
        secret = b"master_seed_32_bytes_exactly_here"
        shares = ShamirSecretSharing.split(secret, k=3, n=5)

        assert len(shares) == 5

        # Any 3 shares should work
        recovered = ShamirSecretSharing.reconstruct(shares[:3])
        assert recovered == secret

    def test_different_subsets(self):
        """Different subsets of k shares produce the same secret."""
        secret = b"\xab" * 32
        shares = ShamirSecretSharing.split(secret, k=3, n=5)

        r1 = ShamirSecretSharing.reconstruct(shares[0:3])
        r2 = ShamirSecretSharing.reconstruct(shares[1:4])
        r3 = ShamirSecretSharing.reconstruct(shares[2:5])

        assert r1 == r2 == r3 == secret

    def test_insufficient_shares_fail(self):
        """Fewer than k shares produce wrong result (information-theoretic security)."""
        secret = b"sensitive_master_seed_material__!"
        shares = ShamirSecretSharing.split(secret, k=3, n=5)

        # 2 shares should NOT reconstruct the secret
        wrong = ShamirSecretSharing.reconstruct(shares[:2])
        assert wrong != secret  # 2 shares: random output

    def test_2_of_3(self):
        """2-of-3 split works."""
        secret = b"short secret"
        shares = ShamirSecretSharing.split(secret, k=2, n=3)
        recovered = ShamirSecretSharing.reconstruct(shares[:2])
        assert recovered == secret

    def test_share_serialization(self):
        """Shares serialize and deserialize correctly."""
        share = Share(x=42, y=b"\x01\x02\x03")
        hex_str = share.to_hex()
        recovered = Share.from_hex(hex_str)

        assert recovered.x == share.x
        assert recovered.y == share.y

    def test_invalid_parameters(self):
        """Invalid parameters raise ValueError."""
        with pytest.raises(ValueError, match="k must be >= 2"):
            ShamirSecretSharing.split(b"test", k=1, n=3)

        with pytest.raises(ValueError, match="n must be >= threshold"):
            ShamirSecretSharing.split(b"test", k=5, n=3)

    def test_verify_shares(self):
        """Share verification accepts consistent shares."""
        secret = b"verify_me_please_32_bytes_exact!"
        shares = ShamirSecretSharing.split(secret, k=3, n=5)
        assert ShamirSecretSharing.verify_shares(shares, k=3)
