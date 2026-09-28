"""Doctor must not lie in either direction.

The nightly drift check exists to notice an upstream changing shape. It is only worth
having if its verdicts are trustworthy, and on 2026-08-10 it produced BOTH failure modes
at once:

  * 13 providers reported as "NEW provider drift" when every one of them was healthy and
    simply refusing an unauthenticated probe — CI holds no BYO keys. A check that cries
    wolf gets ignored, and then misses the real thing.
  * `footballdatauk` reported as "non-JSON — likely a bot challenge" for returning
    text/csv, which is the entire point of that provider.
  * Worst: `apitennis`, `cricketdata` and `isportsapi` reported ✓ PASSED while all three
    were returning auth-error bodies inside HTTP 200. A false PASS is worse than a false
    failure, because it hides breakage behind a green check.

These tests pin the resulting rules.
"""

from __future__ import annotations

import httpx
import pytest

from sportsdata_mcp.config import Config
from sportsdata_mcp.doctor import _key_is_missing, _probe_endpoint
from sportsdata_mcp.http_client import HTTPClient
from sportsdata_mcp.spec_loader import load_all_specs

SPECS = load_all_specs()


def _spec(pid):
    return next(s for s in SPECS if s.provider.id == pid)


def _client(pid, handler):
    spec = _spec(pid)
    c = HTTPClient(spec.provider, Config())
    c._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    c._cache_ttl = 0.0
    return spec, c


def _ep(spec, name=None):
    return next(e for e in spec.endpoints if name is None or e.name == name)


async def _probe(pid, handler, ep_name=None, args=None):
    spec, c = _client(pid, handler)
    ep = _ep(spec, ep_name)
    try:
        return await _probe_endpoint(c, spec.provider, ep, args or {}, lambda _m: None)
    finally:
        await c.aclose()


# ─── the false FAILURES ─────────────────────────────────────────────────


@pytest.mark.anyio
async def test_csv_provider_is_not_a_bot_challenge(monkeypatch):
    """text/csv is a first-class response format here, not a challenge page."""
    csv = "Div,Date,HomeTeam,AwayTeam,FTHG,FTAG\nE0,17/08/24,Man United,Fulham,1,0\nE0,17/08/24,Ipswich,Liverpool,0,2\n"
    outcome = await _probe(
        "footballdatauk",
        lambda r: httpx.Response(200, text=csv, headers={"content-type": "text/csv"}),
        args={"season": "2425", "division": "E0"},
    )
    assert outcome == "ok"


@pytest.mark.anyio
async def test_a_csv_provider_returning_one_line_still_fails():
    """The CSV path must not become a blanket pass — an empty or truncated download is
    real breakage."""
    outcome = await _probe(
        "footballdatauk",
        lambda r: httpx.Response(200, text="Div,Date\n", headers={"content-type": "text/csv"}),
        args={"season": "2425", "division": "E0"},
    )
    assert outcome == "fail"


@pytest.mark.anyio
@pytest.mark.parametrize("status", [400, 401, 403, 404, 429])
async def test_any_4xx_is_expected_when_we_hold_no_key(monkeypatch, status):
    """Providers spell "you did not authenticate" differently — Entity Sport answers a
    missing token with 400 "Invalid request" — and without a key a 404 is genuinely
    indistinguishable from a refusal. Skipping is the honest verdict."""
    monkeypatch.delenv("THE_ODDS_API_KEY", raising=False)
    outcome = await _probe("theoddsapi", lambda r: httpx.Response(status, json={"e": 1}))
    assert outcome == "skip"


@pytest.mark.anyio
async def test_a_keyless_provider_still_fails_on_4xx(monkeypatch):
    """The excuse is strictly for BYO providers. For a keyless one, a 404 IS drift —
    that is the whole point of the check."""
    outcome = await _probe("nhl", lambda r: httpx.Response(404, json={"e": 1}))
    assert outcome == "fail"


@pytest.mark.anyio
async def test_5xx_still_fails_even_without_a_key(monkeypatch):
    """A server error is knowable without credentials, so it must not be excused."""
    monkeypatch.delenv("THE_ODDS_API_KEY", raising=False)
    outcome = await _probe("theoddsapi", lambda r: httpx.Response(503, text="down"))
    assert outcome == "fail"


# ─── the false PASS ─────────────────────────────────────────────────────


@pytest.mark.anyio
async def test_a_200_carrying_an_error_body_is_not_a_pass(monkeypatch):
    """With a key configured, an error-in-200 is a genuine failure and must be reported
    as one. Doctor previously called this "200 OK (dict, 2 keys)"."""
    monkeypatch.setenv("API_TENNIS_KEY", "configured")
    body = {"error": "1", "result": [{"msg": "Wrong login credentials"}]}
    outcome = await _probe("apitennis", lambda r: httpx.Response(200, json=body))
    assert outcome == "fail"


