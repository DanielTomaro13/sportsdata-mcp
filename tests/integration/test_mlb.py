"""MLB (statsapi.mlb.com) — registration (offline) + live probes.

The official MLB Stats API is public and no-auth. The offline test checks tool
registration and runs everywhere; the ``live`` tests hit the API and ``xfail`` if
it is unreachable. Run the live ones with::

    pytest -m live tests/integration/test_mlb.py
"""

from __future__ import annotations

import json

import pytest
from fastmcp.exceptions import ToolError as MCPToolError

from sportsdata_mcp.config import Config
from sportsdata_mcp.server import build_server

MLB_GROUPS = ["mlb.reference", "mlb.schedule", "mlb.game", "mlb.stats", "mlb.extra", "mlb.meta"]


@pytest.fixture
async def mlb_server():
    mcp, reg = build_server(Config(enabled_groups=MLB_GROUPS))
    try:
        yield mcp
    finally:
        await reg.aclose()


def _payload(result):
    if result.structured_content is not None:
        return result.structured_content
    return json.loads(result.content[0].text) if result.content else None


# ─── offline: registration ──────────────────────────────────────────────


async def test_mlb_tools_registered(mlb_server):
    names = {t.name for t in await mlb_server.list_tools()}
    assert {
        "mlb_sports",
        "mlb_leagues",
        "mlb_divisions",
        "mlb_teams",
        "mlb_team_roster",
        "mlb_player",
        "mlb_player_search",
        "mlb_venues",
        "mlb_seasons",
    } <= names
    assert {"mlb_schedule"} <= names
    assert {"mlb_boxscore", "mlb_linescore", "mlb_playbyplay", "mlb_live_feed"} <= names
    assert {"mlb_standings", "mlb_stats", "mlb_player_stats", "mlb_leaders"} <= names
    assert {"mlb_draft", "mlb_awards", "mlb_awards_list", "mlb_attendance"} <= names
    # extended coverage
    assert {
        "mlb_team",
        "mlb_team_coaches",
        "mlb_teams_affiliates",
        "mlb_people",
        "mlb_people_changes",
        "mlb_sports_players",
        "mlb_seasons_all",
    } <= names
    assert {"mlb_schedule_postseason", "mlb_schedule_tied"} <= names
    assert {
        "mlb_game_win_probability",
        "mlb_game_context_metrics",
        "mlb_game_content",
        "mlb_player_game_stats",
    } <= names
    assert {"mlb_team_stats", "mlb_teams_stats", "mlb_team_leaders", "mlb_high_low"} <= names
    assert {
        "mlb_transactions",
        "mlb_free_agents",
        "mlb_jobs",
        "mlb_umpires",
        "mlb_home_run_derby",
        "mlb_allstar_ballot",
    } <= names
    assert {"mlb_meta"} <= names


# ─── live: statsapi.mlb.com ─────────────────────────────────────────────


async def _a_final_gamepk(server):
    """A known-final game date in 2025; returns its gamePk."""
    res = await server.call_tool("mlb_schedule", {"sportId": 1, "date": "2025-09-01"})
    data = _payload(res)
    return data["dates"][0]["games"][0]["gamePk"]


@pytest.mark.live
async def test_teams_live(mlb_server):
    """The 30 MLB clubs come back with ids + venues."""
    try:
        res = await mlb_server.call_tool("mlb_teams", {"sportId": 1})
    except (MCPToolError, RuntimeError) as e:
        pytest.xfail(f"statsapi.mlb.com unavailable: {e}")
    teams = _payload(res)["teams"]
    assert teams and "id" in teams[0] and "abbreviation" in teams[0]


@pytest.mark.live
async def test_schedule_and_boxscore_live(mlb_server):
    """A scheduled game's gamePk resolves to a full boxscore."""
    try:
        gp = await _a_final_gamepk(mlb_server)
        res = await mlb_server.call_tool("mlb_boxscore", {"gamePk": gp})
    except (MCPToolError, RuntimeError) as e:
        pytest.xfail(f"statsapi.mlb.com unavailable: {e}")
    box = _payload(res)
    assert "teams" in box and "home" in box["teams"] and "away" in box["teams"]


