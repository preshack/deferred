"""Deferred API — Hierarchical Deterministic Key Derivation.

Implements Ed25519-based HD key derivation inspired by BIP-32.
Uses HMAC-SHA512 for child key derivation with a custom derivation path:
    m/44'/666'/wallet_index'/account'/change/index
"""

from __future__ import annotations

import hashlib
import hmac
import os
import struct
from dataclasses import dataclass
from typing import List, Tuple

import nacl.signing


@dataclass
class DerivedKey:
    """A derived Ed25519 keypair with its derivation path."""
    path: str
    index: int
    signing_key: nacl.signing.SigningKey
    verify_key: nacl.signing.VerifyKey
    chain_code: bytes

    @property
    def public_key_bytes(self) -> bytes:
        return bytes(self.verify_key)

    @property
    def private_key_bytes(self) -> bytes:
        return bytes(self.signing_key)


class HDKeyDerivation:
    """Hierarchical Deterministic key derivation for Ed25519.

    BIP-32 doesn't natively support Ed25519 (it's designed for secp256k1),
    so we use SLIP-0010 (https://github.com/satoshilabs/slips/blob/master/slip-0010.md)
    which adapts HD derivation for Ed25519.

    Derivation path: m/44'/666'/wallet_index'/account'/change/index
    - 44' = BIP-44 purpose
    - 666' = Deferred coin type (custom)
    - wallet_index' = wallet-specific
    - account' = sub-account
    - change = 0 (external) or 1 (internal/change)
    - index = key index
    """

    HARDENED_OFFSET = 0x80000000
    CURVE_SEED = b"ed25519 seed"  # SLIP-0010 constant

    def __init__(self, master_seed: bytes | None = None):
        """Initialize with a master seed (32 bytes).

        Args:
            master_seed: 32-byte random seed. If None, generates a new one.
        """
        if master_seed is None:
            master_seed = os.urandom(32)
        if len(master_seed) < 16:
            raise ValueError("Master seed must be at least 16 bytes")

        self._master_seed = master_seed
        self._master_key, self._master_chain_code = self._derive_master()

    @property
    def master_seed(self) -> bytes:
        """Access the master seed (handle with care — this is the root secret)."""
        return self._master_seed

    def _derive_master(self) -> Tuple[bytes, bytes]:
        """Derive master key and chain code from seed using HMAC-SHA512."""
        I = hmac.new(self.CURVE_SEED, self._master_seed, hashlib.sha512).digest()
        return I[:32], I[32:]  # key, chain_code

    def _derive_child(
        self, parent_key: bytes, parent_chain_code: bytes, index: int
    ) -> Tuple[bytes, bytes]:
        """Derive a hardened child key (Ed25519 only supports hardened derivation).

        Args:
            parent_key: 32-byte parent private key
            parent_chain_code: 32-byte parent chain code
            index: Child index (will be hardened with offset)

        Returns:
            Tuple of (child_key, child_chain_code)
        """
        # SLIP-0010: hardened child derivation for Ed25519
        # Data = 0x00 || parent_key || index (big-endian, with hardened bit)
        hardened_index = index + self.HARDENED_OFFSET
        data = b"\x00" + parent_key + struct.pack(">I", hardened_index)

        I = hmac.new(parent_chain_code, data, hashlib.sha512).digest()
        return I[:32], I[32:]

    def derive_path(self, path: str) -> DerivedKey:
        """Derive a key at a specific BIP-32-style path.

        Args:
            path: Derivation path like "m/44'/666'/0'/0'/0/0"

        Returns:
            DerivedKey with signing and verification keys
        """
        segments = path.split("/")
        if segments[0] != "m":
            raise ValueError("Path must start with 'm'")

        key = self._master_key
        chain_code = self._master_chain_code

        for segment in segments[1:]:
            hardened = segment.endswith("'")
            index = int(segment.rstrip("'"))
            if hardened:
                key, chain_code = self._derive_child(key, chain_code, index)
            else:
                # For Ed25519, all derivation is hardened per SLIP-0010
                key, chain_code = self._derive_child(key, chain_code, index)

        signing_key = nacl.signing.SigningKey(key)
        verify_key = signing_key.verify_key

        return DerivedKey(
            path=path,
            index=int(segments[-1].rstrip("'")),
            signing_key=signing_key,
            verify_key=verify_key,
            chain_code=chain_code,
        )

    def derive_wallet_keys(
        self,
        wallet_index: int,
        count: int = 100,
        account: int = 0,
    ) -> List[DerivedKey]:
        """Derive a batch of keys for a wallet.

        Uses path: m/44'/666'/wallet_index'/account'/0/i

        Args:
            wallet_index: Index of the wallet
            count: Number of keys to derive
            account: Sub-account index

        Returns:
            List of DerivedKey objects
        """
        keys = []
        for i in range(count):
            path = f"m/44'/666'/{wallet_index}'/{account}'/0/{i}"
            keys.append(self.derive_path(path))
        return keys

    def get_master_public_key(self) -> bytes:
        """Get the master public key (safe to share)."""
        signing_key = nacl.signing.SigningKey(self._master_key)
        return bytes(signing_key.verify_key)

    @staticmethod
    def generate_master_seed(entropy_bytes: int = 32) -> bytes:
        """Generate a cryptographically secure master seed.

        Uses os.urandom which sources from /dev/urandom or getrandom().
        """
        return os.urandom(entropy_bytes)
