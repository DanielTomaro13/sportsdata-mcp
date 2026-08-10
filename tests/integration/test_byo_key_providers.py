"""The BYO-key tier: registration (offline) + keyless-refusal probes (live).

We hold no key for any of these providers, so the usual contract test — freeze a real
response and fail if its shape moves — is not available. What CAN be tested, and is
worth testing, is everything either side of the key:

  * the specs register, and every tool carries the "shape unverified" caveat so a model
    is told not to trust the documented nesting too hard;
  * `free` never includes them, because `free` is a promise of zero setup;
  * the hosts exist, the paths exist, and a keyless call fails LOUDLY rather than
    returning something a model would read as data.

That last point is the one with teeth. Two of these providers answer a keyless request
with HTTP 200 and an error body:

    api-tennis   200  {"error":"1", …"The field is mandatory"}
    cricketdata  200  {"status":"failure","reason":"Invalid API Key"}

Left alone, the engine would decode that and hand it over as a result. The live tests
below assert the ToolError that `error_signals` produces instead.

Run the live probes with::

    pytest -m live tests/integration/test_byo_key_providers.py
"""

from __future__ import annotations

import os

import pytest
from fastmcp.exceptions import ToolError as MCPToolError

from sportsdata_mcp.config import Config
from sportsdata_mcp.server import build_server
from sportsdata_mcp.spec_loader import load_all_specs

BYO = [
    "theoddsapi", "pandascore", "cfbd", "footballdataorg", "apitennis", "cricketdata",
    "apisports", "oddsapiio", "balldontlie", "sportsgameodds", "sportmonks", "sportsdataio",
    "mysportsfeeds", "isportsapi", "highlightly", "entitysport", "golfcourseapi",
]

_GROUPS = [f"{p}.*" for p in BYO]


@pytest.fixture
async def server():
    mcp, reg = build_server(Config(enabled_groups=_GROUPS))
    try:
        yield mcp
    finally:
        await reg.aclose()


# ─── offline: the contract around the key ───────────────────────────────


async def test_every_byo_provider_registers_tools(server):
    names = {t.name for t in await server.list_tools()}
    for pid in BYO:
        assert any(n.startswith(f"{pid}_") for n in names), f"{pid} registered no tools"


async def test_tools_warn_that_shapes_are_unverified(server):
    """A model that trusts an invented nesting will write confidently wrong code. The
    caveat is the only honest signal we can give when we cannot probe."""
    for tool in await server.list_tools():
        if tool.name.split("_")[0] in BYO:
            assert "has NOT been verified" in tool.description, tool.name


def test_all_are_flagged_and_none_leak_into_free():
    specs = {s.provider.id: s.provider for s in load_all_specs()}
    for pid in BYO:
        assert specs[pid].requires_user_key is True, pid
        assert specs[pid].shapes_verified is False, pid


def test_each_declares_the_env_var_it_needs():
    """"Set a key" is useless advice without the variable's name; the error messages are
    built from these, so an unset `env` would produce an unactionable failure.

    `username_env` is checked too: MySportsFeeds uses HTTP Basic, and looking only at
    `env` would silently exempt it from this guarantee.
    """
    specs = {s.provider.id: s.provider for s in load_all_specs()}
    for pid in BYO:
        envs = [
            getattr(a, attr, None)
            for a in specs[pid].auth.values()
            for attr in ("env", "username_env")
        ]
        assert any(envs), f"{pid} declares no env var to read its key from"


# ─── live: what a keyless call actually does ────────────────────────────


def _assert_refused(exc, *expected: str) -> None:
    """The refusal must be about the KEY, not about the network.

    A live probe that fails because the host blinked is not a finding, and turning one
    into a red build teaches people to ignore red builds. So an unreachable host skips,
    while a wrong-shaped refusal — the thing this file exists to catch — still fails.
    """
    msg = str(exc)
    if "did not respond in time" in msg or "unreachable" in msg:
        pytest.skip(f"environmental, not a contract break: {msg[:120]}")
    if expected:
        assert any(e in msg for e in expected), msg



@pytest.mark.live
@pytest.mark.skipif(bool(os.environ.get("API_TENNIS_KEY")), reason="a key is set — this probes the keyless path")
async def test_apitennis_keyless_raises_instead_of_returning_the_error_body(server):
    """VERIFIED live 2026-08-10: HTTP 200 + {"error":"1", …}. Must surface as an error."""
    with pytest.raises(MCPToolError) as e:
        await server.call_tool("apitennis_events", {})
    _assert_refused(e.value, "API_TENNIS_KEY", "error body")


@pytest.mark.live
@pytest.mark.skipif(bool(os.environ.get("CRICKETDATA_API_KEY")), reason="a key is set — this probes the keyless path")
async def test_cricketdata_keyless_raises_instead_of_returning_the_failure_object(server):
    """VERIFIED live 2026-08-10: HTTP 200 + {"status":"failure","reason":"Invalid API Key"}."""
    with pytest.raises(MCPToolError) as e:
        await server.call_tool("cricketdata_current_matches", {})
    _assert_refused(e.value, "CRICKETDATA_API_KEY", "Invalid API Key")


@pytest.mark.live
@pytest.mark.skipif(bool(os.environ.get("THE_ODDS_API_KEY")), reason="a key is set")
async def test_theoddsapi_keyless_gives_a_clean_401(server):
    """This one behaves properly: 401 {"message":"API key is missing"}."""
    with pytest.raises(MCPToolError):
        await server.call_tool("theoddsapi_sports", {})


