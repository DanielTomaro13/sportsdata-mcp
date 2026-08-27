"""Entain's placement tool — Ladbrokes and Neds, the third book that can move money.

Captured live 2026-08-27 from real bets (a single and a three-leg same game multi, both
HTTP 200 with status "accepted"). The account holder placed them; the agent did not.

    POST api.ladbrokes.com.au/v2/betting/place-bet    entain_place_bet

Entain sits between the other two on safety. It reports MORE about what happened than
either — `accepted_stake` and `placed_odds` both come back, so stake reduction and price
drift are visible from the placement response alone. But its `transaction_id` is RETURNED
rather than sent, so unlike TAB there is no idempotency key and a timed-out placement
cannot be safely asked about.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from sportsdata_mcp.registry import _annotations_for
from sportsdata_mcp.spec_loader import load_spec

SPEC = Path(__file__).resolve().parents[2] / "src/sportsdata_mcp/specs/entain.yaml"


@pytest.fixture(scope="module")
def spec():
    return load_spec(SPEC)


@pytest.fixture(scope="module")
def ep(spec):
    return next(e for e in spec.endpoints if e.name == "entain_place_bet")


def test_placing_is_alone_in_the_write_group(spec):
    assert [e.name for e in spec.endpoints if e.group == "entain.write"] == ["entain_place_bet"]


def test_placing_is_destructive(ep):
    a = _annotations_for(ep)
    assert a.readOnlyHint is False and a.destructiveHint is True


def test_the_hint_says_the_status_code_is_not_the_verdict(ep):
    """Entain answers HTTP 200 and puts the outcome in `status`. A plane reading the code
    would treat a refused bet as placed."""
    hint = ep.response_hint or ""
    assert "HTTP 200 IS NOT THE ANSWER" in hint
    assert "'accepted'" in hint


def test_the_hint_says_to_check_the_accepted_stake(ep):
    """Entain states the stake it actually took, and a book may take less than asked. This
    is the field neither Sportsbet nor TAB surfaces so plainly, and ignoring it means
    reporting a bet larger than the one that exists."""
    hint = ep.response_hint or ""
    assert "accepted_stake` AGAINST WHAT YOU SENT" in hint
    assert "take less than asked" in hint


def test_the_hint_says_to_check_the_odds_actually_struck(ep):
    hint = ep.response_hint or ""
    assert "placed_odds" in hint
    assert "drift is detectable" in hint


def test_the_hint_distinguishes_a_receipt_from_an_idempotency_key(ep):
    """TAB's transactionId is SENT and can be safely resent; Entain's transaction_id is
    RETURNED and cannot. Confusing the two would produce a retry that places a second real
    bet — the exact failure TAB's key exists to prevent."""
    hint = ep.response_hint or ""
    assert "RETURNED, not sent" in hint
    assert "NOT an idempotency key" in hint
    assert "never retry" in hint


def test_the_sgm_shape_is_recorded_as_legs_plus_a_prices_block(ep):
    """The confusable part: a same game multi is several legs PLUS a `prices` object keyed
    by EVENT id carrying the combined price. A single has no `prices` block at all."""
    d = next(p for p in ep.params if p.name == "bets").description or ""
    assert "keyed by EVENT ID" in d
    assert "a single carries no `prices` block" in d


def test_the_leg_ids_are_the_same_ones_the_pricer_uses(ep):
    """market_id and entrant_id come from entain_sport_event_card, exactly as
    entain_sgm_price needs — so the resolver written for pricing serves placing too."""
    d = next(p for p in ep.params if p.name == "bets").description or ""
    assert "entain_sgm_price" in d and "entain_sport_event_card" in d


# ─── auth ───────────────────────────────────────────────────────────────


def test_the_account_tier_is_a_public_client_on_the_refresh_grant(spec):
    a = spec.provider.auth["account"]
    assert a.grant == "refresh_token"
    assert a.refresh_token_env == "ENTAIN_REFRESH_TOKEN"
    assert a.client_id_env is None and a.client_secret_env is None
    assert a.optional is True


def test_the_unverified_token_endpoint_is_flagged_as_such(spec):
    """Honesty guard. Entain's token endpoint was NOT observed — no discovery document was
    reachable — so `token_url` is a guess. If this comment is ever removed without the
    endpoint being confirmed, a refresh will fail in a way that looks like a dead
    credential rather than a wrong URL."""
    text = SPEC.read_text()
    i = text.index("ENTAIN_REFRESH_TOKEN")
    block = text[max(0, i - 1800):i]
    assert "has NOT been observed" in block
    assert "unverified" in block


def test_only_the_placement_uses_the_account_tier(spec):
    """Every other Entain tool is anonymous and must stay that way."""
    assert {e.name for e in spec.endpoints if e.auth == "account"} == {"entain_place_bet"}
