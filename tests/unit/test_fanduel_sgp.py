"""FanDuel's Same Game Parlay pricer — a betting-transaction endpoint used read-only.

Verified live 2026-08-27 against NBA Boston Celtics @ Detroit Pistons (event 35928218):
legs at 2.02 and 1.87 price as a parlay at 3.41275716, against a naive 3.7765 — a 9.6%
correlation charge.

THIS ONE IS DIFFERENT FROM THE OTHER SIX and the difference is the reason for the tests
below. Every other pricer in this catalogue is a read endpoint that happens to quote a
combination. FanDuel has no such endpoint: `implyBets` is its BETSLIP service, and every
combination it returns carries a `betReference` — a signed token that is the input to
actually placing the bet — plus stake ceilings and bonus-wallet state.

The tool is therefore read-only by construction rather than by luck: `response_fields`
drops the token and everything else that belongs to placement, so what reaches a caller
is the price, the legs it applies to, and the reason for any refusal. A test below asserts
the token cannot come back, because that is the invariant, not a preference.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from sportsdata_mcp.project import apply_projection
from sportsdata_mcp.registry import _annotations_for, _build_body, _build_query
from sportsdata_mcp.spec_loader import load_spec

SPEC = Path(__file__).resolve().parents[2] / "src/sportsdata_mcp/specs/fanduel.yaml"

#: One combination exactly as the upstream returns it, trimmed of nothing. Used to prove
#: the projection strips what it claims to.
UPSTREAM_COMBINATION = {
    "betType": "DOUBLE",
    "legCombinations": [{"legType": "SIMPLE_SELECTION", "runners": [{"marketId": "734.1", "selectionId": 1}],
                         "outcomes": [], "legGroup": "1"}],
    "canPlaceEachwayBet": False,
    "numLines": 1,
    "betMinStake": 0.09,
    "betMaxStake": 5750,
    "averageOdds": 3.41,
    "winAvgOdds": {"trueOdds": {"decimalOdds": {"decimalOdds": 3.41275716}}},
    "applicablePromotions": [],
    "hasCashout": True,
    "combinationGroup": 1,
    "isSGM": True,
    "features": ["SGM"],
    "betMaxPayout": 5000000,
    "betMinStakeIncrement": 0.01,
    "bonusWalletConditions": [],
    "hasBonusMoney": False,
    "betReference": "ysQb/+oqJfOqNWBqUhzbb5CVzjfkEOF2Hlir8uTkG5UMU+7j+YjsepJM3X3+dxrV",
    "extraCharges": [],
}


@pytest.fixture(scope="module")
def spec():
    return load_spec(SPEC)


@pytest.fixture(scope="module")
def sgp(spec):
    return next(e for e in spec.endpoints if e.name == "fanduel_sgp_price")


def test_it_is_a_post_that_places_nothing(sgp):
    assert sgp.method == "POST"
    assert _annotations_for(sgp).readOnlyHint is True


def test_the_placement_token_cannot_reach_a_caller(sgp):
    """The invariant. `betReference` is what you would POST to place this bet; it must
    never enter model context. Run against a real upstream combination rather than a
    hand-made one, so a field rename upstream shows up here."""
    out = apply_projection({"betCombinations": [UPSTREAM_COMBINATION]},
                           pick=sgp.response_pick, fields=sgp.response_fields)
    kept = out["betCombinations"][0]
    assert "betReference" not in kept
    for banned in ("betMinStake", "betMaxStake", "betMaxPayout", "betMinStakeIncrement",
                   "bonusWalletConditions", "hasBonusMoney", "applicablePromotions",
                   "hasCashout", "canPlaceEachwayBet", "extraCharges"):
        assert banned not in kept, f"{banned} survived the projection"


def test_the_projection_keeps_what_the_price_is_made_of(sgp):
    """Stripping is only correct if the answer survives it."""
    kept = apply_projection({"betCombinations": [UPSTREAM_COMBINATION]},
                            pick=sgp.response_pick, fields=sgp.response_fields)["betCombinations"][0]
    assert kept["isSGM"] is True
    assert kept["winAvgOdds"]["trueOdds"]["decimalOdds"]["decimalOdds"] == 3.41275716
    assert kept["legCombinations"], "the legs the price applies to must survive"
    assert kept["features"] == ["SGM"]


def test_the_web_key_defaults_and_is_documented_as_load_bearing(sgp):
    """Without `_ak` the call still returns 200 and prices the SINGLES while silently
    omitting the same-game combination — the one thing the caller asked for. Verified
    live. The default is what makes the tool work; the description is what stops someone
    "cleaning up" an unused-looking parameter."""
    p = next(x for x in sgp.params if x.name == "web_key")
    assert p.wire_name == "_ak"
    assert p.default == "FhMFpcPWXMeyZxOx"
    assert "WITHOUT `_ak`" in (p.description or "")
    assert _build_query(sgp, {"web_key": p.default}) == {"_ak": "FhMFpcPWXMeyZxOx"}


def test_the_body_is_passed_through_as_betLegs(sgp):
    legs = [{"legType": "SIMPLE_SELECTION",
             "betRunners": [{"runner": {"marketId": "734.1", "selectionId": 1}}]}]
    assert _build_body(sgp, {"betLegs": legs}) == {"betLegs": legs}


def test_the_double_nesting_of_betRunners_is_documented(sgp):
    """`betRunners[].runner` — writing `runners` or a bare runner object binds to nothing
    and returns 200 with an empty `betRunners`, so it fails silently. This cost real time
    to find and the description is the only place it is recorded."""
    d = next(x for x in sgp.params if x.name == "betLegs").description or ""
    assert "DOUBLE NESTING" in d
    assert "binds to NOTHING" in d


def test_the_hint_says_which_entry_is_the_parlay(sgp):
    """A two-leg request returns three combinations. Taking the first gives you a single
    bet at 2.02 while believing you have a parlay at 3.41."""
    hint = sgp.response_hint or ""
    assert "isSGM: true" in hint or "`isSGM: true`" in hint
    assert "ONLY ONE THAT IS A SAME GAME PARLAY" in hint


def test_the_hint_says_to_use_true_odds_not_the_rounded_display(sgp):
    """3.41 vs 3.41275716. Rounded odds compared against another book's exact ones
    manufacture edge that is not there — which is the entire failure mode of a
    cross-book comparator."""
    hint = sgp.response_hint or ""
    assert "trueOdds" in hint and "3.41275716" in hint


def test_the_hint_defuses_INVALID_COMBINATION(sgp):
    """It appears next to a perfectly good SGM entry and means the legs cannot form an
    ORDINARY multi — which is the point of an SGP. Read as failure, it would make every
    successful call look broken."""
    hint = sgp.response_hint or ""
    assert "INVALID_COMBINATION" in hint
    assert "NOT ABOUT YOUR PARLAY" in hint


def test_the_hint_states_the_token_is_stripped(sgp):
    """A caller reading FanDuel's own API docs would expect `betReference` and needs to
    know it is gone on purpose, not missing by accident."""
    assert "PROJECTED AWAY" in (sgp.response_hint or "")


def test_it_is_tagged_for_cross_book_comparison(sgp):
    assert set(sgp.capabilities) == {"sport.same_game_multi", "sport.prices"}
