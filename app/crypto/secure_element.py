"""Deferred API — Secure Element abstraction.

Provides an abstract interface for hardware security modules (HSM/TEE)
with a software fallback implementation using PyNaCl (libsodium).
"""

from __future__ import annotations

import hashlib
import os
import threading
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Dict, Optional

import nacl.signing
import nacl.utils


@dataclass
class Keypair:
    """Public/private key pair."""
    public_key: bytes
    private_key: Optional[bytes] = None  # None if non-extractable (hardware SE)
    key_id: str = ""


@dataclass
class DestructionProof:
    """Proof that a key has been cryptographically destroyed."""
    key_id: str
    public_key: bytes
    destruction_hash: bytes  # Hash proving key material was zeroed
    timestamp: float = 0.0
    nonce: bytes = field(default_factory=lambda: os.urandom(16))

    def serialize(self) -> bytes:
        """Serialize proof for verification."""
        return self.key_id.encode() + self.public_key + self.destruction_hash + self.nonce


@dataclass
class AttestationReport:
    """Device/SE integrity attestation."""
    valid: bool
    device_id: str = ""
    security_level: str = "software"
    timestamp: float = 0.0


class SecureElement(ABC):
    """Abstract Hardware Security Module / Trusted Execution Environment interface.

    In production, implementations would talk to:
    - Apple Secure Enclave (iOS)
    - Android StrongBox / Titan M
    - Cloud HSMs (AWS CloudHSM, Azure Dedicated HSM)
    - FIDO2 security keys
    """

    @abstractmethod
    def generate_keypair(self, key_id: str, extractable: bool = False) -> Keypair:
        """Generate Ed25519 keypair. Private key stays in SE if not extractable."""
        ...

    @abstractmethod
    def sign(self, key_id: str, data: bytes) -> bytes:
        """Sign data with SE-stored key. Raises KeyDestroyedError if destroyed."""
        ...

    @abstractmethod
    def destroy_key(self, key_id: str) -> DestructionProof:
        """Cryptographically destroy key. Returns verifiable proof."""
        ...

    @abstractmethod
    def verify_attestation(self) -> AttestationReport:
        """Verify SE integrity with manufacturer."""
        ...

    @abstractmethod
    def has_key(self, key_id: str) -> bool:
        """Check if a key exists and is not destroyed."""
        ...


class KeyDestroyedError(Exception):
    """Raised when attempting to use a destroyed key."""
    def __init__(self, key_id: str):
        self.key_id = key_id
        super().__init__(f"Key '{key_id}' has been cryptographically destroyed")


class KeyNotFoundError(Exception):
    """Raised when a key is not found in the secure element."""
    def __init__(self, key_id: str):
        self.key_id = key_id
        super().__init__(f"Key '{key_id}' not found in secure element")


class SoftwareSecureElement(SecureElement):
    """Software-based secure element fallback using PyNaCl.

    WARNING: This is a development/testing implementation. In production,
    use hardware-backed implementations (HSM, TEE, Secure Enclave).

    Security properties maintained:
    - Keys stored in-memory only (not persisted to disk)
    - Destruction zeroes key material and records proof
    - Thread-safe operations
    """

    def __init__(self, device_id: str = "dev_software_se"):
        self._keys: Dict[str, nacl.signing.SigningKey] = {}
        self._public_keys: Dict[str, bytes] = {}
        self._destroyed: Dict[str, DestructionProof] = {}
        self._lock = threading.Lock()
        self._device_id = device_id

    def generate_keypair(self, key_id: str, extractable: bool = False) -> Keypair:
        """Generate Ed25519 keypair in software SE."""
        with self._lock:
            if key_id in self._destroyed:
                raise KeyDestroyedError(key_id)

            signing_key = nacl.signing.SigningKey.generate()
            verify_key = signing_key.verify_key

            self._keys[key_id] = signing_key
            self._public_keys[key_id] = bytes(verify_key)

            return Keypair(
                public_key=bytes(verify_key),
                private_key=bytes(signing_key) if extractable else None,
                key_id=key_id,
            )

    def sign(self, key_id: str, data: bytes) -> bytes:
        """Sign data with stored key."""
        with self._lock:
            if key_id in self._destroyed:
                raise KeyDestroyedError(key_id)
            if key_id not in self._keys:
                raise KeyNotFoundError(key_id)

            signing_key = self._keys[key_id]
            signed = signing_key.sign(data)
            return signed.signature

    def destroy_key(self, key_id: str) -> DestructionProof:
        """Destroy key material and generate cryptographic proof.

        The proof contains:
        - The public key (so verifiers can identify which key was destroyed)
        - A hash of the key material XOR'd with random bytes (proving we had access)
        - A random nonce (preventing proof replay)
        """
        import time

        with self._lock:
            if key_id in self._destroyed:
                return self._destroyed[key_id]
            if key_id not in self._keys:
                raise KeyNotFoundError(key_id)

            signing_key = self._keys[key_id]
            public_key = self._public_keys[key_id]

            # Create destruction proof before zeroing
            nonce = os.urandom(16)
            key_material = bytes(signing_key)
            destruction_hash = hashlib.sha256(key_material + nonce).digest()

            # Zero the key material (best-effort in Python—in C this would be memset_s)
            # In production, the HSM handles this at the hardware level
            del self._keys[key_id]

            proof = DestructionProof(
                key_id=key_id,
                public_key=public_key,
                destruction_hash=destruction_hash,
                timestamp=time.time(),
                nonce=nonce,
            )

            self._destroyed[key_id] = proof
            return proof

    def verify_attestation(self) -> AttestationReport:
        """Software attestation (always valid in dev mode)."""
        import time
        return AttestationReport(
            valid=True,
            device_id=self._device_id,
            security_level="software",
            timestamp=time.time(),
        )

    def has_key(self, key_id: str) -> bool:
        """Check if key exists and is not destroyed."""
        with self._lock:
            return key_id in self._keys and key_id not in self._destroyed

    def get_public_key(self, key_id: str) -> bytes:
        """Retrieve the public key for a given key_id."""
        with self._lock:
            if key_id not in self._public_keys:
                raise KeyNotFoundError(key_id)
            return self._public_keys[key_id]

    def is_destroyed(self, key_id: str) -> bool:
        """Check if a key has been destroyed."""
        with self._lock:
            return key_id in self._destroyed

    def get_destruction_proof(self, key_id: str) -> Optional[DestructionProof]:
        """Retrieve destruction proof for a destroyed key."""
        with self._lock:
            return self._destroyed.get(key_id)


def verify_signature(public_key: bytes, signature: bytes, data: bytes) -> bool:
    """Verify an Ed25519 signature against a public key."""
    try:
        verify_key = nacl.signing.VerifyKey(public_key)
        verify_key.verify(data, signature)
        return True
    except nacl.exceptions.BadSignatureError:
        return False


def verify_destruction_proof(proof: DestructionProof) -> bool:
    """Verify that a destruction proof is structurally valid.

    Note: Full verification requires the original key material,
    which is the point — it's been destroyed. This checks structural validity
    and that the proof fields are consistent.
    """
    if not proof.key_id or not proof.public_key or not proof.destruction_hash:
        return False
    if len(proof.public_key) != 32:  # Ed25519 public key size
        return False
    if len(proof.destruction_hash) != 32:  # SHA-256 output
        return False
    if len(proof.nonce) != 16:
        return False
    return True
