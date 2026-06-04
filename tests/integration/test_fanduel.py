"""FanDuel Racing — catalogue/registration checks (offline) + live GraphQL probes.

FanDuel Racing (TVG) is a full-query GraphQL API at api.racing.fanduel.com (the
`graphql_query` dispatcher kind). The offline tests check registration + the
operation catalogue + the unknown-op error path. The ``live`` tests POST real
queries (US racing data); they ``xfail`` if the host is unreachable and assert on
stable structure only. Run them with::

    pytest -m live tests/integration/test_fanduel.py
"""

from __future__ import annotations

import json

import pytest
from fastmcp.exceptions import ToolError as MCPToolError

from sportsdata_mcp.config import Config
from sportsdata_mcp.server import build_server

FANDUEL_GROUPS = ["fanduel.racing", "fanduel.sportsbook"]


@pytest.fixture
async def fanduel_server():
    mcp, reg = build_server(Config(enabled_groups=FANDUEL_GROUPS))
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


# ─── offline: registration + catalogue + error paths ───────────────────


async def test_fanduel_tools_registered(fanduel_server):
    names = {t.name for t in await fanduel_server.list_tools()}
    assert "fanduel_racing_call" in names
    assert {"fanduel_racing_messages", "fanduel_racing_quicklinks", "fanduel_racing_promotions"} <= names
    # sportsbook half
    assert {"fanduel_sb_call", "fanduel_sb_live_score"} <= names


async def test_sportsbook_catalogue_lists_operations(fanduel_server):
    payload = _catalogue(await fanduel_server.read_resource("fanduel://sportsbook/operations"))
    assert payload["dispatcher"] == "fanduel_sb_call"
    ops = {op["name"]: op for op in payload["operations"]}
    assert {"application_context", "event_page", "inplay_counter", "promotions"} <= set(ops)
    # the static public _ak key is carried as an op default, not asked of the model
    assert ops["event_page"]["query_defaults"]["_ak"]


async def test_racing_catalogue_lists_operations(fanduel_server):
    payload = _catalogue(await fanduel_server.read_resource("fanduel://racing/operations"))
    assert payload["dispatcher"] == "fanduel_racing_call"
    names = {op["name"] for op in payload["operations"]}
    assert {"getRaceDate", "getTracks", "getTodayRaces", "getFeaturedRaces", "getTopPools", "getRace"} <= names
    # full-query provider: the note advertises query text (not hashes) server-side
    assert "query" in payload["note"].lower()


async def test_unknown_operation_is_recoverable(fanduel_server):
    with pytest.raises(MCPToolError) as ei:
        await fanduel_server.call_tool("fanduel_racing_call", {"operation": "notARealOp"})
    assert "fanduel://racing/operations" in str(ei.value)
    assert "notARealOp" in str(ei.value)


# ─── live: api.racing.fanduel.com (full-query GraphQL) ──────────────────


@pytest.mark.live
async def test_race_date_live(fanduel_server):
    """getRaceDate takes no variables — the simplest liveness probe."""
    try:
        res = await fanduel_server.call_tool("fanduel_racing_call", {"operation": "getRaceDate"})
    except (MCPToolError, RuntimeError) as e:
        pytest.xfail(f"api.racing.fanduel.com unavailable: {e}")
    data = _payload(res)
    assert "data" in data and "raceDate" in data["data"]
    assert not data.get("errors")


@pytest.mark.live
async def test_tracks_live(fanduel_server):
    """getTracks runs entirely off baked default_variables (brand/product/profile)."""
    try:
        res = await fanduel_server.call_tool("fanduel_racing_call", {"operation": "getTracks"})
    except (MCPToolError, RuntimeError) as e:
        pytest.xfail(f"api.racing.fanduel.com unavailable: {e}")
    data = _payload(res)
    assert not data.get("errors"), data.get("errors")
    assert isinstance(data["data"]["tracks"], list)


@pytest.mark.live
async def test_featured_races_carry_odds_live(fanduel_server):
    """The featured-races op is the race-card surface: each race carries bettingInterests
    with currentOdds. Caller overrides only `results`; the rest defaults."""
    try:
        res = await fanduel_server.call_tool(
            "fanduel_racing_call", {"operation": "getFeaturedRaces", "variables": {"results": 3}}
        )
    except (MCPToolError, RuntimeError) as e:
        pytest.xfail(f"api.racing.fanduel.com unavailable: {e}")
    data = _payload(res)
    assert not data.get("errors"), data.get("errors")
    races = data["data"]["races"]
    if not races:
        pytest.skip("no featured races open right now")
    assert "bettingInterests" in races[0]


