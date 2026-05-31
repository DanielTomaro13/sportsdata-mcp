"""Entain (Ladbrokes) — catalogue/registration checks (offline) + live gql/REST probes.

The catalogue + error-path tests run in the default suite (no network). The
``live``-marked tests hit api.ladbrokes.com.au; because persisted-query hashes
drift on every front-end deploy, a stale hash surfaces a clean
``PERSISTED_QUERY_NOT_FOUND`` ToolError — those tests xfail rather than failing
the suite when the bundled hashes have rotated. Run live tests with::

    pytest -m live tests/integration/test_entain.py
"""

from __future__ import annotations

import json

import pytest
from fastmcp.exceptions import ToolError as MCPToolError

from sportsdata_mcp.config import Config
from sportsdata_mcp.server import build_server


@pytest.fixture
async def entain_server():
    mcp, reg = build_server(Config(enabled_groups=["entain.rest", "entain.graphql"]))
    try:
        yield mcp
    finally:
        await reg.aclose()


def _structured(result):
    return result.structured_content


# ─── offline: catalogue + registration + error paths ───────────────────


async def test_graphql_catalogue_lists_127_without_hashes(entain_server):
    result = await entain_server.read_resource("entain://graphql/operations")
    payload = json.loads(result.contents[0].content)
    assert payload["provider"] == "entain"
    assert len(payload["operations"]) == 127
    names = {op["name"] for op in payload["operations"]}
    assert "HomeSportsScreen" in names
    assert "RacingRaceCardScreenWeb" in names
    # Hashes are managed server-side and must NOT leak into the catalogue.
    assert "sha256" not in result.contents[0].content
    assert all("sha256" not in op and "hash" not in op for op in payload["operations"])


async def test_rest_and_dispatch_tools_registered(entain_server):
    names = {t.name for t in await entain_server.list_tools()}
    assert "entain_graphql_call" in names
    assert "entain_racing_meeting" in names
    assert "entain_sport_event_card" in names


async def test_unknown_graphql_operation_is_recoverable(entain_server):
    # FastMCP re-wraps our ToolError as fastmcp.exceptions.ToolError; the message
    # (with the catalogue pointer the model needs) is preserved.
    with pytest.raises(MCPToolError) as ei:
        await entain_server.call_tool("entain_graphql_call", {"operation": "NotARealOp"})
    assert "entain://graphql/operations" in str(ei.value)
    assert "NotARealOp" in str(ei.value)


# ─── live: real gateway (xfail on hash drift / network) ────────────────


@pytest.mark.live
async def test_home_sports_screen_live(entain_server):
    # call_tool wraps every handler error (including PERSISTED_QUERY_NOT_FOUND) as
    # fastmcp.ToolError; the message carries the refresh-hashes hint when hashes drift.
    try:
        res = await entain_server.call_tool(
            "entain_graphql_call",
            {"operation": "HomeSportsScreen", "variables": {"includeFeaturedEvents": True, "featuredEventsEventCount": 3}},
        )
    except (MCPToolError, RuntimeError) as e:
        pytest.xfail(f"entain gateway unavailable or hashes drifted (refresh-hashes entain): {e}")
    data = _structured(res)
    assert isinstance(data, dict) and "data" in data


@pytest.mark.live
async def test_racing_meeting_rest_live(entain_server):
    try:
        res = await entain_server.call_tool(
            "entain_racing_meeting",
            {"date": "2026-05-30", "timezone": "Australia/Melbourne"},
        )
    except (MCPToolError, RuntimeError) as e:
        pytest.xfail(f"entain REST unavailable: {e}")
    data = _structured(res)
    assert isinstance(data, dict)
    assert "meetings" in data or "races" in data
