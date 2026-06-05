"""Racing and Sports — registration (offline) + live probes.

www.racingandsports.com.au sits behind Cloudflare, which JS-challenges most paths
from datacenter IPs. The `/todays-racing-json-v2` feed is whitelisted and verified
live here; the other JSON endpoints are reachable from a normal browser/residential
IP but get a 403 challenge from a datacenter, so their live tests ``xfail`` in that
environment (and pass where the host is reachable). Run with::

    pytest -m live tests/integration/test_racingandsports.py
"""

from __future__ import annotations

import json

import pytest
from fastmcp.exceptions import ToolError as MCPToolError

from sportsdata_mcp.config import Config
from sportsdata_mcp.server import build_server

RNS_GROUPS = ["racingandsports.racing"]


@pytest.fixture
async def rns_server():
    mcp, reg = build_server(Config(enabled_groups=RNS_GROUPS))
    try:
        yield mcp
    finally:
        await reg.aclose()


def _payload(result):
    if result.structured_content is not None:
        return result.structured_content
    return json.loads(result.content[0].text) if result.content else None


# ─── offline: registration ──────────────────────────────────────────────


async def test_rns_tools_registered(rns_server):
    names = {t.name for t in await rns_server.list_tools()}
    assert {"racingandsports_todays_racing", "racingandsports_match_list", "racingandsports_race_odds"} <= names


# ─── live ────────────────────────────────────────────────────────────────


@pytest.mark.live
async def test_todays_racing_live(rns_server):
    """The today's-racing feed is Cloudflare-whitelisted and schedule-independent: a
    top-level array of disciplines (T/H/G), each with countries → meetings."""
    try:
        res = await rns_server.call_tool("racingandsports_todays_racing", {})
    except (MCPToolError, RuntimeError) as e:
        pytest.xfail(f"www.racingandsports.com.au unavailable: {e}")
    data = _payload(res)
    assert isinstance(data, list) and data
    disc = data[0]
    assert "Discipline" in disc and "Countries" in disc
    assert isinstance(disc["Countries"], list)


@pytest.mark.live
async def test_match_list_live(rns_server):
    """The match-list feed is reachable from a browser/residential IP but Cloudflare-
    challenged from a datacenter — so this xfails when blocked, passes when reachable."""
    try:
        res = await rns_server.call_tool("racingandsports_match_list", {})
    except (MCPToolError, RuntimeError) as e:
        pytest.xfail(f"match-list-json Cloudflare-challenged from this IP: {e}")
    data = _payload(res)
    assert data is not None
