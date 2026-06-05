"""Cricket Australia (cricket.com.au) — registration (offline) + live probes.

Two no-auth hosts: apiv2.cricket.com.au/web (fixtures / scorecard / players /
standings / streams) and api.cricket-australia.pulselive.com (CMS content). The
offline test checks registration and runs everywhere; the ``live`` tests hit the
public APIs and ``xfail`` if unreachable (and ``skip`` when a feed is legitimately
empty, e.g. a competition with no points table). Run::

    pytest -m live tests/integration/test_cricket.py
"""

from __future__ import annotations

import json

import pytest
from fastmcp.exceptions import ToolError as MCPToolError

from sportsdata_mcp.config import Config
from sportsdata_mcp.server import build_server

CRICKET_GROUPS = ["cricket.core", "cricket.match", "cricket.content"]


@pytest.fixture
async def cricket_server():
    mcp, reg = build_server(Config(enabled_groups=CRICKET_GROUPS))
    try:
        yield mcp
    finally:
        await reg.aclose()


def _payload(result):
    if result.structured_content is not None:
        return result.structured_content
    return json.loads(result.content[0].text) if result.content else None


# ─── offline: registration ──────────────────────────────────────────────


async def test_cricket_tools_registered(cricket_server):
    names = {t.name for t in await cricket_server.list_tools()}
    assert {
        "cricket_fixtures",
        "cricket_competitions",
        "cricket_teams",
        "cricket_players",
        "cricket_standings",
    } <= names
    assert {"cricket_scorecard", "cricket_runs_graph", "cricket_streams"} <= names
    assert {"cricket_content", "cricket_playlist"} <= names


# ─── live ───────────────────────────────────────────────────────────────


async def _first_completed_fixture(server):
    res = await server.call_tool("cricket_fixtures", {"isCompleted": True, "limit": 5})
    data = _payload(res)
    fx = data["fixtures"]
    assert fx
    return fx[0]


@pytest.mark.live
async def test_fixtures_live(cricket_server):
    """The /matches feed returns fixtures with ids + team/competition refs."""
    try:
        f = await _first_completed_fixture(cricket_server)
    except (MCPToolError, RuntimeError) as e:
        pytest.xfail(f"apiv2.cricket.com.au unavailable: {e}")
    assert "id" in f and "competitionId" in f and "homeTeamId" in f


@pytest.mark.live
async def test_scorecard_and_players_live(cricket_server):
    """Scorecard yields innings + a players[] lookup; those ids resolve via cricket_players."""
    try:
        f = await _first_completed_fixture(cricket_server)
        sc = _payload(await cricket_server.call_tool("cricket_scorecard", {"fixtureId": f["id"]}))
    except (MCPToolError, RuntimeError) as e:
        pytest.xfail(f"apiv2.cricket.com.au unavailable: {e}")
    assert "fixture" in sc and "innings" in sc["fixture"]
    players = sc.get("players") or []
    if not players:
        pytest.skip("no players on this scorecard")
    ids = [p["id"] for p in players[:5]]
    res = _payload(await cricket_server.call_tool("cricket_players", {"playerIds": ids}))
    assert res["players"] and "displayName" in res["players"][0]


@pytest.mark.live
async def test_standings_live(cricket_server):
    """Ladder for the fixture's competition (skip if that competition has no points table)."""
    try:
        f = await _first_completed_fixture(cricket_server)
        res = _payload(
            await cricket_server.call_tool("cricket_standings", {"competitionId": f["competitionId"]})
        )
    except (MCPToolError, RuntimeError) as e:
        pytest.xfail(f"apiv2.cricket.com.au unavailable: {e}")
    standings = res.get("standings") or []
    if not standings:
        pytest.skip("competition has no points table")
    assert "teamId" in standings[0] and "netRunRate" in standings[0]


@pytest.mark.live
async def test_content_live(cricket_server):
    """Pulselive CMS returns a paginated video list."""
    try:
        res = _payload(
            await cricket_server.call_tool("cricket_content", {"contentType": "VIDEO", "pageSize": 3})
        )
    except (MCPToolError, RuntimeError) as e:
        pytest.xfail(f"pulselive CMS unavailable: {e}")
    assert "pageInfo" in res and "content" in res
