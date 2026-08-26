"""TAB's SGM pricer — and the redundancy trap that makes it different from Sportsbet's.

Verified live 2026-08-28 against AFL Wst Bulldogs v Collingwood: H2H Bulldogs (1.95) plus
Naughton first goal (11.00) priced 15.00 — not 21.45, because TAB applies a correlation
adjustment. Adding the Bulldogs +1.5 line, which the H2H win already implies, returned
the SAME 15.00 with that leg marked `redundant`.

Shape tests, not live calls: the proposition ids belong to one match and expire with it.
What they pin is the knowledge that cost the most to obtain.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from sportsdata_mcp.registry import _annotations_for, _build_body
from sportsdata_mcp.spec_loader import load_spec

SPEC = Path(__file__).resolve().parents[2] / "src/sportsdata_mcp/specs/tab.yaml"


@pytest.fixture(scope="module")
def sgm():
    return next(e for e in load_spec(SPEC).endpoints if e.name == "tab_sgm_price")


def test_it_is_a_post_that_changes_nothing(sgm):
    assert sgm.method == "POST"
    assert _annotations_for(sgm).readOnlyHint is True


def test_the_jurisdiction_nests_into_clientDetails(sgm):
    """TAB puts a required scalar two levels down. Expressing that needs a dotted WIRE
    name — a dot is illegal in a Python identifier, so it cannot be the parameter name.
    Without this the model would have to hand-build the whole envelope to pass one string."""
    j = next(p for p in sgm.params if p.name == "jurisdiction")
    assert j.wire_name == "clientDetails.jurisdiction"
    body = _build_body(sgm, {"jurisdiction": "VIC", "channel": "web", "bets": [1],
                             "returnValidationMatrix": True})
    assert body["clientDetails"] == {"jurisdiction": "VIC", "channel": "web"}
    assert body["bets"] == [1]
    assert "clientDetails.jurisdiction" not in body


def test_jurisdiction_is_required_because_prices_differ_by_state(sgm):
    j = next(p for p in sgm.params if p.name == "jurisdiction")
    assert j.required
    assert "NSW" in (j.description or "")


def test_the_hint_says_the_price_is_not_the_product(sgm):
    """The single most important thing about an SGM. A model that multiplies the legs
    reports 21.45 for a bet that pays 15.00."""
    hint = sgm.response_hint or ""
    assert "NOT THE PRODUCT" in hint.upper()
    assert "21.45" in hint and "15.00" in hint, "the worked example is what makes it land"


def test_the_hint_warns_about_redundant_legs(sgm):
    """TAB does not refuse a leg that another leg implies — it DROPS it, prices what is
    left, and returns the same odds. So a three-leg request can silently become a
    two-leg bet at an unchanged price. Verified live: adding a +1.5 line behind an H2H
    win left the price at 15.00 with the line marked redundant."""
    hint = sgm.response_hint or ""
    assert "redundantPropositions" in hint
    assert "COLLAPSED, NOT REFUSED" in hint.upper() or "collapsed" in hint.lower()
    assert "may not be the bet you asked for" in hint


def test_the_hint_points_at_the_sameGame_eligibility_flag(sgm):
    """Only some markets combine — 52 of 109 on the verified match. Trying the others
    wastes a call and returns a refusal that does not explain itself."""
    assert "sameGame" in (sgm.response_hint or "")


def test_the_validation_matrix_defaults_on(sgm):
    """It is what turns an opaque refusal into one you can act on."""
    v = next(p for p in sgm.params if p.name == "returnValidationMatrix")
    assert v.default is True


def test_the_example_is_a_real_captured_two_leg_multi(sgm):
    params = sgm.examples[0].params
    legs = params["bets"][0]["legs"][0]
    assert legs["type"] == "SAME_GAME_MULTI"
    assert len(legs["propositions"]) >= 2, "TAB needs at least two"
    for prop in legs["propositions"]:
        assert set(prop) == {"type", "propositionId"}
        assert isinstance(prop["propositionId"], int), "ids are integers, not strings"


def test_tab_and_sportsbet_pricers_are_both_present_and_differ():
    """Two books, two entirely different contracts — fractional vs decimal, external ids
    vs proposition ids, silent redundancy vs hard refusal. The cross-book comparator this
    enables is only meaningful because the shapes were each verified separately."""
    tab = next(e for e in load_spec(SPEC).endpoints if e.name == "tab_sgm_price")
    sb_spec = SPEC.parent / "sportsbet.yaml"
    sb = next(e for e in load_spec(sb_spec).endpoints if e.name == "sportsbet_sgm_price")
    assert tab.method == sb.method == "POST"
    assert "decimal" in (tab.response_hint or "")
    assert "numerator" in (sb.response_hint or "")
