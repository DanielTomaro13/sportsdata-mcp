"""Football-Data.co.uk — registration (offline) + live probes.

The catalogue's only CSV provider, and its only source of HISTORICAL CLOSING ODDS —
the baseline a CLV workflow measures live prices against.

Run the live tests with::

    pytest -m live tests/integration/test_footballdatauk.py
"""

from __future__ import annotations

import json

import pytest
from fastmcp.exceptions import ToolError as MCPToolError

from sportsdata_mcp.config import Config
from sportsdata_mcp.server import build_server

SEASON = "2425"  # 2024/25 — complete, so the shape is frozen
DIVISION = "E0"


@pytest.fixture
async def fd_server():
    mcp, reg = build_server(Config(enabled_groups=["footballdatauk.history"]))
    try:
        yield mcp
    finally:
        await reg.aclose()


def _payload(result):
    if result.structured_content is not None:
        d = result.structured_content
        return d["result"] if set(d) == {"result"} else d
    return json.loads(result.content[0].text) if result.content else []


async def test_tool_registered(fd_server):
    names = {t.name for t in await fd_server.list_tools()}
    assert "footballdatauk_season" in names


@pytest.mark.live
async def test_season_parses_to_rows_live(fd_server):
    try:
        rows = _payload(await fd_server.call_tool(
            "footballdatauk_season", {"season": SEASON, "division": DIVISION}))
    except (MCPToolError, RuntimeError) as e:
        pytest.xfail(f"football-data.co.uk unavailable: {e}")
    assert len(rows) == 380, "a 20-team league season is 380 matches"
    r = rows[0]
    assert {"Div", "Date", "HomeTeam", "AwayTeam", "FTHG", "FTAG", "FTR"} <= set(r)
    assert r["FTR"] in {"H", "D", "A"}
    # The BOM must not have leaked into the first column name.
    assert next(iter(r)) == "Div"


@pytest.mark.live
async def test_closing_odds_are_present_live(fd_server):
    """Closing prices are the entire point of this provider — a `C` in the column name
    marks them, and they're the standard CLV benchmark. If they vanished, the provider
    would be just another results feed."""
    try:
        rows = _payload(await fd_server.call_tool(
            "footballdatauk_season", {"season": SEASON, "division": DIVISION}))
    except (MCPToolError, RuntimeError) as e:
        pytest.xfail(f"football-data.co.uk unavailable: {e}")
    r = rows[0]
    assert {"B365H", "B365D", "B365A"} <= set(r), "opening prices missing"
    closing = [k for k in r if k.startswith(("B365C", "PSC", "MaxC", "AvgC"))]
    assert closing, "no closing-odds columns — the CLV baseline is gone"
    # Values are strings; they must still be numeric-looking.
    assert float(r["B365H"]) > 1.0


@pytest.mark.live
async def test_values_are_strings_live(fd_server):
    """Everything arrives as a string because it's CSV — pinned so nobody assumes ints
    and silently mis-sorts."""
    try:
        rows = _payload(await fd_server.call_tool(
            "footballdatauk_season", {"season": SEASON, "division": DIVISION}))
    except (MCPToolError, RuntimeError) as e:
        pytest.xfail(f"football-data.co.uk unavailable: {e}")
    assert isinstance(rows[0]["FTHG"], str)
    assert "/" in rows[0]["Date"], "dates are DD/MM/YYYY strings"





@pytest.mark.live
async def test_unknown_division_is_a_clean_404_live(fd_server):
    """An unknown DIVISION 404s. Note there is no equivalently-invalid season: codes are
    two-digit year pairs, so '9999' is a real (1998/99) file rather than an error — I
    assumed otherwise first, and this is what corrected it."""
    with pytest.raises((MCPToolError, RuntimeError)):
        await fd_server.call_tool("footballdatauk_season", {"season": SEASON, "division": "ZZ"})


@pytest.mark.live
async def test_old_season_codes_are_valid_not_errors_live(fd_server):
    """'9999' looks like a sentinel but is a legitimate historical file. A caller who
    treats odd-looking codes as invalid would silently skip decades of data — which is
    the whole reason this provider exists."""
    try:
        rows = _payload(await fd_server.call_tool(
            "footballdatauk_season", {"season": "9999", "division": "E0"}))
    except (MCPToolError, RuntimeError) as e:
        pytest.xfail(f"football-data.co.uk unavailable: {e}")
    assert rows, "an old season code should return real data"
    assert rows[0]["Div"] == "E0"
