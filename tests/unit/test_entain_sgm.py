"""Entain's SGM pricer — best diagnostics of the six, and it will quote a bet that cannot win.

Verified live 2026-08-27 against AFL Melbourne v Carlton (event
eccdc4f5-e01e-4aca-afab-570869b53702), unauthenticated. Melbourne (2.15) with Over 173.5
(1.88) prices 3.70, against a naive 4.042.

Two things make this book unlike the other five.

When it detects a clash it is the most informative refusal in the catalogue —
`{available: false, conflicting_selections: [...]}` names the exact offending pair, where
every other book gives a sentence at best. But the detector is not complete: on a sample
of 22 two-entrant markets from the verified event, four had their mutually exclusive pair
priced as AVAILABLE, at 70 to 146. A bet that cannot win, quoted at 146.51, is
indistinguishable from a longshot with enormous edge.

And its prices are FRACTIONAL, where decimal = numerator/denominator + 1. Dropping the
+1 understates every price, which is the quiet direction to be wrong in — nothing looks
alarming, the book just appears to be pricing worse than it is.

Shape tests, not live calls: these ids belong to one fixture and expire with it.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from sportsdata_mcp.spec_loader import load_spec

SPEC = Path(__file__).resolve().parents[2] / "src/sportsdata_mcp/specs/entain.yaml"


@pytest.fixture(scope="module")
def spec():
    return load_spec(SPEC)


@pytest.fixture(scope="module")
def sgm(spec):
    return next(e for e in spec.endpoints if e.name == "entain_sgm_price")


def test_the_whole_envelope_travels_in_one_query_param(sgm):
    """Entain's gateway takes a JSON document in the query string, which is how the rest of
    this spec's filters work too. Splitting it into friendlier eventId/selections params
    would need the engine to synthesise one provider's envelope shape, and would throw away
    the batch the map exists for."""
    params = [p for p in sgm.params]
    assert [p.name for p in params] == ["same_game_multies"]
    assert params[0].in_ == "query" and params[0].type == "json" and params[0].required


def test_the_hint_gives_the_fractional_conversion(sgm):
    """decimal = numerator/denominator + 1. `27/10` is 3.70, not 2.7 and not 27."""
    hint = sgm.response_hint or ""
    assert "numerator/denominator + 1" in hint
    assert "`27/10` is 3.70" in hint
    assert "23/20" in hint and "2.15" in hint, "the check against a displayed price is the proof"


def test_the_hint_says_the_price_is_not_the_product(sgm):
    hint = sgm.response_hint or ""
    assert "NOT THE PRODUCT" in hint.upper()
    assert "4.042" in hint and "3.70" in hint


def test_the_hint_warns_that_impossible_bets_get_quoted(sgm):
    """The finding that makes this book dangerous. Four of 22 two-entrant markets sampled
    priced their mutually exclusive pair as available, at 70 to 146."""
    hint = sgm.response_hint or ""
    assert "IMPOSSIBLE COMBINATIONS ARE QUOTED" in hint
    assert "146.51" in hint, "the number is what stops this reading as a theoretical risk"
    assert "22 two-entrant markets" in hint, "the sample size keeps the claim honest"


def test_the_hint_warns_about_silent_collapse(sgm):
    """A redundant leg is dropped, the price becomes the shorter bet's, and `available`
    stays true with no leg echo to notice it by."""
    hint = sgm.response_hint or ""
    assert "SILENTLY COLLAPSES A REDUNDANT LEG" in hint
    assert "RESTATE THE SELECTIONS YOU SENT" in hint


def test_the_hint_credits_conflicting_selections(sgm):
    """Worth naming because it is genuinely the best of the six and a caller who does not
    know it exists will fall back to guessing which leg was wrong."""
    hint = sgm.response_hint or ""
    assert "conflicting_selections" in hint


def test_the_hint_says_a_missing_odds_key_is_not_zero(sgm):
    """An unknown event answers `available: false` with no `odds` at all, quietly, next to
    the events that did price. There is no fake zero here — but inventing one on read is
    the same bug from the other end."""
    hint = sgm.response_hint or ""
    assert "must never be read as 0" in hint


def test_the_duplicated_event_id_is_documented_as_load_bearing(sgm):
    """The map key and the inner `event_id` look redundant and are not: a mismatch is a
    400. Anyone tidying one of them away breaks every call."""
    desc = next(p for p in sgm.params if p.name == "same_game_multies").description or ""
    assert "MUST BE THE SAME STRING" in desc
    assert "not redundant" in desc


def test_the_ids_name_the_tool_they_come_from(sgm):
    desc = next(p for p in sgm.params if p.name == "same_game_multies").description or ""
    assert "entain_sport_event_card" in desc
    assert "entrants" in desc and "markets" in desc


def test_the_batch_shape_is_documented(sgm):
    """The map is not decoration — several events price in one call, each answered
    independently. A friendlier single-event parameter would have quietly removed that."""
    desc = next(p for p in sgm.params if p.name == "same_game_multies").description or ""
    assert "More than one event may be priced in a single call" in desc


def test_entain_declares_no_error_signal(spec):
    """Malformed requests are real 400s and refusals carry no number at all, so there is no
    fake price to guard against. A signal on `available` would fire on every legitimately
    unavailable event in a batch."""
    assert spec.provider.error_signals == []
