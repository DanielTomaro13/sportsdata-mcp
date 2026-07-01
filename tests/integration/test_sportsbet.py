"""Sportsbet — catalogue/registration checks (offline) + live REST/gql probes.

The catalogue + registration + error-path tests run in the default suite (no
network). The ``live``-marked tests hit www.sportsbet.com.au/apigw; they xfail
rather than failing the suite when the gateway is unavailable or a persisted
GraphQL hash has drifted. Run live tests with::

    pytest -m live tests/integration/test_sportsbet.py
"""

from __future__ import annotations

import datetime as dt
import json

import pytest
from fastmcp.exceptions import ToolError as MCPToolError

from sportsdata_mcp.config import Config
from sportsdata_mcp.server import build_server

_GROUPS = [
    "sportsbet.racing",
    "sportsbet.sports",
    "sportsbet.results",
    "sportsbet.cross",
    "sportsbet.graphql",
]


@pytest.fixture
async def sportsbet_server():
    mcp, reg = build_server(Config(enabled_groups=_GROUPS))
    try:
        yield mcp
    finally:
        await reg.aclose()


def _structured(result):
    return result.structured_content


# ─── offline: catalogue + registration + error paths ───────────────────


async def test_graphql_catalogue_lists_eventstats_without_hashes(sportsbet_server):
    result = await sportsbet_server.read_resource("sportsbet://graphql/operations")
    payload = json.loads(result.contents[0].content)
    assert payload["provider"] == "sportsbet"
    names = {op["name"] for op in payload["operations"]}
    assert "EventStats" in names
    # Hashes are managed server-side and must NOT leak into the catalogue.
    assert "sha256" not in result.contents[0].content
    assert all("sha256" not in op and "hash" not in op for op in payload["operations"])


async def test_all_groups_register_expected_tools(sportsbet_server):
    names = {t.name for t in await sportsbet_server.list_tools()}
    # racing
    assert "sportsbet_racing_allracing" in names
    assert "sportsbet_racecard_with_context" in names
    assert "sportsbet_racing_popular_srms" in names
    # sports
    assert "sportsbet_event_markets" in names
    assert "sportsbet_sports_card" in names
    # results / cross / graphql
    assert "sportsbet_results_classes" in names
    assert "sportsbet_league_ladder" in names
    assert "sportsbet_trending_sgm" in names
    assert "sportsbet_graphql_call" in names


async def test_unknown_graphql_operation_is_recoverable(sportsbet_server):
    # FastMCP re-wraps our ToolError as fastmcp.exceptions.ToolError; the message
    # (with the catalogue pointer the model needs) is preserved.
    with pytest.raises(MCPToolError) as ei:
        await sportsbet_server.call_tool("sportsbet_graphql_call", {"operation": "NotARealOp"})
    assert "sportsbet://graphql/operations" in str(ei.value)
    assert "NotARealOp" in str(ei.value)


# ─── live: real gateway (xfail on network / drift) ─────────────────────


@pytest.mark.live
async def test_all_racing_live(sportsbet_server):
    today = dt.date.today().isoformat()
    try:
        res = await sportsbet_server.call_tool("sportsbet_racing_allracing", {"eventDate": today})
    except (MCPToolError, RuntimeError) as e:
        pytest.xfail(f"sportsbet racing gateway unavailable: {e}")
    data = _structured(res)
    assert isinstance(data, dict)


@pytest.mark.live
async def test_sports_classes_live(sportsbet_server):
    # The gateway requires naive datetimes (YYYY-MM-DDTHH:MM:SS); a bare date is a 400.
    now = dt.datetime.now().replace(microsecond=0)
    week = now + dt.timedelta(days=7)
    try:
        res = await sportsbet_server.call_tool(
            "sportsbet_sports_classes",
            {"fromDate": now.isoformat(), "toDate": week.isoformat()},
        )
    except (MCPToolError, RuntimeError) as e:
        pytest.xfail(f"sportsbet sports gateway unavailable: {e}")
    data = _structured(res)
    assert isinstance(data, dict)
    assert "classList" in data