@pytest.mark.live
async def test_get_race_chains_off_today_live(fanduel_server):
    """The single-race card: pull an open race (trackCode + number) from getTodayRaces,
    then fetch its full card with bettingInterests via getRace. Skips on no open races."""
    try:
        today = await fanduel_server.call_tool(
            "fanduel_racing_call",
            {"operation": "getTodayRaces", "variables": {"filterBy": {"status": ["O"], "allRaceClasses": True}}},
        )
    except (MCPToolError, RuntimeError) as e:
        pytest.xfail(f"api.racing.fanduel.com unavailable: {e}")
    races = _payload(today).get("data", {}).get("races", [])
    if not races:
        pytest.skip("no open races right now")
    track_code = races[0]["track"]["code"]
    race_number = str(races[0]["number"])
    try:
        res = await fanduel_server.call_tool(
            "fanduel_racing_call",
            {"operation": "getRace", "variables": {"trackCode": track_code, "raceNumber": race_number}},
        )
    except (MCPToolError, RuntimeError) as e:
        pytest.xfail(f"getRace unavailable for {track_code} R{race_number}: {e}")
    data = _payload(res)
    assert not data.get("errors"), data.get("errors")
    race = data["data"]["race"]
    assert race and "bettingInterests" in race


@pytest.mark.live
async def test_racing_promotions_live(fanduel_server):
    """The racing promotions POST returns a structured-placements envelope."""
    try:
        res = await fanduel_server.call_tool("fanduel_racing_promotions", {})
    except (MCPToolError, RuntimeError) as e:
        pytest.xfail(f"promos-api.racing.fanduel.com unavailable: {e}")
    data = _payload(res)
    assert "promoPlacements" in data


@pytest.mark.live
async def test_racing_messages_live(fanduel_server):
    """The REST messages endpoint returns a namespace map (schedule-independent)."""
    try:
        res = await fanduel_server.call_tool("fanduel_racing_messages", {})
    except (MCPToolError, RuntimeError) as e:
        pytest.xfail(f"service.racing.fanduel.com unavailable: {e}")
    data = _payload(res)
    assert "response" in data


# ─── live: api.sportsbook.fanduel.com (REST, _ak + region headers) ──────


@pytest.mark.live
async def test_sb_application_context_live(fanduel_server):
    """The sportsbook dispatcher carries the _ak key + sportsbook Origin/region headers
    (overriding the provider's racing origin). EVENT_TYPES is schedule-independent."""
    try:
        res = await fanduel_server.call_tool(
            "fanduel_sb_call", {"operation": "application_context", "query_params": {"dataEntries": "EVENT_TYPES"}}
        )
    except (MCPToolError, RuntimeError) as e:
        pytest.xfail(f"api.sportsbook.fanduel.com unavailable: {e}")
    data = _payload(res)
    assert "EVENT_TYPES" in data


@pytest.mark.live
async def test_sb_inplay_counter_live(fanduel_server):
    """The in-play counter is always present (count may be zero off-peak)."""
    try:
        res = await fanduel_server.call_tool(
            "fanduel_sb_call", {"operation": "inplay_counter", "query_params": {"includeTabs": "false"}}
        )
    except (MCPToolError, RuntimeError) as e:
        pytest.xfail(f"api.sportsbook.fanduel.com unavailable: {e}")
    data = _payload(res)
    assert "counter" in data


@pytest.mark.live
async def test_sb_event_page_chains_off_content_live(fanduel_server):
    """Discovery flow: a managed sport page → an eventId → the full event page markets.
    Skips when the sport has no listed events; xfails if the host is unreachable."""
    try:
        page = await fanduel_server.call_tool(
            "fanduel_sb_call", {"operation": "content_page", "query_params": {"customPageId": "mlb"}}
        )
    except (MCPToolError, RuntimeError) as e:
        pytest.xfail(f"api.sportsbook.fanduel.com unavailable: {e}")
    events = _payload(page).get("attachments", {}).get("events", {})
    if not events:
        pytest.skip("no MLB events listed right now")
    event_id = next(iter(events))
    try:
        res = await fanduel_server.call_tool(
            "fanduel_sb_call", {"operation": "event_page", "query_params": {"eventId": event_id}}
        )
    except (MCPToolError, RuntimeError) as e:
        pytest.xfail(f"event-page unavailable for {event_id}: {e}")
    data = _payload(res)
    assert "layout" in data and "attachments" in data