@pytest.mark.anyio
async def test_a_200_error_body_is_a_skip_when_we_hold_no_key(monkeypatch):
    monkeypatch.delenv("API_TENNIS_KEY", raising=False)
    body = {"error": "1", "result": [{"msg": "The field is mandatory"}]}
    outcome = await _probe("apitennis", lambda r: httpx.Response(200, json=body))
    assert outcome == "skip"


@pytest.mark.anyio
async def test_a_genuine_200_still_passes(monkeypatch):
    monkeypatch.delenv("API_TENNIS_KEY", raising=False)
    body = {"success": 1, "result": [{"event_type_key": 265}]}
    outcome = await _probe("apitennis", lambda r: httpx.Response(200, json=body))
    assert outcome == "ok"


# ─── the rule that decides which of the above applies ───────────────────


def test_key_is_missing_needs_both_halves(monkeypatch):
    """`requires_user_key` alone would excuse a developer who HAS a key from seeing real
    failures; an unset env var alone would excuse ESPN Fantasy, which works anonymously
    and for which a 401 genuinely is drift."""
    monkeypatch.delenv("THE_ODDS_API_KEY", raising=False)
    spec = _spec("theoddsapi")
    http = HTTPClient(spec.provider, Config())
    assert _key_is_missing(http, spec.provider, "default") is True

    monkeypatch.setenv("THE_ODDS_API_KEY", "set")
    http2 = HTTPClient(spec.provider, Config())
    assert _key_is_missing(http2, spec.provider, "default") is False

    fantasy = _spec("espnfantasy")
    http3 = HTTPClient(fantasy.provider, Config())
    assert _key_is_missing(http3, fantasy.provider, "default") is False


# ─── a key required by one auth block, not the whole provider ───────────


def _refused(r):
    return httpx.Response(401, json={"title": "X-API-Key header required"})


def test_key_is_missing_reads_the_auth_block_too(monkeypatch):
    """PuntersEdge keeps `requires_user_key: false` for its keyless demo group, so the
    provider-level rule cannot see that its keyed block needs a key. The block says so
    itself; ESPN Fantasy's optional cookie block does not, and must stay unexcused."""
    monkeypatch.delenv("PUNTERSEDGE_API_KEY", raising=False)
    monkeypatch.delenv("ESPN_FANTASY_COOKIE", raising=False)
    pe = _spec("puntersedge")
    http = HTTPClient(pe.provider, Config())
    assert _key_is_missing(http, pe.provider, "default") is True
    assert _key_is_missing(http, pe.provider, "demo") is False

    fantasy = _spec("espnfantasy")
    http2 = HTTPClient(fantasy.provider, Config())
    assert _key_is_missing(http2, fantasy.provider, "private") is False


@pytest.mark.anyio
async def test_a_block_that_requires_its_key_is_skipped_without_one(monkeypatch):
    """Before the flag, every nightly drift run reported both keyed PuntersEdge groups as
    new drift: HTTP 401 without a key, from a provider that is not `requires_user_key`."""
    monkeypatch.delenv("PUNTERSEDGE_API_KEY", raising=False)
    assert await _probe("puntersedge", _refused, "puntersedge_sports") == "skip"


@pytest.mark.anyio
async def test_a_block_that_requires_its_key_still_fails_with_one(monkeypatch):
    """The excuse is for an ABSENT key. A configured key being refused is a real failure."""
    monkeypatch.setenv("PUNTERSEDGE_API_KEY", "configured")
    assert await _probe("puntersedge", _refused, "puntersedge_sports") == "fail"


@pytest.mark.anyio
async def test_the_flag_does_not_excuse_the_providers_keyless_group(monkeypatch):
    """Why it is per block: listing puntersedge in drift-known-blocked.txt would have
    blinded the check to the demo group too, and a 401 there IS drift."""
    monkeypatch.delenv("PUNTERSEDGE_API_KEY", raising=False)
    assert await _probe("puntersedge", _refused, "puntersedge_demo_racing_next_to_go") == "fail"


@pytest.mark.anyio
async def test_an_optional_block_without_the_flag_still_fails(monkeypatch):
    """ESPN Fantasy's cookie block is `optional` and does not set the flag — public
    leagues work anonymously — so its guarantee is unchanged: a 401 is still drift."""
    monkeypatch.delenv("ESPN_FANTASY_COOKIE", raising=False)
    outcome = await _probe(
        "espnfantasy", _refused, "espnfantasy_league", args={"seasonId": 2025, "leagueId": 1234}
    )
    assert outcome == "fail"
