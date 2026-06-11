"""Kalshi — registration checks (offline) + live probes against trade-api/v2.

Market data is public (no key); the RSA-signed portfolio/trading surfaces are
out of scope. Live tests ``xfail`` if the host is unreachable and ``skip`` on
schedule-dependent emptiness. Run with::

    pytest -m live tests/integration/test_kalshi.py
"""

from __future__ import annotations

import json

import pytest
from fastmcp.exceptions import ToolError as MCPToolError

from sportsdata_mcp.config import Config
from sportsdata_mcp.server import build_server

KALSHI_GROUPS = ["kalshi.markets", "kalshi.events", "kalshi.exchange"]


@pytest.fixture
async def kalshi_server():
    mcp, reg = build_server(Config(enabled_groups=KALSHI_GROUPS))
    try:
        yield mcp
    finally:
        await reg.aclose()


def _payload(result):
    if result.structured_content is not None:
        return result.structured_content
    return json.loads(result.content[0].text)


# ─── offline: registration ──────────────────────────────────────────────


async def test_kalshi_tools_registered(kalshi_server):
    names = {t.name for t in await kalshi_server.list_tools()}
    assert {"kalshi_markets", "kalshi_market", "kalshi_orderbook", "kalshi_trades", "kalshi_candlesticks"} <= names
    assert {"kalshi_events", "kalshi_event", "kalshi_series_list", "kalshi_series", "kalshi_milestones"} <= names
    assert {"kalshi_exchange_status", "kalshi_exchange_schedule", "kalshi_exchange_announcements"} <= names


# ─── live: api.elections.kalshi.com ─────────────────────────────────────


@pytest.mark.live
async def test_markets_and_drilldown_live(kalshi_server):
    """A page of open markets resolves; its first ticker drills into market + orderbook."""
    try:
        res = await kalshi_server.call_tool("kalshi_markets", {"limit": 5, "status": "open"})
        markets = _payload(res)["markets"]
        if not markets:
            pytest.skip("no open markets right now")
        ticker = markets[0]["ticker"]
        one = _payload(await kalshi_server.call_tool("kalshi_market", {"ticker": ticker}))
        book = _payload(await kalshi_server.call_tool("kalshi_orderbook", {"ticker": ticker, "depth": 3}))
    except (MCPToolError, RuntimeError) as e:
        pytest.xfail(f"kalshi unavailable: {e}")
    assert one["market"]["ticker"] == ticker
    assert "orderbook_fp" in book or "orderbook" in book


@pytest.mark.live
async def test_events_and_series_live(kalshi_server):
    """Open events resolve; the sports series catalogue is non-empty."""
    try:
        ev = _payload(await kalshi_server.call_tool("kalshi_events", {"limit": 3, "status": "open"}))
        sr = _payload(await kalshi_server.call_tool("kalshi_series_list", {"category": "Sports"}))
    except (MCPToolError, RuntimeError) as e:
        pytest.xfail(f"kalshi unavailable: {e}")
    assert "events" in ev
    assert sr["series"] and "ticker" in sr["series"][0]


@pytest.mark.live
async def test_exchange_status_live(kalshi_server):
    try:
        res = await kalshi_server.call_tool("kalshi_exchange_status", {})
    except (MCPToolError, RuntimeError) as e:
        pytest.xfail(f"kalshi unavailable: {e}")
    data = _payload(res)
    assert "exchange_active" in data
