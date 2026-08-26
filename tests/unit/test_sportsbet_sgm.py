"""Sportsbet's SGM pricer — the one tool here that prices a combination YOU chose.

Every other SGM tool in this catalogue takes an event id and returns combinations the
BOOK already built. This one takes legs and returns a correlated price, which is the
entire product. Verified live 2026-08-25 against AFL Western Bulldogs v Collingwood:
two legs priced 7/5, three legs 10/3, one leg refused.

These are shape tests, not live calls — the example's event ids belong to one match and
would 404 within days. What they pin is the knowledge that was expensive to obtain.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from sportsdata_mcp.registry import _annotations_for
from sportsdata_mcp.spec_loader import load_spec

SPEC = Path(__file__).resolve().parents[2] / "src/sportsdata_mcp/specs/sportsbet.yaml"


@pytest.fixture(scope="module")
def sgm():
    spec = load_spec(SPEC)
    return next(e for e in spec.endpoints if e.name == "sportsbet_sgm_price")


def test_it_is_a_post_that_changes_nothing(sgm):
    """A pricing call travelling by POST is the same case as a GraphQL query: declaring
    it read-only keeps clients from demanding confirmation for a quote request."""
    assert sgm.method == "POST"
    assert _annotations_for(sgm).readOnlyHint is True
    assert _annotations_for(sgm).destructiveHint in (None, False)


def test_it_asks_for_EXTERNAL_ids_everywhere(sgm):
    """The trap that cost the most time. Sportsbet exposes TWO id spaces, and every
    other tool in this spec speaks the internal one. The pricer wants `externalId`
    throughout — market 602153262 not 251983151, selection 2870628954 not 1244168027 —
    and passing the wrong one returns a bare `ERR-VE` that names no field."""
    names = {p.name for p in sgm.params}
    assert names == {
        "classExternalId", "competitionExternalId", "eventExternalId", "outcomesExternalIds",
    }
    for p in sgm.params:
        assert p.required, f"{p.name} is required — the pricer rejects a partial body"
        assert "externalId" in (p.description or "") or "external id" in (p.description or "").lower(), (
            f"{p.name}'s description must say where the EXTERNAL id comes from"
        )


def test_the_legs_are_a_json_array_not_a_csv(sgm):
    """`outcomesExternalIds` is a list of objects; typing it `object` would force a model
    to wrap the array, which is the failure already seen live on Entain."""
    legs = next(p for p in sgm.params if p.name == "outcomesExternalIds")
    assert legs.type == "json"
    assert legs.in_ == "body"


def test_the_hint_explains_that_the_price_is_fractional(sgm):
    """`{numerator: 7, denominator: 5}` is $2.40, not 1.4 and not 7.5. A model that reads
    it as decimal reports a price 40% under and would call a bad SGM good."""
    hint = sgm.response_hint or ""
    assert "numerator" in hint and "denominator" in hint
    assert "1 + numerator/denominator" in hint or "Decimal =" in hint
    assert "2.40" in hint, "the worked example is what makes the formula unambiguous"


def test_the_hint_warns_the_quote_expires(sgm):
    """quoteId is a per-request token. Treating a price from ten minutes ago as current
    is the difference between a real edge and an imagined one."""
    hint = (sgm.response_hint or "").lower()
    assert "quoteid" in hint
    assert "quote" in hint and ("re-request" in hint or "not a cached fact" in hint)


def test_the_hint_names_the_two_error_codes(sgm):
    """Both were observed live and neither is guessable: ERR-MP-001 is "fewer than two
    outcomes", ERR-VE is a schema rejection that names no field."""
    hint = sgm.response_hint or ""
    assert "ERR-MP-001" in hint
    assert "ERR-VE" in hint


def test_the_example_is_a_real_captured_combination(sgm):
    """Two legs, both external ids, from one event — the shape a caller must copy."""
    params = sgm.examples[0].params
    assert params["classExternalId"] == 103          # Australian Rules
    assert params["competitionExternalId"] == 17131  # AFL
    legs = params["outcomesExternalIds"]
    assert len(legs) >= 2, "the pricer refuses a single leg"
    for leg in legs:
        assert set(leg) == {"marketExternalId", "outcomeExternalId"}


def test_it_is_the_only_sportsbet_tool_that_prices_a_chosen_combination():
    """Guards the distinction the whole exercise turned on: the other SGM tools return
    what the book pre-built, and are not substitutes for this."""
    spec = load_spec(SPEC)
    sgm_tools = [e for e in spec.endpoints if "sport.same_game_multi" in (e.capabilities or [])]
    posts = [e for e in sgm_tools if e.method == "POST"]
    assert [e.name for e in posts] == ["sportsbet_sgm_price"]
    trending = next(e for e in sgm_tools if e.name == "sportsbet_trending_sgm")
    assert trending.method == "GET", "trending returns pre-built combinations, not a quote"
