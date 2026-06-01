"""ESPN — catalogue/registration checks (offline) + live CDN/API probes.

The registration + catalogue + error-path tests run in the default suite (no
network). The ``live``-marked tests hit ESPN's real, unauthenticated hosts:

  * ``site.api.espn.com``       — scoreboards, teams, standings, news, summaries.
  * ``sports.core.api.espn.com`` — the canonical $ref-linked core data model.
  * ``site.web.api.espn.com``   — site-wide search + common/v3 athlete views.
  * ``cdn.espn.com``            — the CDN live core feed (needs ?xhr=1).

All four serve JSON (sometimes as ``text/plain``); the client accepts it anyway.
Live tests are tolerant of schedule-dependent emptiness (an off-day scoreboard
with zero events) and assert on stable structure only. They ``xfail`` rather than
fail the suite when a host is unreachable. Run them with::

    pytest -m live tests/integration/test_espn.py
"""

from __future__ import annotations

import json

import pytest
from fastmcp.exceptions import ToolError as MCPToolError

from sportsdata_mcp.config import Config
from sportsdata_mcp.server import build_server

ESPN_GROUPS = ["espn.scores", "espn.site", "espn.core", "espn.web", "espn.cdn"]


@pytest.fixture
async def espn_server():
    mcp, reg = build_server(Config(enabled_groups=ESPN_GROUPS))
    try:
        yield mcp
    finally:
        await reg.aclose()


def _structured(result):
    """Pull the JSON payload out of a FastMCP tool-call result."""
    return result.structured_content


def _catalogue(payload_resource) -> dict:
    return json.loads(payload_resource.contents[0].content)


# ─── offline: registration + catalogue + error paths ───────────────────


async def test_espn_tools_registered(espn_server):
    names = {t.name for t in await espn_server.list_tools()}
    # discrete scores endpoints
    assert {"espn_scoreboard", "espn_teams", "espn_standings", "espn_game_summary", "espn_news"} <= names
    # one dispatcher per host
    assert {"espn_site_call", "espn_core_call", "espn_web_call", "espn_cdn_call"} <= names


async def test_site_catalogue_lists_operations(espn_server):
    payload = _catalogue(await espn_server.read_resource("espn://site/operations"))
    assert payload["dispatcher"] == "espn_site_call"
    names = {op["name"] for op in payload["operations"]}
    # a spread across the families the dispatcher fronts
    assert {"team_roster", "team_injuries", "team_depthchart", "athlete_gamelog", "rankings"} <= names


async def test_core_catalogue_carries_path_params(espn_server):
    """Each core op publishes the path_params it needs — that's how the model knows a
    deep odds path wants sport+league+eventId+competitionId, not just sport+league."""
    payload = _catalogue(await espn_server.read_resource("espn://core/operations"))
    ops = {op["name"]: op for op in payload["operations"]}
    assert payload["dispatcher"] == "espn_core_call"
    odds = ops["event_odds"]
    assert odds["path_params"] == ["sport", "league", "eventId", "competitionId"]
    # the leagues-plural core shape is in the path
    assert "/leagues/" in odds["path"]


async def test_cdn_catalogue_defaults_xhr(espn_server):
    """Every CDN op carries xhr=1 as a query default so the feed returns JSON."""
    payload = _catalogue(await espn_server.read_resource("espn://cdn/operations"))
    ops = {op["name"]: op for op in payload["operations"]}
    assert set(ops) == {"scoreboard", "game", "boxscore", "playbyplay"}
    assert ops["boxscore"]["query_defaults"]["xhr"] == "1"


async def test_unknown_operation_is_recoverable(espn_server):
    # FastMCP re-wraps our ToolError; the catalogue pointer the model needs survives.
    with pytest.raises(MCPToolError) as ei:
        await espn_server.call_tool("espn_core_call", {"operation": "notarealop"})
    assert "espn://core/operations" in str(ei.value)
    assert "notarealop" in str(ei.value)


# ─── live: site.api.espn.com (open) ─────────────────────────────────────


