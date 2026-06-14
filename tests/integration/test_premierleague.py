"""Premier League (premierleague.com) — registration (offline) + live probes.

The site's private JSON APIs are public and no-auth. The offline test checks tool
registration; the ``live`` tests hit the real hosts and ``xfail`` if unreachable.
Run with::

    pytest -m live tests/integration/test_premierleague.py
"""

from __future__ import annotations

import json

import pytest
from fastmcp.exceptions import ToolError as MCPToolError

from sportsdata_mcp.config import Config
from sportsdata_mcp.server import build_server

PL_GROUPS = [
    "premierleague.core",
    "premierleague.teams",
    "premierleague.matches",
    "premierleague.players",
    "premierleague.stats",
    "premierleague.content",
]


@pytest.fixture
async def pl_server():
    mcp, reg = build_server(Config(enabled_groups=PL_GROUPS))
    try:
        yield mcp
    finally:
        await reg.aclose()


def _payload(result):
    if result.structured_content is not None:
        return result.structured_content
    return json.loads(result.content[0].text)


def _rows(data):
    """SDP batch endpoints return a top-level array; FastMCP wraps arrays as {result: [...]}."""
    if isinstance(data, dict) and set(data.keys()) == {"result"}:
        return data["result"]
    return data


# ─── offline: registration ──────────────────────────────────────────────


async def test_pl_tools_registered(pl_server):
    names = {t.name for t in await pl_server.list_tools()}
    assert {"pl_competitions", "pl_standings", "pl_current_gameweek", "pl_country"} <= names
    assert {
        "pl_teams",
        "pl_team",
        "pl_season_teams",
        "pl_teams_by_id",
        "pl_squad",
        "pl_team_form",
        "pl_teamform",
        "pl_team_stats",
        "pl_team_next_fixture",
        "pl_clubs_metadata",
    } <= names
    assert {
        "pl_matches",
        "pl_matchweek_matches",
        "pl_match",
        "pl_match_events",
        "pl_match_lineups",
        "pl_match_stats",
        "pl_match_officials",
        "pl_match_commentary",
    } <= names
    assert {
        "pl_players",
        "pl_player_basic",
        "pl_player",
        "pl_players_by_id",
        "pl_player_comp_stats",
        "pl_player_season_stats",
        "pl_player_info",
        "pl_metadata",
    } <= names
    assert {"pl_player_leaderboard", "pl_team_leaderboard"} <= names
    assert {
        "pl_content",
        "pl_content_item",
        "pl_news_latest",
        "pl_news_popular",
        "pl_video_latest",
        "pl_video_popular",
        "pl_broadcasting_events",
        "pl_broadcast_match_events",
    } <= names


async def test_api_name_params_map_to_wire_names(pl_server):
    """The SDP wire names (_limit/_sort, kickoff>/kickoff<) are exposed under clean
    tool-param names via api_name — assert the tool signature uses the clean names."""
    tools = {t.name: t for t in await pl_server.list_tools()}
    props = tools["pl_matches"].parameters["properties"]
    assert "limit" in props and "_limit" not in props
    assert "kickoff_after" in props and "kickoff>" not in props
    assert "sort" in props and "_sort" not in props


# ─── live: the three PL hosts ───────────────────────────────────────────


async def _a_match_id(server):
    res = await server.call_tool("pl_matches", {"competition": 8, "season": 2025, "matchweek": 1, "limit": 5})
    data = _payload(res)["data"]
    return data[0]["matchId"] if data else None


@pytest.mark.live
async def test_standings_live(pl_server):
    """The 2025/26 league table comes back with team entries."""
    try:
        res = await pl_server.call_tool("pl_standings", {"cid": 8, "sid": 2025, "live": False})
    except (MCPToolError, RuntimeError) as e:
        pytest.xfail(f"SDP unavailable: {e}")
    data = _payload(res)
    assert "tables" in data and data["tables"][0]["entries"]


@pytest.mark.live
async def test_teams_and_squad_live(pl_server):
    """Teams list resolves; a club's squad lists players."""
    try:
        teams = _payload(await pl_server.call_tool("pl_teams", {"cid": 8, "limit": 60}))
        squad = _payload(await pl_server.call_tool("pl_squad", {"cid": 8, "sid": 2025, "tid": 14}))
    except (MCPToolError, RuntimeError) as e:
        pytest.xfail(f"SDP unavailable: {e}")
    assert teams["data"] and "name" in teams["data"][0]
    assert squad["players"]


@pytest.mark.live
async def test_match_centre_live(pl_server):
    """A matchweek-1 match drills into detail + team stats."""
    try:
        mid = await _a_match_id(pl_server)
        if mid is None:
            pytest.skip("no matches for the seed season/matchweek")
        detail = _payload(await pl_server.call_tool("pl_match", {"id": mid}))
        stats = _rows(_payload(await pl_server.call_tool("pl_match_stats", {"id": mid})))
    except (MCPToolError, RuntimeError) as e:
        pytest.xfail(f"SDP unavailable: {e}")
    assert detail.get("matchId") == mid or "kickoff" in detail
    assert isinstance(stats, list) and stats and "stats" in stats[0]


@pytest.mark.live
async def test_player_leaderboard_live(pl_server):
    """Top scorers leaderboard resolves with playerMetadata+stats rows."""
    try:
        res = await pl_server.call_tool(
            "pl_player_leaderboard", {"cid": 8, "sid": 2025, "sort": "goals:desc", "limit": 5}
        )
    except (MCPToolError, RuntimeError) as e:
        pytest.xfail(f"SDP unavailable: {e}")
    data = _payload(res)["data"]
    assert data and "playerMetadata" in data[0] and "stats" in data[0]


@pytest.mark.live
async def test_content_and_resources_live(pl_server):
    """The editorial host (news) and the static config host (current gameweek) both answer."""
    try:
        news = _rows(_payload(await pl_server.call_tool("pl_news_latest", {"limit": 3})))
        gw = _payload(await pl_server.call_tool("pl_current_gameweek", {}))
    except (MCPToolError, RuntimeError) as e:
        pytest.xfail(f"premierleague.com unavailable: {e}")
    assert isinstance(news, list) and news
    assert "matchweek" in gw
