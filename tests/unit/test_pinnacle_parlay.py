"""Pinnacle does not sell the product the other books do, and the spec must say so.

Probed live 2026-08-30 across 16,040 matchups: `/markets/related/parlay` returns data
byte-identical to `/markets/related/straight` — same markets, same prices, same limits —
so Pinnacle applies no correlation adjustment and a combination's price is the product of
its legs. Only 42 matchups of 16,040 permit a same-game parlay at all.

The risk this guards is a tool whose name implies a distinct parlay price when none
exists. That would not fail loudly; it would quietly report the straight price as though
it were a correlated one.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from sportsdata_mcp.spec_loader import load_spec

SPEC = Path(__file__).resolve().parents[2] / "src/sportsdata_mcp/specs/pinnacle.yaml"


@pytest.fixture(scope="module")
def parlay():
    return next(e for e in load_spec(SPEC).endpoints
                if e.name == "pinnacle_matchup_parlay_markets")


def test_the_hint_says_it_duplicates_the_straight_markets(parlay):
    hint = parlay.response_hint or ""
    assert "IDENTICAL to pinnacle_matchup_markets" in hint
    assert "PRODUCT of its legs" in hint


def test_the_hint_forbids_calling_it_a_distinct_parlay_price(parlay):
    """The failure this prevents is silent: reporting a straight price as a correlated
    one looks exactly like a correct answer."""
    assert "Do not present this as a distinct" in (parlay.response_hint or "")


def test_the_hint_points_at_parlayRestriction(parlay):
    """The eligibility answer is already on the matchup object — no extra call. Offering
    a same-game multi on a `unique_matchups` matchup is an error the data prevents."""
    hint = parlay.response_hint or ""
    assert "parlayRestriction" in hint
    for value in ("unique_matchups", "forbidden", "allowed"):
        assert value in hint, f"the hint must name `{value}`"


def test_pinnacle_ships_no_sgm_pricer():
    """Deliberate. Sportsbet and TAB have one because they quote a correlated price;
    Pinnacle does not quote one, and a tool here would be inventing an endpoint."""
    spec = load_spec(SPEC)
    assert not any(e.name.endswith("_sgm_price") for e in spec.endpoints)
    assert not any(e.method == "POST" for e in spec.endpoints), (
        "Pinnacle's surface is read-only; a POST here would need justifying"
    )


def test_the_books_that_DO_quote_a_correlated_price_have_a_pricer():
    """The other half of the claim: this is not an oversight, it is a difference between
    the books."""
    specs_dir = SPEC.parent
    for book in ("sportsbet", "tab"):
        spec = load_spec(specs_dir / f"{book}.yaml")
        assert any(e.name == f"{book}_sgm_price" for e in spec.endpoints), (
            f"{book} quotes a correlated price and should expose a pricer"
        )
