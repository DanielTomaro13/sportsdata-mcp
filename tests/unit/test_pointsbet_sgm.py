"""PointsBet's SGM pricer — and the two traps that make it the most dangerous of the three.

Verified live 2026-08-27 against AFL Western Bulldogs v Collingwood (event 2860313), all
of it unauthenticated:

  * Match Result Bulldogs (1.96) + Total Over 169.5 (1.90)  -> 3.60, not 3.724.
  * Match Result Bulldogs (1.96) + Bulldogs +1.5 (1.90)     -> 1.96 FLAT. The line leg is
    implied by the head-to-head, so PointsBet prices it at nothing while a naive multiply
    says 3.724 — a 47% overstatement of a real bet.

The second one is the trap. PointsBet returns a bare price and NO leg echo, so the
collapsed two-leg quote is byte-identical in shape to an honest one. TAB at least marks
dropped legs `redundant`; here there is nothing to check. Everything below exists so that
knowledge cannot quietly fall out of the spec.

Shape tests, not live calls: these market keys belong to one fixture and expire with it.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from sportsdata_mcp.http_client import HTTPClient
from sportsdata_mcp.registry import _annotations_for, _build_body
from sportsdata_mcp.spec_loader import load_spec

SPEC = Path(__file__).resolve().parents[2] / "src/sportsdata_mcp/specs/pointsbet.yaml"


@pytest.fixture(scope="module")
def spec():
    return load_spec(SPEC)


@pytest.fixture(scope="module")
def sgm(spec):
    return next(e for e in spec.endpoints if e.name == "pointsbet_sgm_price")


def test_it_is_a_post_that_changes_nothing(sgm):
    assert sgm.method == "POST"
    assert _annotations_for(sgm).readOnlyHint is True


def test_the_body_is_pascal_case_on_the_wire(sgm):
    """The site sends EventKey/SelectedOutcomes. The binder happens to accept camelCase
    today, which is exactly why the spec should not rely on it — a tightened model binder
    would turn a working tool into a 400 with no code change on our side."""
    body = _build_body(sgm, {"eventKey": "2860313",
                             "selectedOutcomes": [{"MarketKey": "1", "OutcomeKey": "2"}]})
    assert body == {"EventKey": "2860313",
                    "SelectedOutcomes": [{"MarketKey": "1", "OutcomeKey": "2"}]}


def test_the_event_key_is_a_string(sgm):
    """It is an identifier, not a quantity. Sending it as an int works, but typing it as
    one invites arithmetic on it somewhere downstream."""
    assert next(p for p in sgm.params if p.name == "eventKey").type == "string"


def test_both_params_are_required(sgm):
    assert all(p.required for p in sgm.params)


def test_the_hint_says_the_price_is_not_the_product(sgm):
    """The single most important thing about an SGM. A model that multiplies the legs
    quotes 3.724 for a bet that pays 3.60 — or 3.724 for one that pays 1.96."""
    hint = sgm.response_hint or ""
    assert "NOT THE PRODUCT" in hint.upper()
    assert "3.724" in hint and "3.60" in hint, "the worked example is what makes it land"


def test_the_hint_warns_that_collapse_is_undetectable(sgm):
    """PointsBet's specific hazard: legs are absorbed and the response does not say so.
    Anything that reports a price without restating the legs it asked for is unsafe."""
    hint = (sgm.response_hint or "").upper()
    assert "COLLAPSED" in hint
    assert "1.96" in (sgm.response_hint or ""), "the flat-price example is the proof"
    assert "TAB" in hint, "the contrast with a book that DOES echo is what sets expectations"


def test_the_hint_says_the_eligibility_flag_lies(sgm):
    """`enableCorrelatedMulti` was true on all 82 markets of the verified event while the
    pricer still refused First Goalscorer. Pre-filtering on it promises combinations that
    do not exist."""
    hint = sgm.response_hint or ""
    assert "enableCorrelatedMulti" in hint
    assert "First Goalscorer" in hint


def test_the_outcome_key_is_documented_as_market_scoped(sgm):
    """OutcomeKey "11" is a different bet in the Line market than in the Total market on
    the verified event. Carrying one to the wrong MarketKey prices something else and
    still returns success."""
    d = next(p for p in sgm.params if p.name == "selectedOutcomes").description or ""
    assert "ONLY UNIQUE WITHIN ITS MARKET" in d.upper()
    assert "fixedOddsMarkets" in d, "the id chain must name the tool the keys come from"


def test_the_event_tool_points_at_the_sgm_keys(spec):
    """pointsbet_sgm_price is unusable without knowing where its two ids live. The event
    hint is the only place that chain is written down."""
    hint = next(e for e in spec.endpoints if e.name == "pointsbet_event").response_hint or ""
    assert "pointsbet_sgm_price" in hint
    assert "MarketKey" in hint and "OutcomeKey" in hint


def test_the_refusal_signal_is_declared_and_narrow(spec):
    """A refusal is HTTP 200 with `price: 0`. Without the signal that zero reaches the
    caller in the field they asked for. `equals` keeps it to exactly false — no other
    PointsBet endpoint carries a top-level `success`, and presence-mode would fire on the
    successes too."""
    signals = spec.provider.error_signals
    assert [(s.field, s.equals) for s in signals] == [("success", "False")]


def test_a_refusal_names_the_legs_that_caused_it(spec):
    """"Selection Suspended" is useless when you sent ten selections. PointsBet puts the
    offending ones in a sibling field, and an error that drops them turns a recoverable
    failure — remove that leg, re-price — into a dead end."""
    from sportsdata_mcp.config import Config
    from sportsdata_mcp.errors import ToolError

    http = HTTPClient(spec.provider, Config())
    body = {"success": False, "price": 0, "message": "Selection Suspended",
            "invalidSelections": [{"marketKey": "999999999", "outcomeKey": "1"}]}
    with pytest.raises(ToolError) as e:
        http._raise_on_error_signal(body)
    assert "Selection Suspended" in str(e.value)
    assert "999999999" in str(e.value), "the caller cannot act without knowing which leg"


def test_the_zero_price_is_never_echoed_into_the_error(spec):
    """The one number that must not appear in a refusal is the fake quote itself."""
    from sportsdata_mcp.config import Config
    from sportsdata_mcp.errors import ToolError

    http = HTTPClient(spec.provider, Config())
    with pytest.raises(ToolError) as e:
        http._raise_on_error_signal(
            {"success": False, "price": 0, "message": "OddsFactory returned price 1 or less",
             "invalidSelections": None})
    assert "price=" not in str(e.value)


def test_a_successful_price_is_not_mistaken_for_an_error(spec):
    """`success: true` must pass straight through — a signal that fires on the happy path
    is worse than no signal."""
    from sportsdata_mcp.config import Config

    http = HTTPClient(spec.provider, Config())
    http._raise_on_error_signal(
        {"success": True, "price": 3.6, "message": None, "invalidSelections": None})
