"""TAB (Tabcorp) — catalogue/registration checks (offline) + live API probes.

The registration + catalogue + error-path tests run in the default suite (no
network). The ``live``-marked tests hit TAB's real, unauthenticated hosts:

  * ``api.beta.tab.com.au/v1`` — racing + sports info-service (Akamai-fronted).
  * ``cmsapi.tab.com.au``      — CMS content feeds.

The info-service host sits behind Akamai, which RST-drops requests lacking the
browser header bundle (the spec ships it) and throttles bursts. Live tests are
tolerant: they ``xfail`` on any tool error (a transport reset surfaces as a
wrapped ToolError) and ``skip`` on schedule-dependent emptiness. Every TAB
endpoint requires a ``jurisdiction``; the spec defaults it to NSW. Run them with::

    pytest -m live tests/integration/test_tab.py
"""

from __future__ import annotations

import json

import pytest
from fastmcp.exceptions import ToolError as MCPToolError

from sportsdata_mcp.config import Config
from sportsdata_mcp.server import build_server

TAB_GROUPS = ["tab.racing", "tab.sports", "tab.discovery"]


@pytest.fixture
async def tab_server():
    mcp, reg = build_server(Config(enabled_groups=TAB_GROUPS))
    try:
        yield mcp
    finally:
        await reg.aclose()


def _payload(result):
    """Object responses land in structured_content; arrays in the text block."""
    if result.structured_content is not None:
        return result.structured_content
    return json.loads(result.content[0].text)


def _catalogue(payload_resource) -> dict:
    return json.loads(payload_resource.contents[0].content)


# ─── offline: registration + catalogue + error paths ───────────────────


async def test_tab_tools_registered(tab_server):
    names = {t.name for t in await tab_server.list_tools()}
    # a spread across racing + sports families
    assert {"tab_racing_meetings", "tab_racing_race", "tab_racing_next_to_go"} <= names
    assert {"tab_sports", "tab_sport", "tab_competition", "tab_match", "tab_match_markets"} <= names
    # the CMS content dispatcher
    assert "tab_cms_call" in names


async def test_cms_catalogue_lists_operations(tab_server):
    payload = _catalogue(await tab_server.read_resource("tab://cms/operations"))
    assert payload["dispatcher"] == "tab_cms_call"
    ops = {op["name"]: op for op in payload["operations"]}
    assert {"homepage", "offers", "promotions", "racing"} <= set(ops)
    # each ships the standard CMS query defaults
    assert ops["homepage"]["query_defaults"]["platform"] == "tabcomau"


async def test_unknown_cms_operation_is_recoverable(tab_server):
    with pytest.raises(MCPToolError) as ei:
        await tab_server.call_tool("tab_cms_call", {"operation": "notarealop"})
    assert "tab://cms/operations" in str(ei.value)
    assert "notarealop" in str(ei.value)


# ─── live: api.beta.tab.com.au (sports) ─────────────────────────────────


@pytest.mark.live
async def test_sports_live(tab_server):
    """The sports root is schedule-independent: the catalogue always lists sports."""
    try:
        res = await tab_server.call_tool("tab_sports", {})
    except (MCPToolError, RuntimeError) as e:
        pytest.xfail(f"api.beta.tab.com.au unavailable: {e}")
    data = _payload(res)
    assert "sports" in data and isinstance(data["sports"], list)


@pytest.mark.live
async def test_match_chains_off_competition_live(tab_server):
    """Discovery flow: AFL competition → first match name → full match book. Skips when
    the AFL has no listed matches; xfails on a host reset."""
    try:
        comp = await tab_server.call_tool(
            "tab_competition", {"sport": "AFL Football", "competition": "AFL"}
        )
    except (MCPToolError, RuntimeError) as e:
        pytest.xfail(f"api.beta.tab.com.au unavailable: {e}")
    matches = _payload(comp).get("matches", [])
    if not matches:
        pytest.skip("no AFL matches listed — nothing to price")
    match_name = matches[0]["name"]
    try:
        res = await tab_server.call_tool(
            "tab_match", {"sport": "AFL Football", "competition": "AFL", "match": match_name}
        )
    except (MCPToolError, RuntimeError) as e:
        pytest.xfail(f"api.beta.tab.com.au unavailable: {e}")
    data = _payload(res)
    # the name-based path (spaces in "AFL Football"/match name) resolved + carries markets
    assert "markets" in data


# ─── live: api.beta.tab.com.au (racing) ─────────────────────────────────


@pytest.mark.live
async def test_racing_race_chains_off_meetings_live(tab_server):
    """Pull a valid 'today' meeting date, then meetings → meeting races → one racecard.
    Uses tab_racing_dates so the date is timezone-correct. Skips when no meetings/races;
    xfails on a reset or a race that has dropped out (resulted)."""
    try:
        dates = _payload(await tab_server.call_tool("tab_racing_dates", {}))
    except (MCPToolError, RuntimeError) as e:
        pytest.xfail(f"api.beta.tab.com.au unavailable: {e}")
    date_list = dates.get("dates", [])
    if not date_list:
        pytest.skip("no racing dates returned")
    meeting_date = date_list[0]["meetingDate"]
    try:
        mt = _payload(await tab_server.call_tool("tab_racing_meetings", {"date": meeting_date}))
    except (MCPToolError, RuntimeError) as e:
        pytest.xfail(f"api.beta.tab.com.au unavailable: {e}")
    meetings = mt.get("meetings", [])
    if not meetings:
        pytest.skip("no meetings for the date")
    meet = meetings[0]
    race_type, venue = meet["raceType"], meet["venueMnemonic"]
    try:
        mr = _payload(
            await tab_server.call_tool(
                "tab_racing_meeting_races",
                {"date": meeting_date, "raceType": race_type, "venueMnemonic": venue},
            )
        )
    except (MCPToolError, RuntimeError) as e:
        pytest.xfail(f"api.beta.tab.com.au unavailable: {e}")
    races = mr.get("races", [])
    if not races:
        pytest.skip("meeting has no races listed")
    race_number = races[-1]["raceNumber"]  # a later race is likelier still open
    try:
        rc = _payload(
            await tab_server.call_tool(
                "tab_racing_race",
                {"date": meeting_date, "raceType": race_type, "venueMnemonic": venue, "raceNumber": race_number},
            )
        )
    except (MCPToolError, RuntimeError) as e:
        pytest.xfail(f"racecard unavailable for {venue} R{race_number}: {e}")
    assert str(rc.get("raceNumber")) == str(race_number)
    assert "runners" in rc


@pytest.mark.live
async def test_racing_next_to_go_live(tab_server):
    """Next-to-go is schedule-independent (there is always a next race somewhere)."""
    try:
        res = await tab_server.call_tool("tab_racing_next_to_go", {})
    except (MCPToolError, RuntimeError) as e:
        pytest.xfail(f"api.beta.tab.com.au unavailable: {e}")
    data = _payload(res)
    assert "races" in data and isinstance(data["races"], list)


# ─── live: cmsapi.tab.com.au (content dispatcher) ───────────────────────


@pytest.mark.live
async def test_cms_call_homepage_live(tab_server):
    """The CMS homepage feed is a stable content envelope."""
    try:
        res = await tab_server.call_tool("tab_cms_call", {"operation": "homepage"})
    except (MCPToolError, RuntimeError) as e:
        pytest.xfail(f"cmsapi.tab.com.au unavailable: {e}")
    data = _payload(res)
    assert isinstance(data, dict)
    assert "items" in data
