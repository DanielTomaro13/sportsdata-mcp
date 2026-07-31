"""Unibet — catalogue/registration checks (offline) + live probes.

Two surfaces under one provider:
  * unibet.racing — persisted-query GraphQL at rsa.unibet.com.au (graphql_persisted).
  * unibet.sport  — the Kambi offering API (*.kambicdn.com), open REST.

The offline tests check registration + both dispatcher catalogues + the unknown-op
error path. The ``live`` tests hit the real hosts; they ``xfail`` on host
unavailability / a drifted persisted hash and assert on stable structure. Run with::

    pytest -m live tests/integration/test_unibet.py
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pytest
from fastmcp.exceptions import ToolError as MCPToolError

from sportsdata_mcp.config import Config
from sportsdata_mcp.server import build_server

UNIBET_GROUPS = ["unibet.racing", "unibet.sport"]


@pytest.fixture
async def unibet_server():
    mcp, reg = build_server(Config(enabled_groups=UNIBET_GROUPS))
    try:
        yield mcp
    finally:
        await reg.aclose()


def _payload(result):
    if result.structured_content is not None:
        return result.structured_content
    return json.loads(result.content[0].text)


def _catalogue(payload_resource) -> dict:
    return json.loads(payload_resource.contents[0].content)


def _day_window():
    today = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    fmt = "%Y-%m-%dT%H:%M:%S.000Z"
    return today.strftime(fmt), (today + timedelta(days=1)).strftime(fmt)


# ─── offline: registration + catalogues + error path ───────────────────


async def test_unibet_tools_registered(unibet_server):
    names = {t.name for t in await unibet_server.list_tools()}
    assert {"unibet_racing_call", "unibet_kambi_call"} <= names
    assert {"unibet_kambi_live_stats", "unibet_kambi_odds_ladder"} <= names


async def test_racing_catalogue_lists_operations(unibet_server):
    payload = _catalogue(await unibet_server.read_resource("unibet://racing/operations"))
    assert payload["dispatcher"] == "unibet_racing_call"
    names = {op["name"] for op in payload["operations"]}
    assert {"MeetingsByDateRange", "EventQuery", "FormQuery", "FuturesQuery"} <= names
    # persisted provider → the note advertises hashes server-side
    assert "hash" in payload["note"].lower()


async def test_sport_catalogue_lists_operations(unibet_server):
    payload = _catalogue(await unibet_server.read_resource("unibet://sport/operations"))
    assert payload["dispatcher"] == "unibet_kambi_call"
    ops = {op["name"]: op for op in payload["operations"]}
    assert {"group", "inplay", "event_betoffer", "sport_matches"} <= set(ops)
    assert ops["event_betoffer"]["path_params"] == ["eventId"]


async def test_unknown_sport_operation_is_recoverable(unibet_server):
    with pytest.raises(MCPToolError) as ei:
        await unibet_server.call_tool("unibet_kambi_call", {"operation": "notARealOp"})
    assert "unibet://sport/operations" in str(ei.value)
    assert "notARealOp" in str(ei.value)


# ─── live: rsa.unibet.com.au (persisted racing GraphQL) ─────────────────


@pytest.mark.live
async def test_racing_futures_live(unibet_server):
    """FuturesQuery takes no variables — the simplest racing probe (also exercises the
    Apollo CSRF Content-Type header carried in provider defaults)."""
    try:
        res = await unibet_server.call_tool("unibet_racing_call", {"operation": "FuturesQuery"})
    except (MCPToolError, RuntimeError) as e:
        pytest.xfail(f"rsa.unibet.com.au unavailable: {e}")
    data = _payload(res)
    assert not data.get("errors"), data.get("errors")
    assert "futures" in data["data"]["viewer"]


@pytest.mark.live
async def test_racing_event_chains_off_meetings_live(unibet_server):
    """Discovery flow: meetings for today → an eventKey → the race's EventQuery card.
    Skips when no AUS thoroughbred meetings; xfails on a drifted hash / host issue."""
    start, end = _day_window()
    try:
        mt = await unibet_server.call_tool(
            "unibet_racing_call",
            {
                "operation": "MeetingsByDateRange",
                "variables": {
                    "startDateTime": start, "endDateTime": end,
                    "countryCodes": "AUS", "clientCountryCode": "AU", "raceTypes": ["T"],
                },
            },
        )
    except (MCPToolError, RuntimeError) as e:
        pytest.xfail(f"rsa.unibet.com.au unavailable: {e}")
    meetings = _payload(mt).get("data", {}).get("viewer", {}).get("meetingsByDateRange", [])
    if not meetings or not meetings[0].get("events"):
        pytest.skip("no AUS thoroughbred meetings today")
    event_key = meetings[0]["events"][0]["eventKey"]
    try:
        ev = await unibet_server.call_tool(
            "unibet_racing_call",
            {"operation": "EventQuery", "variables": {"clientCountryCode": "AU", "eventKey": event_key, "fetchTRC": False}},
        )
    except (MCPToolError, RuntimeError) as e:
        pytest.xfail(f"EventQuery unavailable for {event_key}: {e}")
    data = _payload(ev)
    assert not data.get("errors"), data.get("errors")
    assert data["data"]["viewer"].get("event") is not None


# ─── live: *.kambicdn.com (Kambi sport REST) ────────────────────────────


@pytest.mark.live
async def test_kambi_group_live(unibet_server):
    """The Kambi group tree is schedule-independent (always a sport hierarchy)."""
    try:
        res = await unibet_server.call_tool("unibet_kambi_call", {"operation": "group"})
    except (MCPToolError, RuntimeError) as e:
        pytest.xfail(f"ap.offering-api.kambicdn.com unavailable: {e}")
    data = _payload(res)
    assert "group" in data and "groups" in data["group"]


@pytest.mark.live
async def test_kambi_betoffer_chains_off_inplay_live(unibet_server):
    """Pull an in-play event id, then fetch its bet offers (markets). Skips when nothing
    is in-play; xfails on a host issue."""
    try:
        ip = await unibet_server.call_tool("unibet_kambi_call", {"operation": "inplay"})
    except (MCPToolError, RuntimeError) as e:
        pytest.xfail(f"ap.offering-api.kambicdn.com unavailable: {e}")
    events = _payload(ip).get("events", [])
    if not events:
        pytest.skip("nothing in-play right now")
    ev = events[0].get("event", events[0])
    event_id = ev["id"]
    try:
        bo = await unibet_server.call_tool(
            "unibet_kambi_call", {"operation": "event_betoffer", "path_params": {"eventId": event_id}}
        )
    except (MCPToolError, RuntimeError) as e:
        pytest.xfail(f"betoffer unavailable for {event_id}: {e}")
    data = _payload(bo)
    assert "betOffers" in data
