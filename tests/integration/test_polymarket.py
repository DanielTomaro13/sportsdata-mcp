"""Polymarket — registration checks (offline) + live probes against the public read hosts.

All three hosts (gamma-api / clob / data-api) are anonymous for reads. Polymarket
drops connections at the network edge from restricted jurisdictions (observed:
AU IPs time out on connect) — the live tests ``xfail`` there and pass from
unrestricted regions (e.g. US CI runners). Run with::

    pytest -m live tests/integration/test_polymarket.py
"""

from __future__ import annotations

import json

import pytest
from fastmcp.exceptions import ToolError as MCPToolError

from sportsdata_mcp.config import Config
from sportsdata_mcp.server import build_server

POLYMARKET_GROUPS = ["polymarket.gamma", "polymarket.clob", "polymarket.data"]


@pytest.fixture
async def polymarket_server():
    mcp, reg = build_server(Config(enabled_groups=POLYMARKET_GROUPS))
    try:
        yield mcp
    finally:
        await reg.aclose()


def _payload(result):
    if result.structured_content is not None:
        return result.structured_content
    return json.loads(result.content[0].text)


def _rows(data):
    """Gamma list endpoints return a top-level array; FastMCP wraps arrays in {result: [...]}."""
    if isinstance(data, dict) and "result" in data:
        return data["result"]
    return data


# ─── offline: registration ──────────────────────────────────────────────


async def test_polymarket_tools_registered(polymarket_server):
    names = {t.name for t in await polymarket_server.list_tools()}
    assert {"polymarket_markets", "polymarket_market", "polymarket_events", "polymarket_event"} <= names
    assert {"polymarket_tags", "polymarket_search"} <= names
    assert {
        "polymarket_book",
        "polymarket_price",
        "polymarket_midpoint",
        "polymarket_spread",
        "polymarket_price_history",
        "polymarket_clob_markets",
    } <= names
    assert {"polymarket_trades", "polymarket_holders"} <= names


# ─── live: gamma-api / clob (geo-gated; xfail where blocked) ────────────


@pytest.mark.live
async def test_markets_live(polymarket_server):
    """Active markets resolve with question + outcome prices (top-level array)."""
    try:
        res = await polymarket_server.call_tool(
            "polymarket_markets", {"limit": 3, "active": True, "closed": False}
        )
    except (MCPToolError, RuntimeError) as e:
        pytest.xfail(f"polymarket unavailable (geo-gated?): {e}")
    rows = _rows(_payload(res))
    assert rows and "question" in rows[0]


@pytest.mark.live
async def test_event_to_book_live(polymarket_server):
    """An active event's market drills into a CLOB order book via clobTokenIds."""
    try:
        res = await polymarket_server.call_tool(
            "polymarket_events",
            {"limit": 3, "active": True, "closed": False, "order": "volume24hr", "ascending": False},
        )
        events = _rows(_payload(res))
        token_id = None
        for ev in events:
            for mk in ev.get("markets") or []:
                ids = mk.get("clobTokenIds")
                if isinstance(ids, str):
                    ids = json.loads(ids)
                if ids:
                    token_id = ids[0]
                    break
            if token_id:
                break
        if token_id is None:
            pytest.skip("no event with CLOB token ids right now")
        book = _payload(await polymarket_server.call_tool("polymarket_book", {"token_id": token_id}))
    except (MCPToolError, RuntimeError) as e:
        pytest.xfail(f"polymarket unavailable (geo-gated?): {e}")
    assert "bids" in book and "asks" in book
