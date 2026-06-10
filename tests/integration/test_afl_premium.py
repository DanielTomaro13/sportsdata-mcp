"""Live integration tests for AFL premium (api.afl.com.au, x-media-mis-token).

Marked ``live`` — skipped by default. Run with::

    pytest -m live tests/integration/test_afl_premium.py

These mint the anonymous WMCTok and call token-gated CFS/StatsPro endpoints. The
WMCTok mint is not guaranteed to succeed anonymously (AFL may require credentials);
when it cannot mint, the call surfaces a clean ToolError rather than crashing, and
the test xfails so the suite stays green on a machine without working premium access.
"""

from __future__ import annotations

import json

import pytest

from sportsdata_mcp.config import Config
from sportsdata_mcp.errors import ToolError
from sportsdata_mcp.server import build_server

pytestmark = pytest.mark.live

# A 2026 AFL comp-season / match providerId from the documentation examples.
SEASON_PROVIDER_ID = "CD_S2026014"
MATCH_PROVIDER_ID = "CD_M20260141201"


@pytest.fixture
async def premium_server():
    mcp, reg = build_server(Config(enabled_groups=["afl.premium.cfs", "afl.premium.statspro"]))
    try:
        yield mcp
    finally:
        await reg.aclose()


def _structured(result):
    return result.structured_content


async def test_cfs_operations_catalogue_lists_26(premium_server):
    result = await premium_server.read_resource("afl://cfs/operations")
    payload = json.loads(result.contents[0].content)
    assert len(payload["operations"]) == 26
    names = {op["name"] for op in payload["operations"]}
    assert "matchItem" in names and "commentaryFeed" in names


async def test_statspro_operations_catalogue_lists_11(premium_server):
    result = await premium_server.read_resource("afl://statspro/operations")
    payload = json.loads(result.contents[0].content)
    assert len(payload["operations"]) == 11  # spec gained 2 ops in the v0.2.0 coverage pass
    assert any(op["name"] == "leadingPlayerStats_season" for op in payload["operations"])


async def test_bogus_operation_is_recoverable_error(premium_server):
    """A bad operation name fails fast with a catalogue pointer — no token needed."""
    from fastmcp.exceptions import ToolError as FastMCPToolError

    # fastmcp >= 3.3 wraps dispatcher errors in its own ToolError; the recoverable
    # contract (catalogue pointer in the message) is what matters
    with pytest.raises((ToolError, FastMCPToolError)) as ei:
        await premium_server.call_tool("afl_cfs_call", {"operation": "doesNotExist"})
    assert "afl://cfs/operations" in str(ei.value)


async def test_cfs_match_item_live(premium_server):
    """Requires a working anonymous WMCTok; xfail if premium auth is unavailable."""
    try:
        res = await premium_server.call_tool(
            "afl_cfs_call",
            {"operation": "matchItem", "path_params": {"matchProviderId": MATCH_PROVIDER_ID}},
        )
    except (ToolError, RuntimeError) as e:
        pytest.xfail(f"premium auth unavailable: {e}")
    data = _structured(res)
    assert isinstance(data, dict) and data


async def test_statspro_leaders_live(premium_server):
    try:
        res = await premium_server.call_tool(
            "afl_statspro_call",
            {
                "operation": "leadingPlayerStats_season",
                "path_params": {"seasonProviderId": SEASON_PROVIDER_ID},
                "query_params": {"limit": 5},
            },
        )
    except (ToolError, RuntimeError) as e:
        pytest.xfail(f"premium auth unavailable: {e}")
    data = _structured(res)
    assert isinstance(data, dict) and data
