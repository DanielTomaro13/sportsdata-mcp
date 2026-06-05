"""Betfair Exchange — registration (offline) + live probes against the readonly web APIs.

Betfair's open read-only APIs (ero / ips / scan / cos), keyed by the public `_ak`
web key. The offline test checks registration; the ``live`` tests hit the real
hosts and assert on stable structure. The crown jewel is the exchange back/lay
price feed (``bymarket``); the live flow navigates the catalogue graph to a market
id, then prices it. Live tests ``xfail`` on a host issue and ``skip`` on emptiness.
Run with::

    pytest -m live tests/integration/test_betfair.py

(Note: comma-separated id params are ``string_csv`` — pass a Python list, e.g.
``{"marketIds": ["1.258654642"]}``; the engine serialises to CSV.)
"""

from __future__ import annotations

import json

import pytest
from fastmcp.exceptions import ToolError as MCPToolError

from sportsdata_mcp.config import Config
from sportsdata_mcp.server import build_server

BETFAIR_GROUPS = ["betfair.exchange", "betfair.navigation", "betfair.inplay"]


@pytest.fixture
async def betfair_server():
    mcp, reg = build_server(Config(enabled_groups=BETFAIR_GROUPS))
    try:
        yield mcp
    finally:
        await reg.aclose()


def _payload(result):
    if result.structured_content is not None:
        return result.structured_content
    return json.loads(result.content[0].text) if result.content else None


# ─── offline: registration ──────────────────────────────────────────────


async def test_betfair_tools_registered(betfair_server):
    names = {t.name for t in await betfair_server.list_tools()}
    assert {"betfair_market_prices", "betfair_cashout", "betfair_navigation"} <= names
    assert {"betfair_scores", "betfair_event_details", "betfair_event_timeline", "betfair_scores_broadcast"} <= names


# ─── live: the readonly web hosts ───────────────────────────────────────


@pytest.mark.live
async def test_navigation_live(betfair_server):
    """The navigation graph at the Horse Racing root is schedule-independent."""
    try:
        res = await betfair_server.call_tool("betfair_navigation", {"nodeIds": ["EVENT_TYPE:7"]})
    except (MCPToolError, RuntimeError) as e:
        pytest.xfail(f"scan-inbf.betfair.com.au unavailable: {e}")
    data = _payload(res)
    assert "nodes" in data and isinstance(data["nodes"], list)


@pytest.mark.live
async def test_market_prices_chain_live(betfair_server):
    """The core odds flow: walk the catalogue graph to a MARKET node, then pull its
    exchange back/lay prices. Skips if no market surfaces; xfails on a host issue."""
    try:
        nav = await betfair_server.call_tool(
            "betfair_navigation",
            {"nodeIds": ["EVENT_TYPE:7"], "attachments": ["MENU", "EVENT", "MARKET"],
             "maxOutDistance": 4, "maxResults": 400},
        )
    except (MCPToolError, RuntimeError) as e:
        pytest.xfail(f"scan-inbf.betfair.com.au unavailable: {e}")
    market_node = next((n for n in _payload(nav).get("nodes", []) if n.get("nodeType") == "MARKET"), None)
    if not market_node:
        pytest.skip("no market node surfaced in the racing tree right now")
    market_id = market_node["nodeId"].split(":")[-1]
    try:
        res = await betfair_server.call_tool("betfair_market_prices", {"marketIds": [market_id]})
    except (MCPToolError, RuntimeError) as e:
        pytest.xfail(f"ero.betfair.com.au unavailable: {e}")
    data = _payload(res)
    assert "eventTypes" in data and "currencyCode" in data


@pytest.mark.live
async def test_event_details_chain_live(betfair_server):
    """Navigate to an EVENT node, then fetch its in-play event details. Tolerant: the
    in-play service returns [] for events that aren't live."""
    try:
        nav = await betfair_server.call_tool(
            "betfair_navigation",
            {"nodeIds": ["EVENT_TYPE:1"], "attachments": ["MENU", "EVENT"], "maxOutDistance": 3, "maxResults": 200},
        )
    except (MCPToolError, RuntimeError) as e:
        pytest.xfail(f"scan-inbf.betfair.com.au unavailable: {e}")
    event_node = next((n for n in _payload(nav).get("nodes", []) if n.get("nodeType") == "EVENT"), None)
    if not event_node:
        pytest.skip("no event node surfaced")
    event_id = event_node["nodeId"].split(":")[-1]
    try:
        res = await betfair_server.call_tool("betfair_event_details", {"eventIds": [event_id]})
    except (MCPToolError, RuntimeError) as e:
        pytest.xfail(f"ips.betfair.com.au unavailable: {e}")
    data = _payload(res)
    assert isinstance(data, list)  # may be empty when the event isn't in-play
