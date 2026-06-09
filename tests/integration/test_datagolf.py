"""Data Golf — registration (offline) + live probes (need DATAGOLF_KEY).

Data Golf authenticates with a personal `?key=` (the `static_query` auth scheme,
sourced from the DATAGOLF_KEY env var). The offline test checks registration and
runs everywhere; the ``live`` tests need a real key and ``skip`` when DATAGOLF_KEY
is unset. Run with::

    DATAGOLF_KEY=... pytest -m live tests/integration/test_datagolf.py
"""

from __future__ import annotations

import json
import os

import pytest
from fastmcp.exceptions import ToolError as MCPToolError

from sportsdata_mcp.config import Config
from sportsdata_mcp.server import build_server

DATAGOLF_GROUPS = [
    "datagolf.general",
    "datagolf.predictions",
    "datagolf.betting",
    "datagolf.historical",
]
_NO_KEY = not os.environ.get("DATAGOLF_KEY")


@pytest.fixture
async def datagolf_server():
    mcp, reg = build_server(Config(enabled_groups=DATAGOLF_GROUPS))
    try:
        yield mcp
    finally:
        await reg.aclose()


def _payload(result):
    if result.structured_content is not None:
        return result.structured_content
    return json.loads(result.content[0].text) if result.content else None


# ─── offline: registration ──────────────────────────────────────────────


async def test_datagolf_tools_registered(datagolf_server):
    names = {t.name for t in await datagolf_server.list_tools()}
    assert {"datagolf_player_list", "datagolf_schedule", "datagolf_field_updates"} <= names
    assert {"datagolf_rankings", "datagolf_pre_tournament", "datagolf_skill_ratings"} <= names
    # higher-tier predictions
    assert {
        "datagolf_pre_tournament_archive",
        "datagolf_player_decompositions",
        "datagolf_fantasy_projections",
        "datagolf_live_hole_stats",
        "datagolf_approach_skill",
        "datagolf_live_strokes_gained",
    } <= names
    # betting (incl. all-pairings)
    assert {"datagolf_outrights", "datagolf_matchups", "datagolf_matchups_all_pairings"} <= names
    # historical raw data / event results / odds / DFS
    assert {
        "datagolf_hist_event_list",
        "datagolf_hist_rounds",
        "datagolf_hist_results_event_list",
        "datagolf_hist_results",
        "datagolf_hist_odds_event_list",
        "datagolf_hist_outrights",
        "datagolf_hist_matchups",
        "datagolf_hist_dfs_event_list",
        "datagolf_hist_dfs_points",
    } <= names


# ─── live: feeds.datagolf.com (needs DATAGOLF_KEY) ──────────────────────


@pytest.mark.live
@pytest.mark.skipif(_NO_KEY, reason="DATAGOLF_KEY not set")
async def test_player_list_live(datagolf_server):
    """The player list is a stable top-level array (and proves the static_query key works)."""
    try:
        res = await datagolf_server.call_tool("datagolf_player_list", {})
    except (MCPToolError, RuntimeError) as e:
        pytest.xfail(f"feeds.datagolf.com unavailable: {e}")
    data = _payload(res)
    assert isinstance(data, list) and data
    assert "dg_id" in data[0] and "player_name" in data[0]


@pytest.mark.live
@pytest.mark.skipif(_NO_KEY, reason="DATAGOLF_KEY not set")
async def test_rankings_live(datagolf_server):
    """DG rankings carry skill estimates + OWGR rank."""
    try:
        res = await datagolf_server.call_tool("datagolf_rankings", {})
    except (MCPToolError, RuntimeError) as e:
        pytest.xfail(f"feeds.datagolf.com unavailable: {e}")
    data = _payload(res)
    assert "rankings" in data and isinstance(data["rankings"], list)


@pytest.mark.live
@pytest.mark.skipif(_NO_KEY, reason="DATAGOLF_KEY not set")
async def test_outrights_cross_book_live(datagolf_server):
    """The headline feature: outright odds across many sportsbooks for the current event."""
    try:
        res = await datagolf_server.call_tool("datagolf_outrights", {"tour": "pga", "market": "win"})
    except (MCPToolError, RuntimeError) as e:
        pytest.xfail(f"feeds.datagolf.com unavailable: {e}")
    data = _payload(res)
    assert "books_offering" in data and isinstance(data["books_offering"], list)


@pytest.mark.live
@pytest.mark.skipif(_NO_KEY, reason="DATAGOLF_KEY not set")
async def test_hist_event_list_live(datagolf_server):
    """Higher-tier: historical raw-data event list is a top-level array of past events."""
    try:
        res = await datagolf_server.call_tool("datagolf_hist_event_list", {"tour": "pga"})
    except (MCPToolError, RuntimeError) as e:
        pytest.xfail(f"feeds.datagolf.com unavailable / plan-gated: {e}")
    data = _payload(res)
    if not data:
        pytest.skip("no historical events returned")
    assert isinstance(data, list)
    assert "event_id" in data[0] and "calendar_year" in data[0]


@pytest.mark.live
@pytest.mark.skipif(_NO_KEY, reason="DATAGOLF_KEY not set")
async def test_fantasy_projections_live(datagolf_server):
    """Higher-tier: DFS fantasy projections for the current event/slate."""
    try:
        res = await datagolf_server.call_tool(
            "datagolf_fantasy_projections", {"tour": "pga", "site": "draftkings"}
        )
    except (MCPToolError, RuntimeError) as e:
        pytest.xfail(f"feeds.datagolf.com unavailable / plan-gated: {e}")
    data = _payload(res)
    assert data is not None
