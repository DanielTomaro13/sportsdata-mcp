"""Data Golf — registration (offline) + live probes (need DATAGOLF_KEY).

Data Golf authenticates with a personal `?key=` (the `static_query` auth scheme,
sourced from the DATAGOLF_KEY env var). The offline test checks registration and
runs everywhere; the ``live`` tests need a real key and ``skip`` when DATAGOLF_KEY
is unset. Run with::

    DATAGOLF_KEY=... pytest -m live tests/integration/test_datagolf.py
"""

from __future__ import annotations

import json
import os

import pytest
from fastmcp.exceptions import ToolError as MCPToolError

from sportsdata_mcp.config import Config
from sportsdata_mcp.server import build_server

DATAGOLF_GROUPS = ["datagolf.general", "datagolf.predictions", "datagolf.betting"]
_NO_KEY = not os.environ.get("DATAGOLF_KEY")


@pytest.fixture
async def datagolf_server():
    mcp, reg = build_server(Config(enabled_groups=DATAGOLF_GROUPS))
    try:
        yield mcp
    finally:
        await reg.aclose()


def _payload(result):
    if result.structured_content is not None:
        return result.structured_content
    return json.loads(result.content[0].text) if result.content else None


# ─── offline: registration ──────────────────────────────────────────────


async def test_datagolf_tools_registered(datagolf_server):
    names = {t.name for t in await datagolf_server.list_tools()}
    assert {"datagolf_player_list", "datagolf_schedule", "datagolf_field_updates"} <= names
    assert {"datagolf_rankings", "datagolf_pre_tournament", "datagolf_skill_ratings"} <= names
    assert {"datagolf_outrights", "datagolf_matchups"} <= names


# ─── live: feeds.datagolf.com (needs DATAGOLF_KEY) ──────────────────────


@pytest.mark.live
@pytest.mark.skipif(_NO_KEY, reason="DATAGOLF_KEY not set")
async def test_player_list_live(datagolf_server):
    """The player list is a stable top-level array (and proves the static_query key works)."""
    try:
        res = await datagolf_server.call_tool("datagolf_player_list", {})
    except (MCPToolError, RuntimeError) as e:
        pytest.xfail(f"feeds.datagolf.com unavailable: {e}")
    data = _payload(res)
    assert isinstance(data, list) and data
    assert "dg_id" in data[0] and "player_name" in data[0]


@pytest.mark.live
@pytest.mark.skipif(_NO_KEY, reason="DATAGOLF_KEY not set")
async def test_rankings_live(datagolf_server):
    """DG rankings carry skill estimates + OWGR rank."""
    try:
        res = await datagolf_server.call_tool("datagolf_rankings", {})
    except (MCPToolError, RuntimeError) as e:
        pytest.xfail(f"feeds.datagolf.com unavailable: {e}")
    data = _payload(res)
    assert "rankings" in data and isinstance(data["rankings"], list)


@pytest.mark.live
@pytest.mark.skipif(_NO_KEY, reason="DATAGOLF_KEY not set")
async def test_outrights_cross_book_live(datagolf_server):
    """The headline feature: outright odds across many sportsbooks for the current event."""
    try:
        res = await datagolf_server.call_tool("datagolf_outrights", {"tour": "pga", "market": "win"})
    except (MCPToolError, RuntimeError) as e:
        pytest.xfail(f"feeds.datagolf.com unavailable: {e}")
    data = _payload(res)
    assert "books_offering" in data and isinstance(data["books_offering"], list)
