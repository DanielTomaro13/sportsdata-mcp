"""Unibet's Bet Builder pricer — the best-behaved of the five, and the one with a 1000x trap.

Verified live 2026-08-27 against AFL Western Bulldogs v Collingwood (Kambi event
1028856020), unauthenticated: head-to-head Bulldogs (1.92) with Over 170.5 (1.88) prices
3.40 against a naive 3.6096.

Unibet is the safe one for a reason worth stating plainly: it is the ONLY book of the five
that echoes back exactly what it priced (`selectedOutcomeIds`), and the only one that
answers a refusal with a real HTTP status code and a typed body instead of a 200 carrying
a zero. Sportsbet, TAB, PointsBet and BetR all needed an `error_signals` declaration; this
one must not have any.

Against that it has the single loudest wrong answer available anywhere in the catalogue:
Kambi reports odds in THOUSANDTHS. `decimal: 3400` is 3.40. Reporting it as 3400 is a
1000x error in the number a person would bet on.

Shape tests, not live calls: these ids belong to one fixture and expire with it.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from sportsdata_mcp.registry import _interpolate_path
from sportsdata_mcp.spec_loader import load_spec

SPEC = Path(__file__).resolve().parents[2] / "src/sportsdata_mcp/specs/unibet.yaml"


@pytest.fixture(scope="module")
def spec():
    return load_spec(SPEC)


@pytest.fixture(scope="module")
def sgm(spec):
    return next(e for e in spec.endpoints if e.name == "unibet_sgm_price")


def test_the_legs_go_in_the_path_comma_joined(sgm):
    """Kambi takes the whole combination as one path segment, which is why `outcomeIds` is
    a STRING and not a list — a list param would be query-encoded and never reach it."""
    assert sgm.path == "/onDemandPricing/event/{eventId}/outcome/{outcomeIds}.json"
    assert next(p for p in sgm.params if p.name == "outcomeIds").type == "string"
    url = _interpolate_path(sgm, {"eventId": 1028856020, "outcomeIds": "4306981996,4309057043"})
    assert url == "/onDemandPricing/event/1028856020/outcome/4306981996,4309057043.json"


def test_it_is_a_plain_get(sgm):
    """Every other book's pricer is a POST. This one is a GET, which means it caches and
    retries like any other read — worth not "fixing" into a POST for symmetry."""
    assert sgm.method == "GET"


def test_the_hint_shouts_about_milli_odds(sgm):
    """The 1000x error. `decimal: 3400` is 3.40, and a model that reports 3400 has produced
    the most wrong number this catalogue can produce."""
    hint = sgm.response_hint or ""
    assert "THOUSANDTHS" in hint
    assert "3400" in hint and "3.40" in hint
    assert "Divide by 1000" in hint


def test_the_hint_says_the_price_is_not_the_product(sgm):
    hint = sgm.response_hint or ""
    assert "NOT THE PRODUCT" in hint.upper()
    assert "3.6096" in hint and "3.40" in hint


def test_the_hint_warns_that_1001_is_a_cap(sgm):
    """Six, eight, ten, twelve and fourteen legs all returned exactly 1001000 while the
    naive product kept climbing. A capped price read as a real one looks like enormous
    edge, which is the worst possible way to be wrong about a long multi."""
    hint = sgm.response_hint or ""
    assert "1001.0 IS A CEILING" in hint
    assert "1001000" in hint


def test_the_hint_names_the_echo_and_the_silent_dedupe(sgm):
    """`selectedOutcomeIds` is the property that makes this book safe, and it is also the
    only way to notice that duplicate ids were collapsed."""
    hint = sgm.response_hint or ""
    assert "selectedOutcomeIds" in hint
    assert "deduplicated SILENTLY" in hint


def test_the_hint_says_a_missing_price_is_not_zero(sgm):
    """One leg returns a body with no `selectedOdds` key at all — not an error, not a zero.
    Code that reaches for the price without checking gets a KeyError, and code that uses
    .get() reports nothing at all."""
    hint = sgm.response_hint or ""
    assert "SINGLE LEG RETURNS NO PRICE" in hint
    assert "not zero" in hint


def test_the_hint_distinguishes_eligibility_from_compatibility(sgm):
    """`combinableOutcomeIds` reads like "what can go with this" and is not. It kept both
    the opposite head-to-head side and the line the head-to-head implies, and both then
    400ed."""
    hint = sgm.response_hint or ""
    assert "ELIGIBILITY, NOT COMPATIBILITY" in hint
    assert "1137" in hint, "the 940-of-1137 figure is what shows it filters SOMETHING"


def test_the_event_book_is_projected_away(sgm):
    """The upstream repeats all 626 bet offers — 647 KB of a 610 KB response — which
    event_betoffer already serves. Without the projection this tool cannot fit under any
    response cap, and it would be paying that to return data the caller already has."""
    assert sgm.response_pick == [
        "eventId", "selectedOutcomeIds", "selectedOdds", "combinableOutcomeIds"]
    assert "betOffers" not in sgm.response_pick


def test_the_hint_separates_the_four_refusal_codes(sgm):
    """They are not interchangeable and the difference is actionable: an INELIGIBLE leg is
    fixed by picking a different market, a CLASHING pair by dropping one leg, and a 409 by
    abandoning the combination entirely. Found live when a perfectly ordinary betoffer
    outcome came back `Invalid outcomes` because it was not bet-builder eligible."""
    hint = sgm.response_hint or ""
    assert "409" in hint and "Impossible outcome selection" in hint
    assert "not BET-BUILDER ELIGIBLE" in hint
    assert "`invalidOutcomes` EMPTY" in hint, (
        "the empty list on a 409 looks like a bug and is not — the combination is at "
        "fault, not any single id")


def test_unibet_declares_no_error_signal(spec):
    """The other four books answer a refusal with HTTP 200 and a zero in the price field,
    so they need one. Kambi returns a real 400 with a typed body. Adding a signal here
    would be cargo-culting the shape of the other specs onto a provider that does not have
    the problem."""
    assert spec.provider.error_signals == []


def test_the_leg_ids_name_the_tool_they_come_from(sgm):
    """Outcome ids are meaningless without the feed that issues them, and Kambi's are
    behind a dispatcher operation rather than a tool of their own."""
    desc = next(p for p in sgm.params if p.name == "outcomeIds").description or ""
    assert "event_betoffer" in desc
    assert "betOffers[].outcomes[].id" in desc


def test_market_is_documented_as_load_bearing(sgm):
    """Bet Builder availability and pricing are per market, so `market` is not cosmetic
    even though it has a default."""
    desc = next(p for p in sgm.params if p.name == "market").description or ""
    assert "per market" in desc


def test_it_is_tagged_for_cross_book_comparison(sgm):
    """The whole point of these five tools is that one capability query returns all of
    them. An untagged pricer is invisible to that."""
    assert set(sgm.capabilities) == {"sport.same_game_multi", "sport.prices"}