@pytest.mark.live
@pytest.mark.skipif(bool(os.environ.get("CFBD_API_KEY")), reason="a key is set")
async def test_cfbd_keyless_gives_a_clean_401(server):
    with pytest.raises(MCPToolError):
        await server.call_tool("cfbd_teams", {})


@pytest.mark.live
async def test_footballdataorg_open_endpoints_still_work_without_a_key(server):
    """Not everything behind a BYO flag is locked: three football-data.org endpoints are
    open, and were probed live. This is why the provider is `optional` rather than hard
    -required — dropping it entirely would lose 189 competitions of free reference data.
    """
    res = await server.call_tool("footballdataorg_competitions", {})
    assert res is not None


@pytest.mark.live
@pytest.mark.skipif(bool(os.environ.get("API_SPORTS_KEY")), reason="a key is set")
async def test_apisports_keyless_raises(server):
    """api-sports reports failures inside the body (`errors` populated, `response: []`).
    Probed keyless it happens to answer 403, but the presence-mode signal is what
    protects the case that actually bites: a blown daily quota returned as HTTP 200 with
    an empty `response`, which reads as "no games today"."""
    with pytest.raises(MCPToolError):
        await server.call_tool("apisports_status", {})


@pytest.mark.live
async def test_oddsapiio_open_endpoints_work_without_a_key(server):
    """VERIFIED live: /v3/sports and /v3/bookmakers are open. This also pins the version
    segment — the vendor's docs advertise /v2/, which 404s on every path."""
    sports = await server.call_tool("oddsapiio_sports", {})
    books = await server.call_tool("oddsapiio_bookmakers", {})
    assert sports is not None and books is not None


@pytest.mark.live
@pytest.mark.skipif(bool(os.environ.get("ODDS_API_IO_KEY")), reason="a key is set")
async def test_oddsapiio_closed_endpoints_raise(server):
    with pytest.raises(MCPToolError):
        await server.call_tool("oddsapiio_leagues", {"sport": "football"})


@pytest.mark.live
@pytest.mark.skipif(bool(os.environ.get("BALLDONTLIE_API_KEY")), reason="a key is set")
async def test_balldontlie_keyless_raises(server):
    """Once keyless, now 401 — the reason old tutorials for this API no longer work."""
    with pytest.raises(MCPToolError):
        await server.call_tool("balldontlie_nba_teams", {})


@pytest.mark.live
@pytest.mark.skipif(bool(os.environ.get("SPORTMONKS_TOKEN")), reason="a key is set")
async def test_sportmonks_keyless_raises(server):
    with pytest.raises(MCPToolError):
        await server.call_tool("sportmonks_leagues", {})


@pytest.mark.live
@pytest.mark.skipif(bool(os.environ.get("SPORTSGAMEODDS_API_KEY")), reason="a key is set")
async def test_sportsgameodds_keyless_raises(server):
    with pytest.raises(MCPToolError):
        await server.call_tool("sportsgameodds_sports", {})


@pytest.mark.live
@pytest.mark.skipif(bool(os.environ.get("SPORTSDATAIO_NFL_KEY")), reason="a key is set")
async def test_sportsdataio_keyless_raises(server):
    with pytest.raises(MCPToolError):
        await server.call_tool("sportsdataio_nfl_teams", {})


@pytest.mark.live
@pytest.mark.skipif(bool(os.environ.get("ISPORTS_API_KEY")), reason="a key is set")
async def test_isportsapi_keyless_raises_instead_of_returning_the_error_body(server):
    """VERIFIED live 2026-08-10: HTTP 200 + {"code":2,"message":"Invalid [api_key]…"}.
    `code` is 0 on success, so the presence-mode signal passes success through and
    catches every non-zero code."""
    with pytest.raises(MCPToolError) as e:
        await server.call_tool("isportsapi_football_competitions", {})
    _assert_refused(e.value, "ISPORTS_API_KEY", "error body", "illegal access")


@pytest.mark.live
@pytest.mark.skipif(bool(os.environ.get("MYSPORTSFEEDS_API_KEY")), reason="a key is set")
async def test_mysportsfeeds_keyless_raises(server):
    """Answers with a WWW-Authenticate challenge and an HTML body, not JSON — the engine
    must still surface it as an error rather than a decode failure the user cannot act
    on."""
    with pytest.raises(MCPToolError) as e:
        await server.call_tool("mysportsfeeds_standings", {"league": "nba", "season": "current"})
    _assert_refused(e.value)


@pytest.mark.live
@pytest.mark.skipif(bool(os.environ.get("HIGHLIGHTLY_API_KEY")), reason="a key is set")
async def test_highlightly_keyless_raises(server):
    with pytest.raises(MCPToolError) as e:
        await server.call_tool("highlightly_soccer_leagues", {})
    _assert_refused(e.value)


@pytest.mark.live
@pytest.mark.skipif(bool(os.environ.get("ENTITYSPORT_TOKEN")), reason="a token is set")
async def test_entitysport_keyless_raises(server):
    with pytest.raises(MCPToolError) as e:
        await server.call_tool("entitysport_competitions", {})
    _assert_refused(e.value)


@pytest.mark.live
@pytest.mark.skipif(bool(os.environ.get("GOLFCOURSE_API_KEY")), reason="a key is set")
async def test_golfcourseapi_keyless_raises(server):
    with pytest.raises(MCPToolError) as e:
        await server.call_tool("golfcourseapi_search", {"search_query": "Pebble Beach"})
    _assert_refused(e.value)
