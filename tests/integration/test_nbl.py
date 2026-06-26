"""NBL (nbl.com.au) — registration (offline) + live probes.

NBL's site data API is a Redis-cached proxy ("rosetta") over Genius Sports stats:
`https://prod.rosetta.nbl.com.au/get/{route}`. No token, but REFERER-GATED — it
403s without an nbl.com.au Origin + Referer (both baked into the spec). The live
tests xfail if the site is unreachable. Run with::

    pytest -m live tests/integration/test_nbl.py
"""

from __future__ import annotations

import json

import pytest
from fastmcp.exceptions import ToolError as MCPToolError

from sportsdata_mcp.config import Config
from sportsdata_mcp.server import build_server

YEAR = 2025  # NBL26 (the 2025-26 season) is current
NBL26_SEASON_ID = "1f8e4a79-e98b-457b-85a5-e4b898c6c0bd"


@pytest.fixture
async def nbl_server():
    mcp, reg = build_server(Config(enabled_groups=["nbl.basketball"]))
    try:
        yield mcp
    finally:
        await reg.aclose()


def _payload(result):
    if result.structured_content is not None:
        return result.structured_content
    return json.loads(result.content[0].text)


# ─── offline: registration ──────────────────────────────────────────────


async def test_nbl_tools_registered(nbl_server):
    names = {t.name for t in await nbl_server.list_tools()}
    assert {
        "nbl_seasons", "nbl_teams", "nbl_ladder", "nbl_schedule",
        "nbl_players", "nbl_player_stats", "nbl_team_stats", "nbl_stat_leaders",
    } <= names


async def test_referer_gate_headers_baked_in(nbl_server):
    # The proxy 403s without an nbl.com.au Origin + Referer; assert the spec carries them.
    from pathlib import Path

    from sportsdata_mcp.spec_loader import load_spec

    spec = load_spec(Path("src/sportsdata_mcp/specs/nbl.yaml"))
    h = {k.lower(): v for k, v in spec.provider.default_headers.items()}
    assert "nbl.com.au" in h.get("origin", "") and "nbl.com.au" in h.get("referer", "")


# ─── live: prod.rosetta.nbl.com.au (referer-gated → xfail if blocked) ────


@pytest.mark.live
async def test_ladder_live(nbl_server):
    try:
        res = _payload(await nbl_server.call_tool("nbl_ladder", {"year": YEAR, "seasonType": "regular"}))
    except (MCPToolError, RuntimeError) as e:
        pytest.xfail(f"nbl unavailable: {e}")
    rows = res["data"]
    assert res["count"] == 10 and len(rows) == 10  # NBL has 10 clubs
    assert {"position", "won", "lost"} <= set(rows[0])


@pytest.mark.live
async def test_schedule_and_teams_live(nbl_server):
    try:
        sch = _payload(await nbl_server.call_tool("nbl_schedule", {"year": YEAR, "seasonType": "all"}))
        teams = _payload(await nbl_server.call_tool("nbl_teams", {}))
    except (MCPToolError, RuntimeError) as e:
        pytest.xfail(f"nbl unavailable: {e}")
    assert sch["data"] and {"home_team", "away_team", "round"} <= set(sch["data"][0])
    assert teams["count"] >= 10 and {"id", "name", "team_code"} <= set(teams["data"][0])


@pytest.mark.live
async def test_players_have_split_names_live(nbl_server):
    try:
        pl = _payload(await nbl_server.call_tool("nbl_players", {"year": YEAR}))
    except (MCPToolError, RuntimeError) as e:
        pytest.xfail(f"nbl unavailable: {e}")
    assert pl["count"] > 50
    player = pl["data"][0]["player"]
    assert "first_name" in player and "last_name" in player


@pytest.mark.live
async def test_stat_leaders_by_season_uuid_live(nbl_server):
    """Stat leaders are scoped by the season UUID (not the year)."""
    try:
        res = _payload(await nbl_server.call_tool("nbl_stat_leaders", {"seasonId": NBL26_SEASON_ID, "limit": 5}))
    except (MCPToolError, RuntimeError) as e:
        pytest.xfail(f"nbl unavailable: {e}")
    assert isinstance(res.get("data"), list)


@pytest.mark.live
async def test_seasons_discovery_live(nbl_server):
    try:
        res = _payload(await nbl_server.call_tool("nbl_seasons", {}))
    except (MCPToolError, RuntimeError) as e:
        pytest.xfail(f"nbl unavailable: {e}")
    assert res["count"] > 10
    assert {"id", "name", "year", "season_type"} <= set(res["data"][0])
