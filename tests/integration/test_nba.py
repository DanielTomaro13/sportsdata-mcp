"""NBA — catalogue/registration checks (offline) + live CDN/stats probes.

The catalogue + registration + error-path tests run in the default suite (no
network). The ``live``-marked tests hit the real, unauthenticated NBA surfaces:

  * ``cdn.nba.com``   — open JSON CDN (scoreboard, schedule). Serves JSON as
    ``text/plain``; the client accepts it anyway.
  * ``stats.nba.com`` — the ``/stats/`` analytics API behind Akamai. The spec
    ships the browser header bundle + an Akamai-friendly throttle, but a network
    that Akamai black-holes (or rate-limits hard) will fail the request — those
    tests ``xfail`` rather than failing the suite.

Live tests are deliberately tolerant of schedule-dependent emptiness (e.g. an
off-day scoreboard with zero games) and assert on stable structure only. Run
them with::

    pytest -m live tests/integration/test_nba.py
"""

from __future__ import annotations

import json

import pytest
from fastmcp.exceptions import ToolError as MCPToolError

from sportsdata_mcp.config import Config
from sportsdata_mcp.server import build_server


@pytest.fixture
async def nba_server():
    mcp, reg = build_server(Config(enabled_groups=["nba.public.cdn", "nba.stats"]))
    try:
        yield mcp
    finally:
        await reg.aclose()


def _structured(result):
    """Pull the JSON payload out of a FastMCP tool-call result."""
    return result.structured_content


def _result_set(payload: dict, name: str) -> tuple[list[str], list[list]]:
    """Find a classic /stats/ resultSet by name; return (headers, rowSet)."""
    rs = next(r for r in payload["resultSets"] if r["name"] == name)
    return rs["headers"], rs["rowSet"]


# ─── offline: registration + catalogue + error paths ───────────────────


async def test_cdn_and_stats_tools_registered(nba_server):
    names = {t.name for t in await nba_server.list_tools()}
    # cdn surface
    assert "nba_scoreboard_today" in names
    assert "nba_boxscore" in names
    assert "nba_playbyplay" in names
    # stats surface
    assert "nba_daily_lineups" in names
    assert "nba_stats_call" in names


async def test_stats_catalogue_lists_137_operations(nba_server):
    result = await nba_server.read_resource("nba://stats/operations")
    payload = json.loads(result.contents[0].content)
    assert payload["dispatcher"] == "nba_stats_call"
    assert len(payload["operations"]) == 137
    names = {op["name"] for op in payload["operations"]}
    # a spread across the families the dispatcher fronts
    assert {"shotchartdetail", "boxscoretraditionalv3", "leaguestandingsv3", "commonteamyears"} <= names


async def test_catalogue_operations_carry_defaults(nba_server):
    """Each op publishes its required query_params + the default param set the model
    overrides — that's what lets the model call any endpoint with only the fields
    that matter."""
    result = await nba_server.read_resource("nba://stats/operations")
    ops = {op["name"]: op for op in json.loads(result.contents[0].content)["operations"]}
    shot = ops["shotchartdetail"]
    assert "PlayerID" in shot["query_params"] and "TeamID" in shot["query_params"]
    assert shot["query_defaults"]["ContextMeasure"] == "PTS"


async def test_unknown_stats_operation_is_recoverable(nba_server):
    # FastMCP re-wraps our ToolError; the catalogue pointer the model needs survives.
    with pytest.raises(MCPToolError) as ei:
        await nba_server.call_tool("nba_stats_call", {"operation": "notarealop"})
    assert "nba://stats/operations" in str(ei.value)
    assert "notarealop" in str(ei.value)


# ─── live: cdn.nba.com (open) ──────────────────────────────────────────


@pytest.mark.live
async def test_scoreboard_today_live(nba_server):
    """cdn.nba.com serves JSON as text/plain; the client must accept it. The
    scoreboard envelope is always present even on an off day (games may be empty)."""
    try:
        res = await nba_server.call_tool("nba_scoreboard_today", {})
    except (MCPToolError, RuntimeError) as e:
        pytest.xfail(f"cdn.nba.com unavailable: {e}")
    data = _structured(res)
    assert "scoreboard" in data
    games = data["scoreboard"]["games"]
    assert isinstance(games, list)
    if games:
        g = games[0]
        assert "gameId" in g and "homeTeam" in g and "awayTeam" in g


# ─── live: stats.nba.com /stats/ via the dispatcher ────────────────────


@pytest.mark.live
async def test_stats_call_commonteamyears_live(nba_server):
    """commonteamyears is schedule-independent: it returns the franchise/year span
    for every team as a classic column-oriented resultSet. Exercises the full
    header-bundle + throttle path and the {resultSets:[{headers, rowSet}]} shape."""
    try:
        res = await nba_server.call_tool("nba_stats_call", {"operation": "commonteamyears"})
    except (MCPToolError, RuntimeError) as e:
        pytest.xfail(f"stats.nba.com unavailable (Akamai/throttle): {e}")
    data = _structured(res)
    headers, rows = _result_set(data, "TeamYears")
    assert "TEAM_ID" in headers
    assert len(rows) >= 30  # 30 current franchises (+ historical relocations)


@pytest.mark.live
async def test_stats_call_standings_overrides_default_param_live(nba_server):
    """leaguestandingsv3 with an explicit Season — shows query_params overriding
    just the field that matters while the op's other defaults flow up untouched.
    30 teams → 30 standings rows."""
    try:
        res = await nba_server.call_tool(
            "nba_stats_call",
            {"operation": "leaguestandingsv3", "query_params": {"Season": "2024-25"}},
        )
    except (MCPToolError, RuntimeError) as e:
        pytest.xfail(f"stats.nba.com unavailable (Akamai/throttle): {e}")
    data = _structured(res)
    _headers, rows = _result_set(data, "Standings")
    assert len(rows) == 30


# ─── live: cross-tool chain (scoreboard → boxscore) ────────────────────


@pytest.mark.live
async def test_boxscore_chains_off_scoreboard_live(nba_server):
    """The documented discovery flow end to end: pull today's gameId values from the
    scoreboard, then feed the first one into nba_boxscore. Skips cleanly on an off
    day (no games), xfails if the CDN is unreachable."""
    try:
        sb = await nba_server.call_tool("nba_scoreboard_today", {})
    except (MCPToolError, RuntimeError) as e:
        pytest.xfail(f"cdn.nba.com unavailable: {e}")
    games = _structured(sb)["scoreboard"]["games"]
    if not games:
        pytest.skip("no NBA games today — nothing to box-score")
    game_id = games[0]["gameId"]
    try:
        box = await nba_server.call_tool("nba_boxscore", {"gameId": game_id})
    except (MCPToolError, RuntimeError) as e:
        pytest.xfail(f"cdn.nba.com unavailable: {e}")
    game = _structured(box)["game"]
    assert game["gameId"] == game_id
    assert "homeTeam" in game and "awayTeam" in game
