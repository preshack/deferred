"""Deferred API — Shamir's Secret Sharing.

Implements k-of-n secret sharing over GF(2^8) for wallet recovery.
The master seed is split into n shares, any k of which can reconstruct it.
"""

from __future__ import annotations

import os
import secrets
from dataclasses import dataclass
from typing import List, Tuple

# ─── GF(2^8) Arithmetic ──────────────────────────────────────────────────────
# Uses irreducible polynomial x^8 + x^4 + x^3 + x + 1 = 0x11B

_EXP_TABLE = [0] * 512
_LOG_TABLE = [0] * 256


def _build_tables():
    """Build exp and log lookup tables for GF(2^8).
    
    Uses generator 3 (primitive element for polynomial 0x11B).
    NOTE: Generator 2 has order 51, NOT 255, so we MUST use generator 3.
    
    Multiplication by 3 in GF(2^8): x*3 = x*2 XOR x (since 3 = 2+1 in GF(2^8))
    Multiplication by 2 (xtime): shift left, XOR with 0x1B if overflow.
    """
    x = 1
    for i in range(255):
        _EXP_TABLE[i] = x
        _LOG_TABLE[x] = i
        # Multiply x by generator 3: x*3 = x*2 XOR x
        # First compute x*2 (xtime)
        x2 = (x << 1) & 0xFF
        if x & 0x80:
            x2 ^= 0x1B
        # x*3 = x*2 XOR x
        x = x2 ^ x

    # Repeat for easy mod-255 via direct indexing
    # (LOG[a] + LOG[b] can reach up to 254 + 254 = 508)
    for i in range(255, 512):
        _EXP_TABLE[i] = _EXP_TABLE[i - 255]


_build_tables()


def _gf_mul(a: int, b: int) -> int:
    """Multiply in GF(2^8)."""
    if a == 0 or b == 0:
        return 0
    return _EXP_TABLE[(_LOG_TABLE[a] + _LOG_TABLE[b]) % 255]


def _gf_div(a: int, b: int) -> int:
    """Divide in GF(2^8)."""
    if b == 0:
        raise ZeroDivisionError
    if a == 0:
        return 0
    return _EXP_TABLE[(_LOG_TABLE[a] - _LOG_TABLE[b]) % 255]


def _gf_inv(a: int) -> int:
    """Multiplicative inverse in GF(2^8)."""
    if a == 0:
        raise ZeroDivisionError("Cannot invert zero in GF(2^8)")
    return _EXP_TABLE[255 - _LOG_TABLE[a]]


# ─── Share Data ───────────────────────────────────────────────────────────────

@dataclass
class Share:
    """A single share of a split secret."""
    x: int  # Share index (1-255)
    y: bytes  # Share data (same length as secret)

    def to_hex(self) -> str:
        """Serialize share as hex string: xx:yy..."""
        return f"{self.x:02x}:{self.y.hex()}"

    @classmethod
    def from_hex(cls, hex_str: str) -> Share:
        """Deserialize share from hex string."""
        parts = hex_str.split(":", 1)
        return cls(x=int(parts[0], 16), y=bytes.fromhex(parts[1]))


# ─── Core Algorithm ──────────────────────────────────────────────────────────

def _eval_at(coeffs: list, x: int) -> int:
    """Evaluate polynomial at x in GF(2^8).

    coeffs[0] is the constant term (the secret byte).
    f(x) = coeffs[0] + coeffs[1]*x + coeffs[2]*x^2 + ...
    """
    result = 0
    x_power = 1  # x^0 = 1
    for coeff in coeffs:
        result ^= _gf_mul(coeff, x_power)
        x_power = _gf_mul(x_power, x)
    return result


