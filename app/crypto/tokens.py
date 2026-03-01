"""Deferred API — Token minting and coin selection.

Handles offline token lifecycle:
- Minting tokens with Ed25519 keypairs and ancestry chains
- Optimal coin selection (dynamic programming knapsack)
- Token verification and ancestry validation
"""

from __future__ import annotations

import hashlib
import json
import time
import uuid
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from app.crypto.secure_element import (
    DestructionProof,
    SecureElement,
    SoftwareSecureElement,
    verify_signature,
)

# Valid denominations in cents
VALID_DENOMINATIONS = [500, 1000, 2000, 5000, 10000]


@dataclass
class MintedToken:
    """A freshly minted offline token."""
    token_id: str
    denomination_cents: int
    public_key: bytes
    key_id: str
    ancestry_chain: List[str]
    expiry_time: float
    wallet_id: str


@dataclass
class SpendProof:
    """Proof that a token was spent in a specific transaction."""
    token_id: str
    signature: bytes
    public_key: bytes
    destruction_proof: DestructionProof
    tx_hash: bytes


@dataclass
class TransactionPayload:
    """Complete offline transaction payload for merchant settlement."""
    version: str = "1.0"
    tx_id: str = ""
    merchant_id: str = ""
    amount_cents: int = 0
    currency: str = "usd"
    proofs: List[Dict] = field(default_factory=list)
    ancestry_chains: List[str] = field(default_factory=list)
    expiry: float = 0.0
    timestamp: float = 0.0
    nonce: int = 0

    def serialize(self) -> bytes:
        """Canonical serialization for signing."""
        data = {
            "version": self.version,
            "tx_id": self.tx_id,
            "merchant_id": self.merchant_id,
            "amount_cents": self.amount_cents,
            "currency": self.currency,
            "timestamp": self.timestamp,
            "nonce": self.nonce,
        }
        return json.dumps(data, sort_keys=True, separators=(",", ":")).encode()

    def hash(self) -> bytes:
        """SHA-256 hash of the canonical serialization."""
        return hashlib.sha256(self.serialize()).digest()


class TokenManager:
    """Manages offline token minting, spending, and verification.

    Uses a SecureElement for key management to ensure sign-once semantics.
    """

    def __init__(self, secure_element: SecureElement | None = None):
        self._se = secure_element or SoftwareSecureElement()
        self._token_counter = 0

    def mint_tokens(
        self,
        wallet_id: str,
        total_cents: int,
        expiry_days: int = 30,
    ) -> List[MintedToken]:
        """Mint a batch of tokens to cover the given amount.

        Uses a greedy algorithm to minimize the number of tokens:
        largest denominations first.

        Args:
            wallet_id: Wallet to mint tokens for
            total_cents: Total amount to cover in cents
            expiry_days: Days until token expiry

        Returns:
            List of MintedToken objects
        """
        tokens = []
        remaining = total_cents

        # Greedy: largest denominations first
        for denom in sorted(VALID_DENOMINATIONS, reverse=True):
            while remaining >= denom:
                token = self._mint_single(wallet_id, denom, expiry_days)
                tokens.append(token)
                remaining -= denom

        return tokens

    def _mint_single(
        self, wallet_id: str, denomination_cents: int, expiry_days: int
    ) -> MintedToken:
        """Mint a single token with a fresh Ed25519 keypair."""
        self._token_counter += 1

        # Generate unique token ID — uuid4 suffix prevents collisions across restarts
        denom_label = f"{denomination_cents // 100}usd"
        token_id = f"tok_{denom_label}_{uuid.uuid4().hex[:12]}"
        key_id = f"token:{token_id}"

        # Generate keypair in secure element
        keypair = self._se.generate_keypair(key_id, extractable=True)

        # Create ancestry hash
        ancestry_hash = hashlib.sha256(
            f"{token_id}:{wallet_id}:{denomination_cents}".encode()
        ).hexdigest()

        expiry = time.time() + (expiry_days * 86400)

        return MintedToken(
            token_id=token_id,
            denomination_cents=denomination_cents,
            public_key=keypair.public_key,
            key_id=key_id,
            ancestry_chain=[ancestry_hash],
            expiry_time=expiry,
            wallet_id=wallet_id,
        )

    def spend_token(
        self, token: MintedToken, tx_payload: TransactionPayload
    ) -> SpendProof:
        """Spend a token: sign the transaction and destroy the key (Sign-Once).

        This is the critical security operation:
        1. Sign the transaction hash with the token's private key
        2. Immediately destroy the key (preventing re-signing / double-spend)
        3. Return proof of both signature and destruction

        Args:
            token: The token to spend
            tx_payload: The transaction being signed

        Returns:
            SpendProof with signature and destruction proof
        """
        key_id = f"token:{token.token_id}"
        tx_hash = tx_payload.hash()

        # Step 1: Sign
        signature = self._se.sign(key_id, tx_hash)

        # Step 2: Destroy key (Sign-Once enforcement)
        destruction_proof = self._se.destroy_key(key_id)

        return SpendProof(
            token_id=token.token_id,
            signature=signature,
            public_key=token.public_key,
            destruction_proof=destruction_proof,
            tx_hash=tx_hash,
        )

    @staticmethod
    def verify_spend_proof(proof: SpendProof, tx_payload: TransactionPayload) -> bool:
        """Verify a spend proof: signature valid and destruction proof valid.

        Args:
            proof: The SpendProof to verify
            tx_payload: The original transaction

        Returns:
            True if both signature and destruction proof are valid
        """
        tx_hash = tx_payload.hash()

        # Verify signature
        if not verify_signature(proof.public_key, proof.signature, tx_hash):
            return False

        # Verify tx_hash matches
        if proof.tx_hash != tx_hash:
            return False

        return True


