"""BetR — registration checks (offline) + live probes against the BlueBet API.

BetR runs on the BlueBet platform; the data API is ``web20-api.bluebet.com.au``
(anonymous, no key). The offline test checks registration; the ``live`` tests hit
the real API and assert on stable structure, ``xfail``-ing if the host is
unreachable and skipping on schedule-dependent emptiness. Run with::

    pytest -m live tests/integration/test_betr.py
"""

from __future__ import annotations

import json

import pytest
from fastmcp.exceptions import ToolError as MCPToolError

from sportsdata_mcp.config import Config
from sportsdata_mcp.server import build_server

BETR_GROUPS = ["betr.racing", "betr.sport", "betr.content"]


@pytest.fixture
async def betr_server():
    mcp, reg = build_server(Config(enabled_groups=BETR_GROUPS))
    try:
        yield mcp
    finally:
        await reg.aclose()


def _payload(result):
    if result.structured_content is not None:
        return result.structured_content
    return json.loads(result.content[0].text)


# ─── offline: registration ──────────────────────────────────────────────


async def test_betr_tools_registered(betr_server):
    names = {t.name for t in await betr_server.list_tools()}
    assert {"betr_next5_races", "betr_grouped_racecard", "betr_race", "betr_race_form"} <= names
    assert {"betr_event_types", "betr_master_category", "betr_sports_category", "betr_master_event"} <= names
    assert {"betr_promotions", "betr_featured_racing"} <= names


# ─── live: web20-api.bluebet.com.au (racing) ────────────────────────────


@pytest.mark.live
async def test_event_types_live(betr_server):
    """The event-type catalogue is schedule-independent."""
    try:
        res = await betr_server.call_tool("betr_event_types", {})
    except (MCPToolError, RuntimeError) as e:
        pytest.xfail(f"web20-api.bluebet.com.au unavailable: {e}")
    data = _payload(res)
    assert "Items" in data and isinstance(data["Items"], list)


@pytest.mark.live
async def test_race_chains_off_next5_live(betr_server):
    """Discovery flow: pull a next-to-jump race id, then fetch its full card. Skips when
    no races are upcoming; xfails on a host issue."""
    try:
        n5 = await betr_server.call_tool("betr_next5_races", {})
    except (MCPToolError, RuntimeError) as e:
        pytest.xfail(f"web20-api.bluebet.com.au unavailable: {e}")
    items = _payload(n5).get("Items", [])
    if not items:
        pytest.skip("no upcoming races right now")
    event_id = items[0]["Race"]["EventId"]
    try:
        res = await betr_server.call_tool("betr_race", {"eventId": event_id})
    except (MCPToolError, RuntimeError) as e:
        pytest.xfail(f"race card unavailable for {event_id}: {e}")
    data = _payload(res)
    assert str(data.get("EventId")) == str(event_id)
    assert "EventName" in data


@pytest.mark.live
async def test_grouped_racecard_live(betr_server):
    """Today's meetings grouped by code — always present (codes may be empty off-peak)."""
    try:
        res = await betr_server.call_tool("betr_grouped_racecard", {"DaysToRace": 0})
    except (MCPToolError, RuntimeError) as e:
        pytest.xfail(f"web20-api.bluebet.com.au unavailable: {e}")
    data = _payload(res)
    assert "Thoroughbred" in data


# ─── live: web20-api.bluebet.com.au (sport) ─────────────────────────────


@pytest.mark.live
async def test_master_category_live(betr_server):
    """Basketball master categories (competitions) — schedule-independent structure."""
    try:
        res = await betr_server.call_tool("betr_master_category", {"EventTypeId": 107})
    except (MCPToolError, RuntimeError) as e:
        pytest.xfail(f"web20-api.bluebet.com.au unavailable: {e}")
    data = _payload(res)
    assert data.get("EventTypeId") == 107
    assert isinstance(data.get("MasterCategories"), list)


# ─── live: web20-api.bluebet.com.au (content) ───────────────────────────


@pytest.mark.live
async def test_promotions_live(betr_server):
    """Promotions metadata envelope is stable."""
    try:
        res = await betr_server.call_tool("betr_promotions", {})
    except (MCPToolError, RuntimeError) as e:
        pytest.xfail(f"web20-api.bluebet.com.au unavailable: {e}")
    data = _payload(res)
    assert "MetaData" in data or "Promotions" in data
