"""Jolpica F1 (api.jolpi.ca) — registration (offline) + live probes.

The Ergast successor: every F1 race since 1950. Seeded on 2024, a completed season,
so the shapes can't drift.

The tests below pin the three things that make this API easy to get wrong: the double
MRData envelope (whose inner table name changes per endpoint), values arriving as
strings, and pagination that truncates silently.

Run the live tests with::

    pytest -m live tests/integration/test_jolpicaf1.py
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml
from fastmcp.exceptions import ToolError as MCPToolError

from sportsdata_mcp.config import Config
from sportsdata_mcp.server import build_server

_GROUPS = ["jolpicaf1.reference", "jolpicaf1.schedule", "jolpicaf1.results", "jolpicaf1.standings"]
SEASON = "2024"


@pytest.fixture
async def f1_server():
    mcp, reg = build_server(Config(enabled_groups=_GROUPS))
    try:
        yield mcp
    finally:
        await reg.aclose()


def _payload(result):
    if result.structured_content is not None:
        return result.structured_content
    return json.loads(result.content[0].text)


def _spec() -> dict:
    path = Path(__file__).resolve().parents[2] / "src/sportsdata_mcp/specs/jolpicaf1.yaml"
    return yaml.safe_load(path.read_text())


# ─── offline ────────────────────────────────────────────────────────────


async def test_tools_registered(f1_server):
    names = {t.name for t in await f1_server.list_tools()}
    assert {
        "jolpicaf1_seasons", "jolpicaf1_drivers", "jolpicaf1_constructors",
        "jolpicaf1_circuits", "jolpicaf1_races", "jolpicaf1_results",
        "jolpicaf1_qualifying", "jolpicaf1_sprint", "jolpicaf1_laps",
        "jolpicaf1_pitstops", "jolpicaf1_driver_standings",
        "jolpicaf1_constructor_standings",
    } <= names


def test_every_tool_defaults_to_json():
    """The API serves XML by default — a tool without format=json returns a document
    this engine cannot decode."""
    missing = []
    for ep in _spec()["endpoints"]:
        fmt = next((p for p in ep.get("params", []) if p["name"] == "format"), None)
        if not fmt or fmt.get("default") != "json":
            missing.append(ep["name"])
    assert not missing, f"these would return XML: {missing}"


# ─── live ───────────────────────────────────────────────────────────────


@pytest.mark.live
async def test_races_envelope_live(f1_server):
    """MRData.RaceTable.Races — the double envelope, pinned because everything else
    depends on reading it correctly."""
    try:
        res = await f1_server.call_tool("jolpicaf1_races", {"season": SEASON})
    except (MCPToolError, RuntimeError) as e:
        pytest.xfail(f"jolpica unavailable: {e}")
    d = _payload(res)
    races = d["MRData"]["RaceTable"]["Races"]
    assert len(races) > 15, "a modern F1 season is 20+ rounds"
    assert {"season", "round", "raceName", "date", "Circuit"} <= set(races[0])


@pytest.mark.live
async def test_results_values_are_strings_live(f1_server):
    """Positions and points are STRINGS. Sorting them lexically puts '10' before '2',
    which is exactly the bug this pins."""
    try:
        res = await f1_server.call_tool("jolpicaf1_results", {"season": SEASON, "round": "1"})
    except (MCPToolError, RuntimeError) as e:
        pytest.xfail(f"jolpica unavailable: {e}")
    results = _payload(res)["MRData"]["RaceTable"]["Races"][0]["Results"]
    assert results
    top = results[0]
    assert top["position"] == "1"
    assert isinstance(top["position"], str) and isinstance(top["points"], str)
    assert {"Driver", "Constructor", "grid", "laps", "status"} <= set(top)


@pytest.mark.live
async def test_standings_have_the_extra_layer_live(f1_server):
    """Standings nest one level deeper than everything else:
    StandingsTable.StandingsLists[0].DriverStandings."""
    try:
        res = await f1_server.call_tool("jolpicaf1_driver_standings", {"season": SEASON})
    except (MCPToolError, RuntimeError) as e:
        pytest.xfail(f"jolpica unavailable: {e}")
    lists = _payload(res)["MRData"]["StandingsTable"]["StandingsLists"]
    assert lists
    standings = lists[0]["DriverStandings"]
    assert standings[0]["position"] == "1"
    assert {"points", "wins", "Driver", "Constructors"} <= set(standings[0])


@pytest.mark.live
async def test_laps_report_total_for_pagination_live(f1_server):
    """A race is thousands of timing rows and the default page is 30, so a caller who
    ignores MRData.total silently gets a fraction of the data."""
    try:
        res = await f1_server.call_tool(
            "jolpicaf1_laps", {"season": SEASON, "round": "1", "limit": 50})
    except (MCPToolError, RuntimeError) as e:
        pytest.xfail(f"jolpica unavailable: {e}")
    mr = _payload(res)["MRData"]
    assert int(mr["total"]) > 50, "expected far more rows than one page"
    assert mr["RaceTable"]["Races"][0]["Laps"]


@pytest.mark.live
async def test_sprint_is_empty_not_an_error_for_a_normal_weekend_live(f1_server):
    """A non-sprint weekend returns Races: [] with HTTP 200. That's data, not failure."""
    try:
        res = await f1_server.call_tool("jolpicaf1_sprint", {"season": SEASON, "round": "1"})
    except (MCPToolError, RuntimeError) as e:
        pytest.xfail(f"jolpica unavailable: {e}")
    races = _payload(res)["MRData"]["RaceTable"]["Races"]
    assert races == [] or "SprintResults" in races[0]


@pytest.mark.live
async def test_current_and_last_aliases_live(f1_server):
    """`current`/`last` avoid a lookup round-trip; if they broke, every 'most recent
    race' question would need two calls."""
    try:
        res = await f1_server.call_tool("jolpicaf1_results", {"season": "current", "round": "last"})
    except (MCPToolError, RuntimeError) as e:
        pytest.xfail(f"jolpica unavailable: {e}")
    races = _payload(res)["MRData"]["RaceTable"]["Races"]
    if not races:
        pytest.skip("no completed race in the current season yet")
    assert races[0]["Results"]


@pytest.mark.live
@pytest.mark.parametrize("tool,table,key", [
    ("jolpicaf1_drivers", "DriverTable", "Drivers"),
    ("jolpicaf1_constructors", "ConstructorTable", "Constructors"),
    ("jolpicaf1_circuits", "CircuitTable", "Circuits"),
])
async def test_reference_tables_live(f1_server, tool, table, key):
    try:
        res = await f1_server.call_tool(tool, {"season": SEASON})
    except (MCPToolError, RuntimeError) as e:
        pytest.xfail(f"jolpica unavailable: {e}")
    rows = _payload(res)["MRData"][table][key]
    assert rows, f"{tool} returned no rows"


@pytest.mark.live
async def test_qualifying_and_pitstops_live(f1_server):
    try:
        q = _payload(await f1_server.call_tool(
            "jolpicaf1_qualifying", {"season": SEASON, "round": "1"}))
        p = _payload(await f1_server.call_tool(
            "jolpicaf1_pitstops", {"season": SEASON, "round": "1"}))
    except (MCPToolError, RuntimeError) as e:
        pytest.xfail(f"jolpica unavailable: {e}")
    quali = q["MRData"]["RaceTable"]["Races"][0]["QualifyingResults"]
    assert "Q1" in quali[0]
    stops = p["MRData"]["RaceTable"]["Races"][0]["PitStops"]
    assert {"driverId", "lap", "duration"} <= set(stops[0])