@pytest.mark.live
async def test_live_feed_v11_live(mlb_server):
    """The v1.1 feed/live endpoint returns the gameData + liveData firehose."""
    try:
        gp = await _a_final_gamepk(mlb_server)
        res = await mlb_server.call_tool("mlb_live_feed", {"gamePk": gp})
    except (MCPToolError, RuntimeError) as e:
        pytest.xfail(f"statsapi.mlb.com unavailable: {e}")
    feed = _payload(res)
    assert "gameData" in feed and "liveData" in feed


@pytest.mark.live
async def test_standings_live(mlb_server):
    """AL+NL division standings carry per-team W/L records."""
    try:
        res = await mlb_server.call_tool("mlb_standings", {"leagueId": "103,104", "season": 2025})
    except (MCPToolError, RuntimeError) as e:
        pytest.xfail(f"statsapi.mlb.com unavailable: {e}")
    recs = _payload(res)["records"]
    assert recs and "teamRecords" in recs[0]


@pytest.mark.live
async def test_leaders_live(mlb_server):
    """Home-run leaders resolve under stats.leaders_season."""
    try:
        res = await mlb_server.call_tool(
            "mlb_leaders", {"leaderCategories": ["homeRuns"], "season": 2025, "limit": 5}
        )
    except (MCPToolError, RuntimeError) as e:
        pytest.xfail(f"statsapi.mlb.com unavailable: {e}")
    data = _payload(res)
    assert "leagueLeaders" in data


@pytest.mark.live
async def test_meta_lookup_live(mlb_server):
    """The meta endpoint returns a lookup table (positions) used by other calls."""
    try:
        res = await mlb_server.call_tool("mlb_meta", {"type": "positions"})
    except (MCPToolError, RuntimeError) as e:
        pytest.xfail(f"statsapi.mlb.com unavailable: {e}")
    data = _payload(res)
    assert isinstance(data, list) and data
    assert "abbrev" in data[0] or "code" in data[0]


@pytest.mark.live
async def test_win_probability_and_transactions_live(mlb_server):
    """Win-probability series + transactions log resolve (newly multi-provider caps)."""
    try:
        gp = await _a_final_gamepk(mlb_server)
        wp = _payload(await mlb_server.call_tool("mlb_game_win_probability", {"gamePk": gp}))
        tx = _payload(
            await mlb_server.call_tool(
                "mlb_transactions", {"teamId": 133, "startDate": "2025-07-01", "endDate": "2025-07-15"}
            )
        )
    except (MCPToolError, RuntimeError) as e:
        pytest.xfail(f"statsapi.mlb.com unavailable: {e}")
    assert isinstance(wp, list) and wp and "homeTeamWinProbability" in wp[0]
    assert "transactions" in tx


@pytest.mark.live
async def test_team_stats_live(mlb_server):
    """League-wide team stats (stats.team_season)."""
    try:
        res = await mlb_server.call_tool("mlb_teams_stats", {"season": 2025, "group": "hitting"})
    except (MCPToolError, RuntimeError) as e:
        pytest.xfail(f"statsapi.mlb.com unavailable: {e}")
    assert "stats" in _payload(res)


@pytest.mark.live
async def test_awards_list_live(mlb_server):
    """The award-definitions catalogue returns awardIds for mlb_awards."""
    try:
        res = await mlb_server.call_tool("mlb_awards_list", {})
    except (MCPToolError, RuntimeError) as e:
        pytest.xfail(f"statsapi.mlb.com unavailable: {e}")
    awards = _payload(res)["awards"]
    assert awards and "id" in awards[0] and "name" in awards[0]


@pytest.mark.live
async def test_seasons_all_live(mlb_server):
    """/seasons/all returns the full season history (150+), unlike plain /seasons."""
    try:
        res = await mlb_server.call_tool("mlb_seasons_all", {"sportId": 1})
    except (MCPToolError, RuntimeError) as e:
        pytest.xfail(f"statsapi.mlb.com unavailable: {e}")
    seasons = _payload(res)["seasons"]
    assert len(seasons) > 100 and "seasonId" in seasons[0]


@pytest.mark.live
async def test_people_changes_live(mlb_server):
    """Recently-changed player records come back for a short updatedSince window."""
    try:
        res = await mlb_server.call_tool("mlb_people_changes", {"updatedSince": "2026-06-01T00:00:00Z"})
    except (MCPToolError, RuntimeError) as e:
        pytest.xfail(f"statsapi.mlb.com unavailable: {e}")
    data = _payload(res)
    assert "people" in data
