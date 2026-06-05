"""Pinnacle — registration checks (offline) + live probes against the Arcadia guest API.

Pinnacle's data API is ``guest.api.arcadia.pinnacle.com/0.1`` (anonymous, no key).
The offline test checks registration; the ``live`` tests hit the real API. Most
endpoints return a top-level JSON array (``_payload`` normalises that). Live tests
``xfail`` if the host is unreachable and ``skip`` on schedule-dependent emptiness.
Run with::

    pytest -m live tests/integration/test_pinnacle.py
"""

from __future__ import annotations

import json

import pytest
from fastmcp.exceptions import ToolError as MCPToolError

from sportsdata_mcp.config import Config
from sportsdata_mcp.server import build_server

PINNACLE_GROUPS = ["pinnacle.sports", "pinnacle.reference"]


@pytest.fixture
async def pinnacle_server():
    mcp, reg = build_server(Config(enabled_groups=PINNACLE_GROUPS))
    try:
        yield mcp
    finally:
        await reg.aclose()


def _payload(result):
    if result.structured_content is not None:
        return result.structured_content
    return json.loads(result.content[0].text)


# ─── offline: registration ──────────────────────────────────────────────


async def test_pinnacle_tools_registered(pinnacle_server):
    names = {t.name for t in await pinnacle_server.list_tools()}
    assert {"pinnacle_sports", "pinnacle_sports_live", "pinnacle_sport_leagues"} <= names
    assert {"pinnacle_sport_matchups", "pinnacle_matchup", "pinnacle_matchup_markets"} <= names
    assert {"pinnacle_enums", "pinnacle_labels", "pinnacle_teasers", "pinnacle_status"} <= names


# ─── live: guest.api.arcadia.pinnacle.com ───────────────────────────────


@pytest.mark.live
async def test_sports_catalogue_live(pinnacle_server):
    """The sports catalogue is a stable top-level array."""
    try:
        res = await pinnacle_server.call_tool("pinnacle_sports", {})
    except (MCPToolError, RuntimeError) as e:
        pytest.xfail(f"guest.api.arcadia.pinnacle.com unavailable: {e}")
    data = _payload(res)
    assert isinstance(data, list) and data
    assert "name" in data[0] and "id" in data[0]


@pytest.mark.live
async def test_status_live(pinnacle_server):
    """The status endpoint reports system health (schedule-independent)."""
    try:
        res = await pinnacle_server.call_tool("pinnacle_status", {})
    except (MCPToolError, RuntimeError) as e:
        pytest.xfail(f"guest.api.arcadia.pinnacle.com unavailable: {e}")
    data = _payload(res)
    assert "code" in data


@pytest.mark.live
async def test_markets_chain_off_matchups_live(pinnacle_server):
    """The odds-comparison flow: live sport → a highlighted matchup → its straight
    markets (American-odds prices). Skips when nothing is on; xfails on a host issue."""
    try:
        live = await pinnacle_server.call_tool("pinnacle_sports_live", {})
    except (MCPToolError, RuntimeError) as e:
        pytest.xfail(f"guest.api.arcadia.pinnacle.com unavailable: {e}")
    sports = _payload(live)
    if not sports:
        pytest.skip("no live sports right now")
    sport_id = sports[0]["id"]
    try:
        mh = await pinnacle_server.call_tool("pinnacle_sport_matchups", {"sportId": sport_id})
    except (MCPToolError, RuntimeError) as e:
        pytest.xfail(f"guest.api.arcadia.pinnacle.com unavailable: {e}")
    matchups = [m for m in _payload(mh) if m.get("hasMarkets")]
    if not matchups:
        pytest.skip("no highlighted matchups with markets")
    matchup_id = matchups[0]["id"]
    try:
        res = await pinnacle_server.call_tool("pinnacle_matchup_markets", {"matchupId": matchup_id})
    except (MCPToolError, RuntimeError) as e:
        pytest.xfail(f"markets unavailable for {matchup_id}: {e}")
    markets = _payload(res)
    assert isinstance(markets, list)
    if markets:
        assert "key" in markets[0] and "prices" in markets[0]
