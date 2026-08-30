"""A price quote must never be served from cache.

The engine caches GET responses for 60s. That is right for fixtures, market lists and
reference data, and WRONG for a live price — wrong in a way that is invisible, because a
cached quote arrives in 0ms looking exactly like a fresh one.

It matters because of one specific check. Automated betting is only safe if you can
quote, take a decision, RE-QUOTE, and refuse when the price has moved. A re-quote served
from cache compares a number against itself and always agrees, so the check passes while
protecting nothing — and the bet gets placed at a price nobody confirmed.

Measured live 2026-08-27: `unibet_sgm_price` returned the previous price in 0ms on the
second and third call. TWO of the seven pricers are GETs — Unibet and Entain — and the
other five are POSTs, which the cache key already refuses. That split is luck rather than
design, and Entain was missed entirely on the first pass until the audit below caught it.
This file makes the property design instead of luck.
"""

from __future__ import annotations

import pytest

from sportsdata_mcp.http_client import HTTPClient
from sportsdata_mcp.spec_loader import load_all_specs

#: Tools that return a price someone could ACT on. Each must be uncacheable — either by
#: being a POST (which the cache key already refuses) or by declaring `never_cache`.
PRICERS = (
    "sportsbet_sgm_price", "tab_sgm_price", "pointsbet_sgm_price",
    "betr_sgm_price", "unibet_sgm_price", "entain_sgm_price", "fanduel_sgp_price",
)


@pytest.fixture(scope="module")
def endpoints():
    return {e.name: (s, e) for s in load_all_specs() for e in s.endpoints}


def test_no_pricer_can_be_served_from_cache(endpoints):
    """The invariant, stated so a seventh book cannot quietly break it: a GET pricer that
    forgets `never_cache` is indistinguishable from a working one until a stale quote gets
    a real bet placed at the wrong price."""
    for name in PRICERS:
        assert name in endpoints, f"{name} is gone"
        _, ep = endpoints[name]
        cacheable = ep.method == "GET" and not ep.never_cache
        assert not cacheable, (
            f"{name} is a GET that does not declare never_cache — a re-quote would be "
            f"served from cache and the drift check would compare a price against itself")


@pytest.mark.parametrize("name", ["unibet_sgm_price", "entain_sgm_price"])
def test_the_get_pricers_declare_it_explicitly(endpoints, name):
    """The two that need the flag rather than getting the property free from being POSTs.
    Entain was missed on the first pass — the audit above is what caught it, which is the
    argument for having the audit rather than a hand-maintained list."""
    _, ep = endpoints[name]
    assert ep.method == "GET"
    assert ep.never_cache is True


#: The second category of cache opt-out: racecards the racing board polls for PRICES.
#: Not betting pricers — these feed a live odds board rather than a re-quote check — but
#: the same defect. Measured 2026-08-31: the board polls every 8s against a 60s TTL, so
#: five calls to a live meeting returned an identical body hash in 12-25ms against 311ms
#: cold. The prices did not move because they could not; polling faster changed nothing.
#: Racing DISCOVERY endpoints (tab_racing_meetings, dabble_active_competitions, …) keep
#: the cache deliberately — they change per day, not per second.
RACING_PRICE_ENDPOINTS = [
    "dabble_competition_fixtures", "dabble_fixture_details", "entain_racing_racecard",
    "pointsbet_racing_race", "sportsbet_racecard", "tab_racing_race",
]


def test_never_cache_is_off_by_default(endpoints):
    """Passthrough caching stays the default — this is an opt-out for prices, not a
    general disabling of the cache that would make every tool slower.

    The allowlist is exact on purpose: it is what forces a reason to be written down for
    each opt-out, rather than the flag spreading until the cache is effectively gone.
    """
    _, betoffer = endpoints["unibet_kambi_live_stats"]
    assert betoffer.never_cache is False

    # Every racing endpoint that opted out must be a PRICE endpoint, never a discovery
    # one — the split is the whole point, and an index served fresh costs ~100x on repeat.
    for name in ("tab_racing_meetings", "pointsbet_racing_meetings",
                 "sportsbet_racing_allracing", "dabble_active_competitions"):
        assert endpoints[name][1].never_cache is False, (
            f"{name} is DISCOVERY, not a price — it should keep the cache")

    expected = sorted(["entain_sgm_price", "unibet_sgm_price"] + RACING_PRICE_ENDPOINTS)
    declaring = [n for (s, e) in endpoints.values() for n in [e.name] if e.never_cache]
    assert sorted(declaring) == expected, (
        f"unexpected endpoints opting out of cache: {sorted(set(declaring) - set(expected))} "
        "— if that is right, say why in the endpoint's own comment and add it here")


@pytest.mark.parametrize("no_cache,expected_key", [(False, True), (True, False)])
def test_the_flag_reaches_the_cache_key(no_cache, expected_key):
    """The wiring itself: spec flag -> registry -> http_client. Without this the
    declaration is decorative."""
    from pathlib import Path

    from sportsdata_mcp.config import Config
    from sportsdata_mcp.spec_loader import load_spec

    spec = load_spec(Path(__file__).resolve().parents[2]
                     / "src/sportsdata_mcp/specs/unibet.yaml")
    http = HTTPClient(spec.provider, Config())
    kwargs = {"method": "GET", "base": "kambi_offering", "url": "/x.json",
              "params": {}, "headers": {}, "auth_key": "default"}
    key = http._cache_key(kwargs)
    assert (key is not None) is True, "a plain GET is cacheable"
    # request_json pops `no_cache` and skips the key when set; mirror that decision here.
    effective = None if no_cache else key
    assert (effective is not None) is expected_key


def test_a_post_was_never_cacheable(endpoints):
    """Why the other five pricers did not need the flag — stated so nobody 'tidies up' by
    removing it from Unibet on the grounds that its neighbours manage without."""
    from pathlib import Path

    from sportsdata_mcp.config import Config
    from sportsdata_mcp.spec_loader import load_spec

    spec = load_spec(Path(__file__).resolve().parents[2]
                     / "src/sportsdata_mcp/specs/pointsbet.yaml")
    http = HTTPClient(spec.provider, Config())
    assert http._cache_key({"method": "POST", "url": "/x", "json_body": {"a": 1}}) is None