def _lagrange_interpolate(shares: List[Tuple[int, int]]) -> int:
    """Lagrange interpolation at x=0 in GF(2^8).

    shares: list of (x_i, y_i) pairs
    returns: f(0)
    """
    k = len(shares)
    result = 0

    for i in range(k):
        xi, yi = shares[i]

        # Compute Lagrange basis L_i(0) = ∏_{j≠i} (0 - x_j)/(x_i - x_j)
        # In GF(2^8): -a = a, a - b = a ⊕ b
        # So L_i(0) = ∏_{j≠i} x_j / (x_i ⊕ x_j)
        numerator = 1
        denominator = 1
        for j in range(k):
            if i == j:
                continue
            xj = shares[j][0]
            numerator = _gf_mul(numerator, xj)
            denominator = _gf_mul(denominator, xi ^ xj)

        li = _gf_div(numerator, denominator)
        result ^= _gf_mul(yi, li)

    return result



class ShamirSecretSharing:
    """Shamir's Secret Sharing over GF(2^8).

    Split a secret into n shares where any k shares can reconstruct it.

    Security properties:
    - Fewer than k shares reveal zero information about the secret
    - Each share is the same size as the secret
    - Uses GF(2^8) arithmetic (no modular arithmetic overflow issues)
    """

    @staticmethod
    def split(secret: bytes, k: int, n: int) -> List[Share]:
        """Split a secret into n shares with threshold k.

        Args:
            secret: The secret to split (any length)
            k: Minimum shares required for reconstruction (2 <= k <= n)
            n: Total number of shares to generate (k <= n <= 255)

        Returns:
            List of n Share objects

        Raises:
            ValueError: If k or n are out of valid range
        """
        if k < 2:
            raise ValueError("Threshold k must be >= 2")
        if n < k:
            raise ValueError("Total shares n must be >= threshold k")
        if n > 255:
            raise ValueError("Maximum 255 shares supported (GF(2^8) limitation)")

        # Ensure unique x-coordinates (1 through n)
        shares_y = [bytearray(len(secret)) for _ in range(n)]

        for byte_idx in range(len(secret)):
            # Random polynomial coefficients: f(x) = secret[byte_idx] + a1*x + ... + a_{k-1}*x^{k-1}
            coeffs = [secret[byte_idx]] + [secrets.randbelow(256) for _ in range(k - 1)]

            for share_idx in range(n):
                x = share_idx + 1  # x = 1, 2, ..., n
                shares_y[share_idx][byte_idx] = _eval_at(coeffs, x)

        return [Share(x=i + 1, y=bytes(shares_y[i])) for i in range(n)]

    @staticmethod
    def reconstruct(shares: List[Share]) -> bytes:
        """Reconstruct the secret from k or more shares using Lagrange interpolation.

        Args:
            shares: At least k shares (the threshold used during splitting)

        Returns:
            The reconstructed secret

        Raises:
            ValueError: If shares are invalid or insufficient
        """
        if len(shares) < 2:
            raise ValueError("Need at least 2 shares")

        # Verify all shares have the same length
        lengths = {len(s.y) for s in shares}
        if len(lengths) != 1:
            raise ValueError("All shares must have the same length")

        # Verify unique x values
        x_values = [s.x for s in shares]
        if len(set(x_values)) != len(x_values):
            raise ValueError("Duplicate share indices detected")

        secret_length = len(shares[0].y)
        result = bytearray(secret_length)

        for byte_idx in range(secret_length):
            points = [(s.x, s.y[byte_idx]) for s in shares]
            result[byte_idx] = _lagrange_interpolate(points)

        return bytes(result)

    @staticmethod
    def verify_shares(shares: List[Share], k: int) -> bool:
        """Verify that a set of shares is self-consistent.

        Takes multiple shares and checks that different k-subsets reconstruct the same secret.

        Args:
            shares: List of shares to verify
            k: Threshold

        Returns:
            True if shares are consistent
        """
        if len(shares) < k:
            return False

        # Reconstruct with first k shares
        reference = ShamirSecretSharing.reconstruct(shares[:k])

        # Verify with different subsets
        for i in range(min(len(shares) - k, 3)):
            subset = shares[i + 1: i + 1 + k]
            if len(subset) < k:
                break
            result = ShamirSecretSharing.reconstruct(subset)
            if result != reference:
                return False

        return True
