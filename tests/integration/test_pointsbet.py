"""PointsBet — catalogue/registration checks (offline) + live API probes.

The registration + catalogue + error-path tests run in the default suite (no
network). The ``live``-marked tests hit PointsBet's real, unauthenticated hosts:

  * ``api.au.pointsbet.com`` — the sportsbook sports + racing JSON API.
  * ``pointsbet.com.au``     — static CMS / navigation assets.

Many PointsBet endpoints return a *top-level JSON array*; FastMCP only populates
``structured_content`` for object responses, so array payloads arrive in the text
content block instead. ``_payload`` normalises both. Live tests are tolerant of
schedule-dependent emptiness (an off day with no meetings) and assert on stable
structure only; they ``xfail`` rather than fail when a host is unreachable. Run
them with::

    pytest -m live tests/integration/test_pointsbet.py
"""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest
from fastmcp.exceptions import ToolError as MCPToolError

from sportsdata_mcp.config import Config
from sportsdata_mcp.server import build_server

POINTSBET_GROUPS = ["pointsbet.sports", "pointsbet.racing", "pointsbet.content"]


@pytest.fixture
async def pointsbet_server():
    mcp, reg = build_server(Config(enabled_groups=POINTSBET_GROUPS))
    try:
        yield mcp
    finally:
        await reg.aclose()


def _payload(result):
    """Normalise a FastMCP tool result to its JSON payload.

    Object responses land in ``structured_content``; top-level-array responses
    (common on PointsBet) land in the text content block instead.
    """
    if result.structured_content is not None:
        return result.structured_content
    return json.loads(result.content[0].text)


def _catalogue(payload_resource) -> dict:
    return json.loads(payload_resource.contents[0].content)


def _today_window() -> tuple[str, str]:
    d = datetime.now(UTC).strftime("%Y-%m-%d")
    return f"{d}T00:00:00.000Z", f"{d}T23:59:59.000Z"


# ─── offline: registration + catalogue + error paths ───────────────────


async def test_pointsbet_tools_registered(pointsbet_server):
    names = {t.name for t in await pointsbet_server.list_tools()}
    # a spread of discrete sports + racing endpoints
    assert {"pointsbet_sports_inplay", "pointsbet_event", "pointsbet_sport_competitions"} <= names
    assert {"pointsbet_racing_meetings", "pointsbet_racing_race", "pointsbet_racing_srm"} <= names
    # the static-content surfaces: promotions, promo-code splash + dispatcher
    assert {"pointsbet_promotions", "pointsbet_promo_code", "pointsbet_content_call"} <= names


async def test_content_catalogue_lists_operations(pointsbet_server):
    payload = _catalogue(await pointsbet_server.read_resource("pointsbet://content/operations"))
    assert payload["dispatcher"] == "pointsbet_content_call"
    names = {op["name"] for op in payload["operations"]}
    assert {"league_menu", "quick_links", "logo_mappings", "app_manifest", "maintenance_kill"} <= names


async def test_unknown_content_operation_is_recoverable(pointsbet_server):
    # FastMCP re-wraps our ToolError; the catalogue pointer the model needs survives.
    with pytest.raises(MCPToolError) as ei:
        await pointsbet_server.call_tool("pointsbet_content_call", {"operation": "notarealop"})
    assert "pointsbet://content/operations" in str(ei.value)
    assert "notarealop" in str(ei.value)


# ─── live: api.au.pointsbet.com (sports) ────────────────────────────────


@pytest.mark.live
async def test_sports_inplay_live(pointsbet_server):
    """The in-play envelope is schedule-independent (the count may be zero off-peak)."""
    try:
        res = await pointsbet_server.call_tool("pointsbet_sports_inplay", {})
    except (MCPToolError, RuntimeError) as e:
        pytest.xfail(f"api.au.pointsbet.com unavailable: {e}")
    data = _payload(res)
    assert "sports" in data and "numberOfInPlayEvents" in data
    assert isinstance(data["sports"], list)