@pytest.mark.live
@pytest.mark.parametrize("sport,league", [("football", "nfl"), ("basketball", "nba")])
async def test_scoreboard_live(espn_server, sport, league):
    """The site scoreboard envelope is always present even off-season (events may be
    empty). Exercises the parametric {sport}/{league} path across two leagues."""
    try:
        res = await espn_server.call_tool("espn_scoreboard", {"sport": sport, "league": league})
    except (MCPToolError, RuntimeError) as e:
        pytest.xfail(f"site.api.espn.com unavailable: {e}")
    data = _structured(res)
    assert "events" in data and "leagues" in data
    assert isinstance(data["events"], list)


@pytest.mark.live
async def test_standings_live(espn_server):
    """NBA standings are schedule-independent: the league tree always has conference
    children once a season exists."""
    try:
        res = await espn_server.call_tool("espn_standings", {"sport": "basketball", "league": "nba"})
    except (MCPToolError, RuntimeError) as e:
        pytest.xfail(f"site.api.espn.com unavailable: {e}")
    data = _structured(res)
    assert "children" in data
    assert isinstance(data["children"], list)


# ─── live: sports.core.api.espn.com via the dispatcher ──────────────────


@pytest.mark.live
async def test_core_call_teams_live(espn_server):
    """core `teams` is schedule-independent: 30 NBA franchises as a paged
    {count, items:[{$ref}]} envelope. Exercises the leagues-plural core path."""
    try:
        res = await espn_server.call_tool(
            "espn_core_call",
            {"operation": "teams", "path_params": {"sport": "basketball", "league": "nba"}},
        )
    except (MCPToolError, RuntimeError) as e:
        pytest.xfail(f"sports.core.api.espn.com unavailable: {e}")
    data = _structured(res)
    assert "items" in data and isinstance(data["items"], list)
    assert data.get("count", 0) >= 30


# ─── live: site.web.api.espn.com via the dispatcher ─────────────────────


@pytest.mark.live
async def test_web_call_search_live(espn_server):
    """Site-wide search is schedule-independent and needs only query_params."""
    try:
        res = await espn_server.call_tool(
            "espn_web_call",
            {"operation": "search", "query_params": {"query": "lebron", "limit": 3}},
        )
    except (MCPToolError, RuntimeError) as e:
        pytest.xfail(f"site.web.api.espn.com unavailable: {e}")
    data = _structured(res)
    assert "results" in data


# ─── live: cdn.espn.com via the dispatcher ──────────────────────────────


@pytest.mark.live
async def test_cdn_call_scoreboard_live(espn_server):
    """The CDN scoreboard returns its envelope (with a `content` block) for the league
    slug `nfl`; xhr=1 is supplied by the op default so the feed returns JSON."""
    try:
        res = await espn_server.call_tool(
            "espn_cdn_call",
            {"operation": "scoreboard", "path_params": {"sport": "nfl"}},
        )
    except (MCPToolError, RuntimeError) as e:
        pytest.xfail(f"cdn.espn.com unavailable: {e}")
    data = _structured(res)
    # The CDN nests the scoreboard under `content`; the envelope is always present.
    assert isinstance(data, dict)
    assert "content" in data or "scoreboard" in data


# ─── live: cross-tool chain (scoreboard → game_summary) ─────────────────


@pytest.mark.live
async def test_game_summary_chains_off_scoreboard_live(espn_server):
    """The documented discovery flow end to end: pull event ids from the NFL
    scoreboard, then feed the first into espn_game_summary. Skips cleanly on an off
    day (no events), xfails if the host is unreachable."""
    try:
        sb = await espn_server.call_tool(
            "espn_scoreboard", {"sport": "football", "league": "nfl", "dates": "20251102"}
        )
    except (MCPToolError, RuntimeError) as e:
        pytest.xfail(f"site.api.espn.com unavailable: {e}")
    events = _structured(sb).get("events", [])
    if not events:
        pytest.skip("no NFL events for the probe date — nothing to summarise")
    event_id = events[0]["id"]
    try:
        summ = await espn_server.call_tool(
            "espn_game_summary", {"sport": "football", "league": "nfl", "event": event_id}
        )
    except (MCPToolError, RuntimeError) as e:
        pytest.xfail(f"site.api.espn.com unavailable: {e}")
    data = _structured(summ)
    assert "boxscore" in data
