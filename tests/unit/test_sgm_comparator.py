"""The six same-game-multi pricers, as a set.

Each book's own test file pins that book's traps. This one pins the thing none of them
can: that the six tools exist together, agree on how they are tagged, and stay findable by
one capability query. The entire point of building six of these was to quote the same legs
at every book and compare — a pricer that ships untagged is invisible to that, and nothing
else in the suite would notice.

Verified live 2026-08-27, all six unauthenticated, five of them on the same AFL fixture
(Western Bulldogs v Collingwood) and Entain on Melbourne v Carlton. Each returns a
correlation-adjusted price that is NOT the product of its legs.

They do not agree on units. Four quote ordinary decimals, Unibet quotes THOUSANDTHS
(3400 = 3.40) and Entain quotes FRACTIONS needing a +1 (27/10 = 3.70). Normalising is the
comparator's job and there is nothing in any payload that announces the scale, so
SCALE is pinned per book below.
"""

from __future__ import annotations

import pytest

from sportsdata_mcp.spec_loader import load_all_specs

#: The tools that price a combination YOU choose. Pre-built-coupon catalogues
#: (betr_pop_sgm_bet_data, pointsbet_preprice_multis, sportsbet_trending_sgm) are a
#: different product and deliberately not here — they answer "what has the book already
#: made", not "what is this bet worth".
PRICERS = {
    "sportsbet": "sportsbet_sgm_price",
    "tab": "tab_sgm_price",
    "pointsbet": "pointsbet_sgm_price",
    "betr": "betr_sgm_price",
    "unibet": "unibet_sgm_price",
    "entain": "entain_sgm_price",
}

#: How each book expresses a price, and therefore what a comparator must do before
#: comparing anything. Nothing in any payload announces this — it is knowledge that only
#: exists because someone checked each book against its own displayed odds.
SCALE = {
    "sportsbet": "decimal",
    "tab": "decimal",
    "pointsbet": "decimal",
    "betr": "decimal",
    "unibet": "thousandths — divide by 1000 (3400 = 3.40)",
    "entain": "fractional — numerator/denominator PLUS ONE (27/10 = 3.70)",
}

#: Books surveyed and deliberately given no pricer, with the reason. Kept here so a later
#: reader asking "why is Pinnacle missing" finds the answer next to the list rather than
#: assuming it was an oversight.
NO_PRICER = {
    "pinnacle": "prices a parlay as the product of its legs — compute it locally",
    "dabble": "sells SGMs but is app-only; no web client to observe the pricer from",
}


@pytest.fixture(scope="module")
def tools_by_name():
    return {t.name: (s, t) for s in load_all_specs() for t in s.all_tools()}


def test_every_pricer_exists_on_its_own_provider(tools_by_name):
    for provider, name in PRICERS.items():
        assert name in tools_by_name, f"{name} is gone"
        assert tools_by_name[name][0].provider.id == provider


def test_all_five_answer_one_capability_query(tools_by_name):
    """`sport.same_game_multi` + `sport.prices` is how a comparator finds them. Losing a
    tag does not break any single book's tool — it just quietly drops that book out of
    every comparison."""
    for name in PRICERS.values():
        caps = set(tools_by_name[name][1].capabilities or [])
        assert {"sport.same_game_multi", "sport.prices"} <= caps, f"{name}: {caps}"


def test_none_of_them_can_move_money(tools_by_name):
    """These price a bet; they must never place one. Four are POSTs, which is exactly the
    shape a placement call has, so `read_only` is what keeps a client from confirming
    before a harmless quote — and what keeps the no-money invariant honest."""
    for name in PRICERS.values():
        _, tool = tools_by_name[name]
        if tool.method == "POST":
            assert tool.read_only is True, f"{name} is a POST that is not marked read_only"


def test_each_hint_says_the_price_is_not_the_product(tools_by_name):
    """The one fact common to all five, and the one a model is most likely to get wrong by
    reaching for arithmetic it already knows. Every hint has to carry it in its own words
    with its own worked example — a shared sentence would be easy to keep and easy to stop
    meaning anything."""
    for name in PRICERS.values():
        hint = (tools_by_name[name][1].response_hint or "").upper()
        assert "NOT THE PRODUCT" in hint, f"{name} no longer states it"


def test_each_hint_carries_a_verified_worked_example(tools_by_name):
    """A rule with a number attached survives; a rule without one gets summarised away.
    Each hint names the date it was checked, because these are live prices and a hint that
    cannot be dated cannot be re-verified."""
    for name in PRICERS.values():
        hint = tools_by_name[name][1].response_hint or ""
        assert "VERIFIED live" in hint, f"{name} does not say when it was checked"


def test_the_books_with_no_pricer_still_have_no_pricer(tools_by_name):
    """A guard against someone adding one without reading why it was skipped. If either of
    these gains a real pricer, delete its entry here — that is the point of the failure."""
    for provider, reason in NO_PRICER.items():
        assert f"{provider}_sgm_price" not in tools_by_name, (
            f"{provider} gained a pricer; NO_PRICER says: {reason}")


#: How each book says no, and therefore whether it needs an `error_signals` declaration.
#: Written out per book rather than counted, because the wrong thing to do when adding the
#: next one is to copy whichever neighbour was nearest.
REFUSAL_STYLE = {
    # HTTP 200 with a ZERO in the field the caller asked for. The zero is the danger: it
    # reads as a quote, so the engine must turn it into an error.
    "pointsbet": "signal",   # {"success": false, "price": 0}
    "betr": "signal",        # {"Price": 0, "ErrorNo": 4527}
    # Refuse in a way that cannot be mistaken for a price, so a signal would be noise.
    "sportsbet": "none",
    "tab": "none",           # per-leg `status` in a validation matrix, no fake price
    "unibet": "none",        # real HTTP 400 with a typed body
    "entain": "none",        # real HTTP 400, and a refusal carries no `odds` key at all
}


def test_each_book_declares_a_signal_exactly_when_it_fakes_a_price(tools_by_name):
    """The failure this catches is a book that starts answering refusals with a zero and
    nobody notices, or a signal copied onto a provider that never needed one. Both are
    silent: the first hands a caller a price of 0, the second turns a real result into an
    error the first time a legitimate field goes falsy."""
    by_provider = {s.provider.id: s for s in load_all_specs()}
    for provider, style in REFUSAL_STYLE.items():
        signals = by_provider[provider].provider.error_signals
        if style == "signal":
            assert signals, f"{provider} answers a refusal with a fake price and declares no signal"
        else:
            assert signals == [], (
                f"{provider} declares {signals} but does not fake a price on refusal — "
                "a signal here fires on a legitimate falsy field sooner or later")


def test_every_pricer_has_an_entry_in_both_tables(tools_by_name):
    """So neither table can quietly fall behind the set of books."""
    assert set(REFUSAL_STYLE) == set(PRICERS)
    assert set(SCALE) == set(PRICERS)


def test_a_book_that_is_not_plain_decimal_says_so_in_its_hint(tools_by_name):
    """The two odd ones out. Unibet reported as 3400 instead of 3.40 is a 1000x error that
    looks like the arbitrage of a lifetime; Entain reported as 2.7 instead of 3.70 is the
    quiet direction, where the book merely looks worse than it is. Both have to be stated
    in the hint, because neither payload carries a unit."""
    for provider, scale in SCALE.items():
        if scale == "decimal":
            continue
        hint = tools_by_name[PRICERS[provider]][1].response_hint or ""
        assert "1000" in hint or "+ 1" in hint, (
            f"{provider} quotes {scale} and its hint no longer says how to convert")
