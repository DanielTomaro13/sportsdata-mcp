"""Polymarket — registration checks (offline) + live probes against the public read hosts.

All three hosts (gamma-api / clob / data-api) are anonymous for reads. On some
networks the OS resolver returns a dead sinkhole IP for ``*.polymarket.com``
(observed on an AU residential line 2026-07-06: every host → one unreachable
Azure IP, while public DNS returns the real Cloudflare edge) — the spec's
``resolve_via_doh`` bypasses that by resolving through DoH. The live tests
still ``xfail`` where even DoH cannot reach the edge (a genuine block). Run::

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


# ─── offline: DoH resolution path ─────────────────────────────────────────


def test_polymarket_opts_into_doh():
    """The spec resolves via DoH so a poisoned OS resolver cannot blind the feed."""
    from sportsdata_mcp.spec_loader import load_all_specs

    spec = next(s for s in load_all_specs() if s.provider.id == "polymarket")
    assert spec.provider.defaults.resolve_via_doh is True


async def test_doh_backend_swaps_ip_keeps_hostname(monkeypatch):
    """The backend connects to the DoH-resolved IP but leaves host/SNI untouched
    (httpcore starts TLS against the original hostname, so certs still verify)."""
    from sportsdata_mcp.dns import DohResolver, _DohBackend

    resolver = DohResolver()

    async def fake_resolve(host):
        assert host == "gamma-api.polymarket.com"
        return "104.18.34.205"

    monkeypatch.setattr(resolver, "resolve", fake_resolve)

    seen: dict[str, str] = {}

    async def fake_super_connect(self, host, port, **kw):
        seen["host"] = host
        return object()  # a stand-in stream; connect_tcp only returns it

    monkeypatch.setattr("httpcore.AnyIOBackend.connect_tcp", fake_super_connect)
    backend = _DohBackend(resolver, frozenset({"gamma-api.polymarket.com"}))

    await backend.connect_tcp("gamma-api.polymarket.com", 443)
    assert seen["host"] == "104.18.34.205"  # dialled the real edge IP
    # a host NOT in the override set falls through to the OS resolver unchanged
    await backend.connect_tcp("example.com", 443)
    assert seen["host"] == "example.com"


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
