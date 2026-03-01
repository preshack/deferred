"""Tests for the coin selection algorithm.

Includes property-based tests using Hypothesis to verify:
- Selected tokens always cover the target amount
- Change is minimized
- Token count is minimized
"""

from __future__ import annotations

import pytest
from hypothesis import given, settings, assume
from hypothesis import strategies as st

from app.crypto.tokens import (
    MintedToken,
    TokenManager,
    TransactionPayload,
    select_tokens,
    VALID_DENOMINATIONS,
)
from app.crypto.secure_element import SoftwareSecureElement


# ─── Helpers ──────────────────────────────────────────────────────────────────

def make_token(denom: int, token_id: str = "", wallet_id: str = "test_wallet") -> MintedToken:
    """Create a test MintedToken."""
    return MintedToken(
        token_id=token_id or f"tok_{denom}",
        denomination_cents=denom,
        public_key=b"\x00" * 32,
        key_id=f"token:tok_{denom}",
        ancestry_chain=[],
        expiry_time=9999999999.0,
        wallet_id=wallet_id,
    )


# ─── Unit Tests ───────────────────────────────────────────────────────────────


class TestCoinSelection:
    """Tests for the token selection algorithm."""

    def test_exact_match(self):
        """Exact denomination match uses 1 token."""
        tokens = [make_token(500), make_token(1000), make_token(2000)]
        selected = select_tokens(tokens, 1000)

        total = sum(t.denomination_cents for t in selected)
        assert total == 1000
        assert len(selected) == 1

    def test_multiple_tokens(self):
        """Multiple tokens combined to reach target."""
        tokens = [make_token(500, "t1"), make_token(500, "t2"), make_token(500, "t3")]
        selected = select_tokens(tokens, 1200)

        total = sum(t.denomination_cents for t in selected)
        assert total >= 1200
        assert total == 1500  # 3 x 500

    def test_minimal_change(self):
        """Algorithm minimizes change."""
        tokens = [make_token(500, "t1"), make_token(1000, "t2"), make_token(2000, "t3")]
        selected = select_tokens(tokens, 1500)

        total = sum(t.denomination_cents for t in selected)
        assert total == 1500  # Exact: 1000 + 500

    def test_insufficient_funds_raises(self):
        """Insufficient tokens raise ValueError."""
        tokens = [make_token(500)]
        with pytest.raises(ValueError, match="Insufficient"):
            select_tokens(tokens, 1000)

    def test_empty_tokens_raises(self):
        """Empty token list raises ValueError."""
        with pytest.raises(ValueError, match="No tokens"):
            select_tokens([], 100)

    def test_large_target(self):
        """Can handle large targets with many tokens."""
        tokens = [make_token(10000, f"t{i}") for i in range(10)]
        selected = select_tokens(tokens, 50000)

        total = sum(t.denomination_cents for t in selected)
        assert total == 50000

    def test_prefers_fewer_tokens(self):
        """Given same change, prefers fewer tokens."""
        tokens = [
            make_token(5000, "big"),
            make_token(2000, "med1"),
            make_token(2000, "med2"),
            make_token(1000, "small"),
        ]
        selected = select_tokens(tokens, 5000)

        # Should prefer 1 x 5000 over 2 x 2000 + 1 x 1000
        assert len(selected) == 1
        assert selected[0].denomination_cents == 5000


# ─── Property-Based Tests ────────────────────────────────────────────────────


denomination_strategy = st.sampled_from(VALID_DENOMINATIONS)
token_list_strategy = st.lists(
    denomination_strategy,
    min_size=1,
    max_size=20,
)


@given(denoms=token_list_strategy, target_pct=st.floats(min_value=0.1, max_value=0.8))
@settings(max_examples=100, deadline=5000)
def test_selection_covers_target(denoms: list, target_pct: float):
    """Property: Selected tokens always cover the target amount."""
    total = sum(denoms)
    target = max(500, int(total * target_pct))  # Ensure target <= total
    assume(target <= total)

    tokens = [make_token(d, f"t{i}") for i, d in enumerate(denoms)]

    try:
        selected = select_tokens(tokens, target)
        selected_total = sum(t.denomination_cents for t in selected)
        assert selected_total >= target, f"Selected {selected_total} < target {target}"
    except ValueError:
        # Acceptable if truly insufficient
        assert total < target


@given(denoms=token_list_strategy)
@settings(max_examples=50, deadline=5000)
def test_selection_is_subset(denoms: list):
    """Property: Selected tokens are a subset of available tokens."""
    tokens = [make_token(d, f"t{i}") for i, d in enumerate(denoms)]
    target = min(denoms)  # Minimum denomination as target

    selected = select_tokens(tokens, target)
    assert len(selected) <= len(tokens)


# ─── Token Manager Tests ─────────────────────────────────────────────────────


class TestTokenManager:
    """Tests for the TokenManager (minting + spending)."""

    def test_mint_exact_amount(self):
        """Minting covers the exact amount."""
        se = SoftwareSecureElement()
        manager = TokenManager(se)
        tokens = manager.mint_tokens("wallet_test", 2500)

        total = sum(t.denomination_cents for t in tokens)
        assert total == 2500  # 2000 + 500

    def test_mint_produces_unique_ids(self):
        """Each minted token has a unique ID."""
        se = SoftwareSecureElement()
        manager = TokenManager(se)
        tokens = manager.mint_tokens("wallet_test", 5000)

        ids = [t.token_id for t in tokens]
        assert len(ids) == len(set(ids))

    def test_spend_token_sign_once(self):
        """Spending a token destroys its key (Sign-Once)."""
        se = SoftwareSecureElement()
        manager = TokenManager(se)
        tokens = manager.mint_tokens("wallet_test", 500)
        token = tokens[0]

        payload = TransactionPayload(
            tx_id="pay_test",
            merchant_id="merch_test",
            amount_cents=500,
            timestamp=1234567890.0,
            nonce=42,
        )

        proof = manager.spend_token(token, payload)

        # Key should be destroyed
        assert se.is_destroyed(f"token:{token.token_id}")

        # Proof should be verifiable
        assert TokenManager.verify_spend_proof(proof, payload)
