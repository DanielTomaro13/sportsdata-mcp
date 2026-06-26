"""WTA (api.wtatennis.com) — registration (offline) + live probes.

The WTA's official public API — Spring REST backend, no auth/key, not geo-blocked,
so the live tests run in CI (xfail if the API is unreachable). Run with::

    pytest -m live tests/integration/test_wta.py
"""

from __future__ import annotations

import json

import pytest
from fastmcp.exceptions import ToolError as MCPToolError

from sportsdata_mcp.config import Config
from sportsdata_mcp.server import build_server

SABALENKA = 320760
AO_GROUP = 901  # Australian Open tournamentGroup id


@pytest.fixture
async def wta_server():
    mcp, reg = build_server(Config(enabled_groups=["wta.tennis"]))
    try:
        yield mcp
    finally:
        await reg.aclose()


def _payload(result):
    if result.structured_content is not None:
        return result.structured_content
    return json.loads(result.content[0].text)


# ─── offline: registration ──────────────────────────────────────────────


async def test_wta_tools_registered(wta_server):
    names = {t.name for t in await wta_server.list_tools()}
    assert {
        "wta_rankings", "wta_players", "wta_player", "wta_player_matches",
        "wta_tournaments", "wta_tournament", "wta_tournament_matches",
    } <= names


async def test_rankings_requires_type_and_metric(wta_server):
    tools = {t.name: t for t in await wta_server.list_tools()}
    required = set(tools["wta_rankings"].parameters.get("required", []))
    assert {"type", "metric"} <= required


# ─── live: api.wtatennis.com (open API → xfail if unreachable) ───────────


@pytest.mark.live
async def test_rankings_live(wta_server):
    """The singles rankings return ranked rows with points + movement."""
    try:
        rows = _payload(
            await wta_server.call_tool("wta_rankings", {"type": "rankSingles", "metric": "singles", "pageSize": 10})
        )
    except (MCPToolError, RuntimeError) as e:
        pytest.xfail(f"wta unavailable: {e}")
    assert isinstance(rows, list) and len(rows) == 10
    top = rows[0]
    assert top["ranking"] == 1 and "points" in top and "fullName" in top["player"]


@pytest.mark.live
async def test_player_search_and_detail_live(wta_server):
    try:
        found = _payload(await wta_server.call_tool("wta_players", {"name": "Swiatek"}))
        pid = found["content"][0]["id"]
        detail = _payload(await wta_server.call_tool("wta_player", {"playerId": pid}))
    except (MCPToolError, RuntimeError) as e:
        pytest.xfail(f"wta unavailable: {e}")
    assert "Swiatek" in found["content"][0]["fullName"]
    assert detail["id"] == pid and "countryCode" in detail


@pytest.mark.live
async def test_tournament_matches_live(wta_server):
    """A tournament edition (group id + year) returns its match list."""
    try:
        tm = _payload(await wta_server.call_tool("wta_tournament_matches", {"groupId": AO_GROUP, "year": 2025}))
    except (MCPToolError, RuntimeError) as e:
        pytest.xfail(f"wta unavailable: {e}")
    matches = tm["matches"]
    assert matches and {"MatchID", "EventYear"} <= set(matches[0])


@pytest.mark.live
async def test_tournaments_calendar_live(wta_server):
    try:
        cal = _payload(await wta_server.call_tool("wta_tournaments", {"pageSize": 5}))
    except (MCPToolError, RuntimeError) as e:
        pytest.xfail(f"wta unavailable: {e}")
    assert cal["content"] and "tournamentGroup" in cal["content"][0]
