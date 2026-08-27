"""Unibet's placement plane — the fourth book that can move money, and the odd one out.

Unibet runs on Kambi, so its contract is Kambi's, not Unibet's, and it differs from the
other three books on every axis:

    POST cf-al-auth-api.kambicdn.com/player/api/v2019/ubau/coupon/validate.json   (anon)
    POST cf-al-auth-api.kambicdn.com/player/api/v2019/ubau/coupon.json            (account)

  * Auth is `Authorization: Bearer <uuid>` from UNIBET_ACCESS_TOKEN — OBSERVED on a live
    authenticated request. This file first asserted a session COOKIE, which was an
    inference that went unchecked because the capture recorder redacted the very header
    that would have disproved it.
  * Pricing/validation is ANONYMOUS: validate.json answered 400 (not 401) cross-origin
    with no credential, so the go/no-go check needs no login.
  * An SGM is ONE couponRow, operation "AND", type "BET_BUILDER"; the stake lives in
    bets[] and is what separates a placement from a validation.
  * Validate DOES NOT echo a price, so it cannot be used to check drift.

Captured 2026-08-27 from a real 2-leg SGM placement (the account holder placed it; the
agent recorded the request). The request SHAPE is verbatim; a headless placement was NOT
round-tripped, and the spec says so.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from sportsdata_mcp.spec_loader import load_spec

SPEC = Path(__file__).resolve().parents[2] / "src/sportsdata_mcp/specs/unibet.yaml"


@pytest.fixture(scope="module")
def spec():
    return load_spec(SPEC)


@pytest.fixture(scope="module")
def place(spec):
    return next(e for e in spec.endpoints if e.name == "unibet_place_bet")


@pytest.fixture(scope="module")
def validate(spec):
    return next(e for e in spec.endpoints if e.name == "unibet_validate_coupon")


# ─── the write gate ───────────────────────────────────────────────────────


def test_placing_is_alone_in_the_write_group(spec):
    assert [e.name for e in spec.endpoints if e.group == "unibet.write"] == ["unibet_place_bet"]


def test_placement_is_a_post(place):
    # A POST is never cached, so — like sportsbet/tab/entain place_bet — no never_cache flag.
    assert place.method == "POST"
    assert place.never_cache is False


def test_placement_uses_the_account_tier(place):
    assert place.auth == "account"


def test_placement_hits_the_player_api_not_the_offering_api(place, spec):
    # `player/` is the authenticated write host; `offering/` is the anonymous read feed.
    assert place.base == "kambi_player"
    assert "player/api" in place.path and "coupon.json" in place.path
    assert spec.provider.base_urls["kambi_player"] == "https://cf-al-auth-api.kambicdn.com"


# ─── validation is the anonymous go/no-go ──────────────────────────────────


def test_validate_is_read_only_and_anonymous(validate):
    # Proven live: validate answered 400 (not 401) with no session cookie, so it prices
    # without login and must NOT be forced onto the account tier.
    assert validate.read_only is True
    assert validate.auth == "default"
    assert validate.method == "POST"


def test_validate_and_place_share_the_coupon_body(place, validate):
    pb = next(p for p in place.params if p.name == "body").description or ""
    vb = next(p for p in validate.params if p.name == "body").description or ""
    for token in ("couponRows", "bets", "outcomeIds", "stake"):
        assert token in pb, token
        assert token in vb, token


# ─── the account tier: bearer, not cookie ──────────────────────────────────


def test_the_account_tier_is_a_bearer_token_not_a_cookie(spec):
    """OBSERVED on a live authenticated request 2026-08-27: `Authorization: Bearer <uuid>`.

    This spec first said the credential was a session COOKIE on .kambicdn.com — inferred
    from finding no bearer in Unibet's storage, never checked against the request, because
    the capture recorder redacted exactly the header that would have settled it. Kambi is
    cross-origin, so a browser would not have sent cookies there at all."""
    a = spec.provider.auth["account"]
    assert a.type == "static_header"
    assert a.header == "Authorization"
    assert a.value_prefix == "Bearer "
    assert a.env == "UNIBET_ACCESS_TOKEN"
    # optional so an unset env degrades to anonymous (Kambi 401s) rather than breaking
    # startup for everyone who has not configured it.
    assert a.optional is True


# ─── honesty guards ────────────────────────────────────────────────────────


def test_shape_verified_but_headless_placement_flagged(place):
    """The request is real; the headless round-trip is not. If this caveat is removed
    without a controlled live placement confirming the cookie alone satisfies Kambi, a
    reader will over-trust the tool."""
    hint = place.response_hint or ""
    assert "HEADLESS placement has NOT been round-tripped" in hint
    assert "REQUEST SHAPE IS REAL" in hint


def test_the_shared_body_check_covers_the_stake_difference(place, validate):
    """validate carries no stake; placement does. That is the difference between a
    question and a bet."""
    vb = next(p for p in validate.params if p.name == "body").description or ""
    assert "does NOT carry" in vb or "no `stake`" in vb


def test_no_retry_on_timeout_like_the_other_books(place):
    hint = place.response_hint or ""
    assert "NEVER retry" in hint
    assert "read" in hint.lower()  # confirm-by-account-read


def test_kambi_odds_are_thousandths_in_the_body_help(place):
    # 3300 = 3.30 — the loudest wrong answer here is a price 1000x too large.
    d = next(p for p in place.params if p.name == "body").description or ""
    assert "THOUSANDTHS" in d and "3300" in d


def test_the_coupon_operation_and_type_are_the_verified_strings(place):
    """"AND" / "BET_BUILDER", read off a live request. The first version of this spec
    guessed "COMBINATION" for both, which Kambi would not have recognised."""
    d = next(p for p in place.params if p.name == "body").description or ""
    assert '"AND"' in d and '"BET_BUILDER"' in d


def test_validate_does_not_echo_a_price_and_says_so(validate):
    """The reply is {status, validSession, rewardInfo} — no couponRows. A drift check
    that re-reads the price from here refuses every placement, which is what the betting
    plane did until this was measured."""
    hint = validate.response_hint or ""
    assert "DOES NOT ECHO A PRICE" in hint
    assert "unibet_sgm_price" in hint          # names the call that CAN re-price


def test_validate_success_is_the_string_SUCCESS(validate):
    hint = validate.response_hint or ""
    assert "SUCCESS" in hint and "validSession" in hint
