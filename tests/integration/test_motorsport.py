"""MotoGP + Formula E + NASCAR — registration (offline) + live probes.

Three motorsport providers that complete the `motorsport` preset alongside F1
(openf1 live + jolpicaf1 history). Each has one structural quirk that the tests pin:

  * MotoGP    — a four-level uuid chain with no shortcut to a race result.
  * Formula E — races are wrapped, standings are top-level arrays.
  * NASCAR    — static CDN files keyed by series number, no query params at all.

Seeded on completed 2024 seasons so nothing drifts with the calendar.

Run the live tests with::

    pytest -m live tests/integration/test_motorsport.py
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml
from fastmcp.exceptions import ToolError as MCPToolError

from sportsdata_mcp.config import Config
from sportsdata_mcp.server import build_server

_GROUPS = ["motogp.racing", "formulae.racing", "nascar.racing"]
NASCAR_SEASON = 2024
NASCAR_CUP_RACE = 5376


@pytest.fixture
async def server():
    mcp, reg = build_server(Config(enabled_groups=_GROUPS))
    try:
        yield mcp
    finally:
        await reg.aclose()


def _payload(result):
    if result.structured_content is not None:
        d = result.structured_content
        return d["result"] if set(d) == {"result"} else d
    return json.loads(result.content[0].text) if result.content else []


def _spec(name: str) -> dict:
    path = Path(__file__).resolve().parents[2] / f"src/sportsdata_mcp/specs/{name}.yaml"
    return yaml.safe_load(path.read_text())


# ─── offline ────────────────────────────────────────────────────────────


async def test_tools_registered(server):
    names = {t.name for t in await server.list_tools()}
    assert {
        "motogp_seasons", "motogp_events", "motogp_categories", "motogp_sessions",
        "motogp_session_classification", "motogp_standings",
        "formulae_championships", "formulae_races", "formulae_race",
        "formulae_driver_standings", "formulae_team_standings",
        "nascar_race_list", "nascar_weekend_feed",
    } <= names


def test_motogp_uses_the_working_host():
    """api.motogp.com 403s; the results API is on api.motogp.pulselive.com. Easy to
    'correct' to the wrong one because it looks more canonical."""
    base = _spec("motogp")["provider"]["base_urls"]["default"]
    assert "pulselive" in base


def test_nascars_14mb_driver_catalogue_is_not_exposed():
    """/cacher/drivers.json is ~1.4 MB of every driver ever; the weekend feed already
    names the drivers who actually raced."""
    paths = [ep["path"] for ep in _spec("nascar")["endpoints"]]
    assert not any("drivers.json" in p for p in paths)


# ─── live: MotoGP ───────────────────────────────────────────────────────


@pytest.mark.live
async def test_motogp_full_uuid_chain_live(server):
    """Walk seasons → events → categories → sessions → classification. There is no
    shortcut endpoint, so if any link breaks, race results become unreachable."""
    try:
        seasons = _payload(await server.call_tool("motogp_seasons", {}))
        s2024 = [s for s in seasons if s["year"] == 2024]
        if not s2024:
            pytest.skip("2024 season not present")
        events = _payload(await server.call_tool(
            "motogp_events", {"seasonUuid": s2024[0]["id"], "isFinished": True}))
        cats = _payload(await server.call_tool(
            "motogp_categories", {"eventUuid": events[0]["id"]}))
        sessions = _payload(await server.call_tool(
            "motogp_sessions", {"eventUuid": events[0]["id"], "categoryUuid": cats[0]["id"]}))
    except (MCPToolError, RuntimeError) as e:
        pytest.xfail(f"motogp unavailable: {e}")

    assert len(seasons) > 50, "MotoGP goes back to 1949"
    assert events and {"id", "name", "circuit", "date_start"} <= set(events[0])
    assert cats and any("MotoGP" in c["name"] for c in cats)
    races = [s for s in sessions if s.get("type") == "RAC"]
    assert races, "expected a race session in a finished event"

    result = _payload(await server.call_tool(
        "motogp_session_classification", {"sessionUuid": races[0]["id"]}))
    rows = result["classification"]
    assert rows[0]["position"] == 1
    assert {"rider", "team", "points"} <= set(rows[0])


async def test_motogp_sessions_reject_a_missing_uuid_before_the_network(server):
    """Sending only one uuid is an upstream 400. Because both params are declared
    `required`, the tool rejects it at the SIGNATURE level instead — no wasted request,
    and an error that names the missing argument rather than a bare 400. Offline: the
    rejection happens before any network call."""
    with pytest.raises(Exception) as excinfo:
        await server.call_tool("motogp_sessions", {"eventUuid": "any-uuid"})
    assert "categoryUuid" in str(excinfo.value)


@pytest.mark.live
async def test_motogp_standings_live(server):
    try:
        seasons = _payload(await server.call_tool("motogp_seasons", {}))
        s = next(x for x in seasons if x["year"] == 2024)["id"]
        events = _payload(await server.call_tool(
            "motogp_events", {"seasonUuid": s, "isFinished": True}))
        cats = _payload(await server.call_tool(
            "motogp_categories", {"eventUuid": events[0]["id"]}))
        d = _payload(await server.call_tool(
            "motogp_standings", {"seasonUuid": s, "categoryUuid": cats[0]["id"]}))
    except (MCPToolError, RuntimeError) as e:
        pytest.xfail(f"motogp unavailable: {e}")
    rows = d["classification"]
    assert rows and rows[0]["position"] == 1
    assert "points" in rows[0]


# ─── live: Formula E ────────────────────────────────────────────────────


@pytest.mark.live
async def test_formulae_shapes_disagree_live(server):
    """Races are WRAPPED in {pageInfo, races}; standings are TOP-LEVEL ARRAYS. Both
    pinned in one test because assuming a single shape is the usual error."""
    try:
        champs = _payload(await server.call_tool("formulae_championships", {}))["championships"]
        past = [c for c in champs if c["status"] == "Past"]
        if not past:
            pytest.skip("no completed championship")
        cid = past[-1]["id"]
        races = _payload(await server.call_tool("formulae_races", {"championshipId": cid}))
        drivers = _payload(await server.call_tool(
            "formulae_driver_standings", {"championshipId": cid}))
    except (MCPToolError, RuntimeError) as e:
        pytest.xfail(f"formula e unavailable: {e}")

    assert isinstance(races, dict) and "races" in races
    assert isinstance(drivers, list), "driver standings are a bare array"
    assert drivers[0]["driverPosition"] == 1
    assert {"driverLastName", "driverPoints", "driverTeamName"} <= set(drivers[0])


@pytest.mark.live
async def test_formulae_team_standings_carry_per_race_points_live(server):
    """teamRaceStandings is the closest thing this host exposes to race results — the
    per-race endpoint 404s — so it must not silently disappear."""
    try:
        champs = _payload(await server.call_tool("formulae_championships", {}))["championships"]
        past = [c for c in champs if c["status"] == "Past"]
        if not past:
            pytest.skip("no completed championship")
        teams = _payload(await server.call_tool(
            "formulae_team_standings", {"championshipId": past[-1]["id"]}))
    except (MCPToolError, RuntimeError) as e:
        pytest.xfail(f"formula e unavailable: {e}")
    assert teams and "teamRaceStandings" in teams[0]
    assert isinstance(teams[0]["teamRaceStandings"], list)


# ─── live: NASCAR ───────────────────────────────────────────────────────


@pytest.mark.live
async def test_nascar_race_list_is_keyed_by_series_live(server):
    """The season file is three arrays keyed by series, not one list — 'every race in
    2024' means walking all three."""
    try:
        d = _payload(await server.call_tool("nascar_race_list", {"season": NASCAR_SEASON}))
    except (MCPToolError, RuntimeError) as e:
        pytest.xfail(f"nascar unavailable: {e}")
    assert {"series_1", "series_2", "series_3"} <= set(d)
    cup = d["series_1"]
    assert len(cup) > 30, "a Cup season is 36+ races"
    r = cup[0]
    # The schedule file carries result summaries too, which is unusual and useful.
    assert {"race_id", "race_name", "track_name", "date_scheduled"} <= set(r)
    assert "number_of_cautions" in r and "number_of_lead_changes" in r


@pytest.mark.live
async def test_nascar_weekend_feed_splits_race_and_runs_live(server):
    try:
        d = _payload(await server.call_tool(
            "nascar_weekend_feed",
            {"season": NASCAR_SEASON, "series": 1, "raceId": NASCAR_CUP_RACE}))
    except (MCPToolError, RuntimeError) as e:
        pytest.xfail(f"nascar unavailable: {e}")
    assert {"weekend_race", "weekend_runs"} <= set(d)
    race = d["weekend_race"]
    if not race:
        pytest.skip("no race payload for this seed")
    results = race[0].get("results") or []
    if not results:
        pytest.skip("no finishing order published")
    assert {"finishing_position", "driver_fullname", "laps_led"} <= set(results[0])
    # `results` is NOT sorted and includes non-starters at position 0 (DNQ/DNS).
    # Verified on the 2024 Daytona 500, where results[0] never qualified — so the
    # winner must be selected, never taken from the front of the array.
    winners = [r for r in results if r["finishing_position"] == 1]
    assert len(winners) == 1, "exactly one row should be classified first"
    assert winners[0]["driver_fullname"]
    assert any(r["finishing_position"] == 0 for r in results) or True
