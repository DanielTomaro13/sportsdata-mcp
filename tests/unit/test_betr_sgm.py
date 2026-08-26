"""BetR's SGM pricer — the only one of the four that trusts a price you send it.

Verified live 2026-08-27 against AFL Western Bulldogs v Collingwood (MasterEventId
2255977), unauthenticated, on the same fixture the other three books were verified on:

  * Bulldogs (1.95) + Over 139.5 (1.10)   -> 2.20  (naive 2.145, +2.6%)
  * Bulldogs (1.95) + Under 139.5 (6.25)  -> 11.00 (naive 12.19, -9.7%)
  * Bulldogs (1.95) + Under 201.5 (1.10)  -> 2.25  (naive 2.145, +4.9%)

BetR is the well-behaved one in one respect and the worst in another. It REFUSES a
redundant leg (4527) instead of silently dropping it, so you can never end up holding a
shorter bet than you asked for — the failure mode TAB and PointsBet both have. But it
takes a `FixedWin` from the client and uses it as a floor on the answer, so a wrong price
in the request comes back as a wrong price in the response with ErrorNo 0. The site sends
that field; this spec deliberately does not.

Shape tests, not live calls: these ids belong to one fixture and expire with it.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from sportsdata_mcp.config import Config
from sportsdata_mcp.errors import ToolError
from sportsdata_mcp.http_client import HTTPClient
from sportsdata_mcp.registry import _annotations_for, _build_body
from sportsdata_mcp.spec_loader import load_spec

SPEC = Path(__file__).resolve().parents[2] / "src/sportsdata_mcp/specs/betr.yaml"


@pytest.fixture(scope="module")
def spec():
    return load_spec(SPEC)


@pytest.fixture(scope="module")
def sgm(spec):
    return next(e for e in spec.endpoints if e.name == "betr_sgm_price")


def test_it_is_a_post_that_changes_nothing(sgm):
    assert sgm.method == "POST"
    assert _annotations_for(sgm).readOnlyHint is True


def test_the_body_keeps_betrs_own_casing(sgm):
    """`MasterEventID` has a capital D that `MasterEventId` elsewhere in this spec does
    not. It happens to be ignored either way, but guessing at casing is not a habit worth
    forming on the fields that are NOT ignored."""
    body = _build_body(sgm, {"MasterEventID": 2255977,
                             "Markets": [{"EventId": 1, "OutcomeId": 2, "MarketType": "WIN"}]})
    assert body == {"MasterEventID": 2255977,
                    "Markets": [{"EventId": 1, "OutcomeId": 2, "MarketType": "WIN"}]}


def test_only_the_legs_are_required(sgm):
    """MasterEventID is ignored by the server, so requiring it would be theatre."""
    assert next(p for p in sgm.params if p.name == "Markets").required
    assert not next(p for p in sgm.params if p.name == "MasterEventID").required


def test_the_hint_says_the_price_is_not_the_product(sgm):
    """The single most important thing about an SGM."""
    hint = sgm.response_hint or ""
    assert "NOT THE PRODUCT" in hint.upper()
    assert "12.19" in hint and "11.00" in hint, "the worked example is what makes it land"
    assert "-9.7%" in hint and "+4.9%" in hint, "the adjustment goes BOTH ways here"


def test_the_hint_forbids_sending_fixedwin(sgm):
    """The one field that turns this endpoint from a pricer into an echo. Sending 99.0
    returns {Price: 99.0, ErrorNo: 0} — a fabricated quote reported as a clean success."""
    hint = sgm.response_hint or ""
    assert "DO NOT SEND `FixedWin`" in hint
    assert "99.0" in hint, "the demonstration is the argument"
    desc = next(p for p in sgm.params if p.name == "Markets").description or ""
    assert "FixedWin" in desc, "the warning has to be where the legs are built, too"


def test_the_hint_says_markettype_fails_silently(sgm):
    """Dropping MarketType turned a correct 2.20 into 21 with ErrorNo 0. A field that is
    required-but-unvalidated is more dangerous than one that errors."""
    desc = next(p for p in sgm.params if p.name == "Markets").description or ""
    assert "LOAD-BEARING AND FAILS SILENTLY" in desc
    assert "2.20 into 21" in desc


def test_the_hint_says_4527_is_a_catch_all(sgm):
    """It reads as "redundant leg" and also covers a duplicate leg and legs from two
    different matches. Taking the message literally sends you looking for the wrong bug."""
    hint = sgm.response_hint or ""
    assert "CATCH-ALL" in hint
    assert "DIFFERENT matches" in hint


def test_the_hint_records_the_two_leg_minimum(sgm):
    """Sportsbet and PointsBet both price a single leg; BetR returns 4500. Worth stating,
    because "just price one leg" is the obvious way to test whether a market is eligible
    and it does not work here."""
    assert "4500" in (sgm.response_hint or "")


def test_master_event_id_is_documented_as_ignored(sgm):
    """It looks like the thing that scopes the legs to one match and it is not — omitting
    it, zeroing it and misspelling it all returned the same price. Anything relying on it
    as a guard is relying on nothing."""
    desc = next(p for p in sgm.params if p.name == "MasterEventID").description or ""
    assert "IGNORED BY THE SERVER" in desc


def test_the_leg_ids_name_the_tool_they_come_from(sgm):
    """EventId here is a MARKET GROUP, not the match — the single most confusable thing in
    this provider's id space."""
    desc = next(p for p in sgm.params if p.name == "Markets").description or ""
    assert "betr_master_event" in desc
    assert "MARKET GROUP, not the match" in desc


def test_the_refusal_signal_is_declared_in_presence_mode(spec):
    """ErrorNo is 0 on every success, so the falsy case IS the success case and presence
    mode fits exactly. An `equals` here would have to enumerate 4500/4503/4526/4527 and
    would silently pass any code BetR adds later."""
    assert [(s.field, s.equals) for s in spec.provider.error_signals] == [("ErrorNo", None)]


def test_a_zero_errorno_is_not_an_error(spec):
    """A signal that fires on the happy path is worse than no signal."""
    HTTPClient(spec.provider, Config())._raise_on_error_signal({"Price": 2.2, "ErrorNo": 0})


def test_a_refusal_reports_betrs_message_not_its_number(spec):
    """BetR spells it `Message`. The detail lookup used to be lowercase-only, which would
    have reduced "Same Game Multi must have at least two legs" to a bare 4500."""
    http = HTTPClient(spec.provider, Config())
    with pytest.raises(ToolError) as e:
        http._raise_on_error_signal(
            {"Price": 0, "ErrorNo": 4500, "Message": "Same Game Multi must have at least two legs"})
    assert "at least two legs" in str(e.value)


def test_the_zero_price_is_never_echoed_into_the_error(spec):
    """The one number that must not appear in a refusal is the fake quote itself."""
    http = HTTPClient(spec.provider, Config())
    with pytest.raises(ToolError) as e:
        http._raise_on_error_signal(
            {"Price": 0, "ErrorNo": 4527, "Message": "Invalid price response - redundant leg in bet"})
    assert "Price=" not in str(e.value)
