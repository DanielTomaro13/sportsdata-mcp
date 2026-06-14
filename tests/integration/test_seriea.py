"""Serie A (legaseriea.it SDP) — registration (offline) + live probes.

The SDP API is public and no-auth. The offline test checks registration; the
``live`` tests hit the real host and ``xfail`` if unreachable. Run with::

    pytest -m live tests/integration/test_seriea.py
"""

from __future__ import annotations

import json

import pytest
from fastmcp.exceptions import ToolError as MCPToolError

from sportsdata_mcp.config import Config
from sportsdata_mcp.server import build_server

SERIEA_GROUPS = ["seriea.core", "seriea.season"]
# 2025/26 season id (a fixed, stable SDP id).
SID = "serie-a::Football_Season::5f0e080fc3a44073984b75b3a8e06a8a"


@pytest.fixture
async def seriea_server():
    mcp, reg = build_server(Config(enabled_groups=SERIEA_GROUPS))
    try:
        yield mcp
    finally:
        await reg.aclose()


def _payload(result):
    if result.structured_content is not None:
        return result.structured_content
    return json.loads(result.content[0].text)


# ─── offline: registration ──────────────────────────────────────────────


async def test_seriea_tools_registered(seriea_server):
    names = {t.name for t in await seriea_server.list_tools()}
    assert {"seriea_competitions", "seriea_seasons", "seriea_season"} <= names
    assert {"seriea_standings", "seriea_teams", "seriea_players", "seriea_matches"} <= names


async def test_competition_id_baked_into_seasons_path(seriea_server):
    """seriea_seasons must take NO competition param — the Serie A compId is baked
    into the path so the model never types the opaque id."""
    tools = {t.name: t for t in await seriea_server.list_tools()}
    props = tools["seriea_seasons"].parameters["properties"]
    assert set(props) <= {"locale"}  # only the optional locale, no compId


# ─── live: api-sdp.legaseriea.it ────────────────────────────────────────


async def _a_season_id(server):
    """Resolve the 2025/26 seasonId live (fall back to the pinned id)."""
    seasons = _payload(await server.call_tool("seriea_seasons", {}))["seasons"]
    return next((s["seasonId"] for s in seasons if s.get("seasonName") == "2025/2026"), SID)


@pytest.mark.live
async def test_seasons_catalogue_live(seriea_server):
    """The 41-season catalogue resolves with the baked competition id."""
    try:
        res = await seriea_server.call_tool("seriea_seasons", {})
    except (MCPToolError, RuntimeError) as e:
        pytest.xfail(f"Serie A SDP unavailable: {e}")
    seasons = _payload(res)["seasons"]
    assert len(seasons) > 30 and "seasonId" in seasons[0]
    assert any(s.get("seasonName") == "2025/2026" for s in seasons)


@pytest.mark.live
async def test_standings_live(seriea_server):
    """The overall table has 20 teams, each with Opta stats[]."""
    try:
        sid = await _a_season_id(seriea_server)
        res = await seriea_server.call_tool("seriea_standings", {"seasonId": sid})
    except (MCPToolError, RuntimeError) as e:
        pytest.xfail(f"Serie A SDP unavailable: {e}")
    tables = _payload(res)["standings"]
    overall = next(t for t in tables if t.get("type") == "table")
    assert len(overall["teams"]) == 20 and overall["teams"][0]["stats"]


@pytest.mark.live
async def test_players_paginated_and_goalkeeping_live(seriea_server):
    """Player stats paginate 30/page; the Goalkeeping category is valid."""
    try:
        sid = await _a_season_id(seriea_server)
        gen = _payload(await seriea_server.call_tool("seriea_players", {"seasonId": sid, "category": "General", "page": 1}))
        gk = _payload(await seriea_server.call_tool("seriea_players", {"seasonId": sid, "category": "Goalkeeping", "page": 1}))
    except (MCPToolError, RuntimeError) as e:
        pytest.xfail(f"Serie A SDP unavailable: {e}")
    assert gen["players"] and gen["players"][0]["stats"]
    assert gen["pagination"]["totalPages"] >= 1
    assert "players" in gk


@pytest.mark.live
async def test_matches_live(seriea_server):
    """A season's matches feed is 380 games with scores + status."""
    try:
        sid = await _a_season_id(seriea_server)
        res = await seriea_server.call_tool("seriea_matches", {"seasonId": sid})
    except (MCPToolError, RuntimeError) as e:
        pytest.xfail(f"Serie A SDP unavailable: {e}")
    matches = _payload(res)["matches"]
    assert len(matches) == 380
    assert {"matchId", "home", "away", "status"} <= set(matches[0])