@pytest.mark.live
async def test_sport_competitions_live(pointsbet_server):
    """Aussie-rules always has its locale buckets with the AFL competition under them."""
    try:
        res = await pointsbet_server.call_tool("pointsbet_sport_competitions", {"sportKey": "aussie-rules"})
    except (MCPToolError, RuntimeError) as e:
        pytest.xfail(f"api.au.pointsbet.com unavailable: {e}")
    data = _payload(res)
    assert data.get("key") == "aussie-rules"
    assert isinstance(data.get("locales"), list)


@pytest.mark.live
async def test_event_chains_off_competition_events_live(pointsbet_server):
    """The documented discovery flow: pull an event key from the AFL competition feed,
    then fetch its full markets via pointsbet_event. Skips cleanly when the AFL has no
    listed events, xfails if the host is unreachable."""
    try:
        comp = await pointsbet_server.call_tool(
            "pointsbet_competition_events", {"competitionKey": 7523, "page": 1}
        )
    except (MCPToolError, RuntimeError) as e:
        pytest.xfail(f"api.au.pointsbet.com unavailable: {e}")
    events = _payload(comp).get("events", [])
    if not events:
        pytest.skip("no AFL events listed — nothing to price")
    event_key = events[0]["key"]
    try:
        res = await pointsbet_server.call_tool("pointsbet_event", {"eventKey": event_key})
    except (MCPToolError, RuntimeError) as e:
        pytest.xfail(f"api.au.pointsbet.com unavailable: {e}")
    data = _payload(res)
    assert str(data.get("key")) == str(event_key)
    # the full event detail carries the fixed-odds market list
    assert "fixedOddsMarkets" in data


# ─── live: api.au.pointsbet.com (racing) ────────────────────────────────


@pytest.mark.live
async def test_racing_race_chains_off_meetings_live(pointsbet_server):
    """Pull today's meetings, take the first meeting's first race id, then fetch that
    racecard. Skips on a day with no meetings, xfails if the host is unreachable."""
    start, end = _today_window()
    try:
        mtgs = await pointsbet_server.call_tool(
            "pointsbet_racing_meetings", {"startDate": start, "endDate": end}
        )
    except (MCPToolError, RuntimeError) as e:
        pytest.xfail(f"api.au.pointsbet.com unavailable: {e}")
    groups = _payload(mtgs)
    meetings = groups[0].get("meetings", []) if groups else []
    if not meetings or not meetings[0].get("races"):
        pytest.skip("no race meetings today — nothing to card")
    race_id = meetings[0]["races"][0]["raceId"]
    try:
        res = await pointsbet_server.call_tool("pointsbet_racing_race", {"raceId": race_id})
    except (MCPToolError, RuntimeError) as e:
        pytest.xfail(f"api.au.pointsbet.com unavailable: {e}")
    data = _payload(res)
    assert str(data.get("raceId")) == str(race_id)
    assert "venue" in data


# ─── live: pointsbet.com.au (static content dispatcher) ─────────────────


@pytest.mark.live
async def test_content_call_league_menu_live(pointsbet_server):
    """The static league menu is a stable top-level array of menu entries."""
    try:
        res = await pointsbet_server.call_tool("pointsbet_content_call", {"operation": "league_menu"})
    except (MCPToolError, RuntimeError) as e:
        pytest.xfail(f"pointsbet.com.au unavailable: {e}")
    data = _payload(res)
    assert isinstance(data, list)
    assert any("sportKey" in entry for entry in data)


@pytest.mark.live
async def test_promo_code_live(pointsbet_server):
    """The WELCOME promo-code splash is a stable static JSON asset."""
    try:
        res = await pointsbet_server.call_tool("pointsbet_promo_code", {"code": "WELCOME"})
    except (MCPToolError, RuntimeError) as e:
        pytest.xfail(f"pointsbet.com.au unavailable: {e}")
    data = _payload(res)
    assert isinstance(data, dict)
    assert "info" in data or "image" in data
