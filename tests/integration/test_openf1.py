"""OpenF1 — registration (offline) + live probes against api.openf1.org.

OpenF1 is a free, no-auth Formula 1 data API. The offline test checks tool
registration and runs everywhere; the ``live`` tests hit the public API and
``xfail`` if it is unreachable / rate-limited (and ``skip`` when a sparse feed
returns nothing). Run the live ones with::

    pytest -m live tests/integration/test_openf1.py
"""

from __future__ import annotations

import json

import pytest
from fastmcp.exceptions import ToolError as MCPToolError

from sportsdata_mcp.config import Config
from sportsdata_mcp.server import build_server

OPENF1_GROUPS = [
    "openf1.reference",
    "openf1.results",
    "openf1.timing",
    "openf1.telemetry",
    "openf1.live",
]


@pytest.fixture
async def openf1_server():
    mcp, reg = build_server(Config(enabled_groups=OPENF1_GROUPS))
    try:
        yield mcp
    finally:
        await reg.aclose()


def _payload(result):
    if result.structured_content is not None:
        return result.structured_content
    return json.loads(result.content[0].text) if result.content else None


# ─── offline: registration ──────────────────────────────────────────────


async def test_openf1_tools_registered(openf1_server):
    names = {t.name for t in await openf1_server.list_tools()}
    assert {"openf1_meetings", "openf1_sessions", "openf1_drivers"} <= names
    assert {
        "openf1_session_result",
        "openf1_starting_grid",
        "openf1_championship_drivers",
        "openf1_championship_teams",
        "openf1_overtakes",
    } <= names
    assert {"openf1_laps", "openf1_pit", "openf1_stints", "openf1_intervals", "openf1_position"} <= names
    assert {"openf1_car_data", "openf1_location"} <= names
    assert {"openf1_race_control", "openf1_team_radio", "openf1_weather"} <= names


# ─── live: api.openf1.org ───────────────────────────────────────────────


async def _latest_session_key(server):
    res = await server.call_tool("openf1_sessions", {"session_key": "latest"})
    data = _payload(res)
    assert isinstance(data, list) and data
    return str(data[0]["session_key"])


@pytest.mark.live
async def test_sessions_latest_live(openf1_server):
    """`session_key=latest` resolves the current/most-recent session."""
    try:
        res = await openf1_server.call_tool("openf1_sessions", {"session_key": "latest"})
    except (MCPToolError, RuntimeError) as e:
        pytest.xfail(f"api.openf1.org unavailable: {e}")
    data = _payload(res)
    assert isinstance(data, list) and data
    assert "session_key" in data[0] and "session_name" in data[0]


@pytest.mark.live
async def test_drivers_for_latest_session_live(openf1_server):
    """Driver roster for the latest session (proves ref.players + key plumbing)."""
    try:
        sk = await _latest_session_key(openf1_server)
        res = await openf1_server.call_tool("openf1_drivers", {"session_key": sk})
    except (MCPToolError, RuntimeError) as e:
        pytest.xfail(f"api.openf1.org unavailable: {e}")
    data = _payload(res)
    if not data:
        pytest.skip("no drivers for latest session yet")
    assert "driver_number" in data[0] and "full_name" in data[0]


@pytest.mark.live
async def test_laps_live(openf1_server):
    """Per-lap timing for one driver carries sector + speed-trap detail."""
    try:
        sk = await _latest_session_key(openf1_server)
        res = await openf1_server.call_tool(
            "openf1_laps", {"session_key": sk, "driver_number": 1, "lap_number": 1}
        )
    except (MCPToolError, RuntimeError) as e:
        pytest.xfail(f"api.openf1.org unavailable: {e}")
    data = _payload(res)
    if not data:
        pytest.skip("no lap data for this session/driver")
    assert "lap_number" in data[0] and "duration_sector_1" in data[0]


@pytest.mark.live
async def test_car_data_telemetry_live(openf1_server):
    """Telemetry telemetry feed returns speed/throttle/gear samples for one driver."""
    try:
        sk = await _latest_session_key(openf1_server)
        res = await openf1_server.call_tool(
            "openf1_car_data", {"session_key": sk, "driver_number": 1}
        )
    except (MCPToolError, RuntimeError) as e:
        pytest.xfail(f"api.openf1.org unavailable: {e}")
    data = _payload(res)
    if not data:
        pytest.skip("no telemetry for this session/driver")
    assert "speed" in data[0] and "n_gear" in data[0]


@pytest.mark.live
async def test_championship_standings_live(openf1_server):
    """Drivers' championship standings compose under stats.ladder."""
    try:
        sk = await _latest_session_key(openf1_server)
        res = await openf1_server.call_tool("openf1_championship_drivers", {"session_key": sk})
    except (MCPToolError, RuntimeError) as e:
        pytest.xfail(f"api.openf1.org unavailable: {e}")
    data = _payload(res)
    if not data:
        pytest.skip("no championship standings for this session")
    assert "driver_number" in data[0] and "points_current" in data[0]