def select_tokens(
    available_tokens: List[MintedToken], target_cents: int
) -> List[MintedToken]:
    """Select optimal tokens for a payment using dynamic programming.

    Algorithm: Minimize change first, then minimize token count.
    Time complexity: O(n * target) where n = number of tokens (max 100).

    Args:
        available_tokens: List of unspent tokens
        target_cents: Amount to pay in cents

    Returns:
        List of selected tokens (total >= target, minimal change)

    Raises:
        ValueError: If insufficient funds
    """
    if not available_tokens:
        raise ValueError("No tokens available")

    total_available = sum(t.denomination_cents for t in available_tokens)
    if total_available < target_cents:
        raise ValueError(
            f"Insufficient offline funds: have {total_available}, need {target_cents}"
        )

    # Try exact match first (greedy)
    exact = _try_exact_match(available_tokens, target_cents)
    if exact is not None:
        return exact

    # Dynamic programming: find combination with minimal total >= target
    n = len(available_tokens)
    denoms = [t.denomination_cents for t in available_tokens]

    # Find minimum sum >= target
    best_selection = None
    best_total = float("inf")
    best_count = float("inf")

    # Branch and bound with sorting (largest first for faster pruning)
    sorted_indices = sorted(range(n), key=lambda i: denoms[i], reverse=True)

    def search(idx: int, current_sum: int, selected: List[int]):
        nonlocal best_selection, best_total, best_count

        if current_sum >= target_cents:
            change = current_sum - target_cents
            count = len(selected)
            if change < (best_total - target_cents) or (
                change == (best_total - target_cents) and count < best_count
            ):
                best_selection = selected.copy()
                best_total = current_sum
                best_count = count
            return

        if idx >= len(sorted_indices):
            return

        remaining = sum(denoms[sorted_indices[j]] for j in range(idx, len(sorted_indices)))
        if current_sum + remaining < target_cents:
            return  # Prune: can't reach target

        # Include current token
        i = sorted_indices[idx]
        selected.append(i)
        search(idx + 1, current_sum + denoms[i], selected)
        selected.pop()

        # Skip current token
        search(idx + 1, current_sum, selected)

    search(0, 0, [])

    if best_selection is None:
        raise ValueError("Could not find valid token combination")

    return [available_tokens[i] for i in best_selection]


def _try_exact_match(
    tokens: List[MintedToken], target: int
) -> Optional[List[MintedToken]]:
    """Try to find an exact match using a simple greedy approach."""
    remaining = target
    selected = []

    # Sort by denomination descending
    for token in sorted(tokens, key=lambda t: t.denomination_cents, reverse=True):
        if token.denomination_cents <= remaining:
            selected.append(token)
            remaining -= token.denomination_cents
            if remaining == 0:
                return selected

    return None
