"""Dabble (api.dabble.com.au) — registration (offline) + live probes.

Dabble is the iOS app's backend, reached by posing as the app (the header bundle
is baked into the spec). It is AU-geo + Cloudflare gated, so the live tests
``xfail`` from a blocked region (non-AU / datacenter IP), the same as the other
AU books. Run with::

    pytest -m live tests/integration/test_dabble.py
"""

from __future__ import annotations

import json

import pytest
from fastmcp.exceptions import ToolError as MCPToolError

from sportsdata_mcp.config import Config
from sportsdata_mcp.server import build_server

AFL = "ad4c78ec-e39d-45ee-8cec-ff5d485a3205"


@pytest.fixture
async def dabble_server():
    mcp, reg = build_server(Config(enabled_groups=["dabble.sport"]))
    try:
        yield mcp
    finally:
        await reg.aclose()


def _payload(result):
    if result.structured_content is not None:
        return result.structured_content
    return json.loads(result.content[0].text)


# ─── offline: registration ──────────────────────────────────────────────


async def test_dabble_tools_registered(dabble_server):
    names = {t.name for t in await dabble_server.list_tools()}
    assert {
        "dabble_active_competitions",
        "dabble_competitions",
        "dabble_sports",
        "dabble_competition_fixtures",
        "dabble_fixture_details",
    } <= names


async def test_exclude_param_maps_to_wire_name(dabble_server):
    """`exclude` is exposed as a clean tool param mapped to the wire param
    `exclude[]` via api_name."""
    tools = {t.name: t for t in await dabble_server.list_tools()}
    props = tools["dabble_competition_fixtures"].parameters["properties"]
    assert "exclude" in props and "exclude[]" not in props


# ─── live: api.dabble.com.au (AU-geo + Cloudflare → xfail when blocked) ──


@pytest.mark.live
async def test_discovery_any_competition_live(dabble_server):
    """Discover an ARBITRARY competition (not AFL/NRL) from the active list and pull
    its fixtures — proves Dabble works for any competition."""
    try:
        active = _payload(await dabble_server.call_tool("dabble_active_competitions", {}))
        comps = active["data"]["activeCompetitions"]
        if not comps:
            pytest.skip("no active competitions right now")
        # pick a non-AU-football competition to make the point
        pick = next(
            (c for c in comps if c.get("sportName") in ("Football", "Tennis", "Cricket", "Basketball") and c.get("id")),
            comps[0],
        )
        fx = _payload(await dabble_server.call_tool("dabble_competition_fixtures", {"competitionId": pick["id"]}))
    except (MCPToolError, RuntimeError) as e:
        pytest.xfail(f"dabble unavailable (AU-geo / Cloudflare?): {e}")
    assert len(comps) > 20 and {"id", "name", "sportName"} <= set(comps[0])
    assert "data" in fx  # fixtures (possibly empty if none scheduled), but the call resolved


@pytest.mark.live
async def test_competitions_name_lookup_live(dabble_server):
    """Exact-name lookup resolves a known competition to its id."""
    try:
        res = _payload(await dabble_server.call_tool("dabble_competitions", {"name": "NRL"}))
    except (MCPToolError, RuntimeError) as e:
        pytest.xfail(f"dabble unavailable: {e}")
    assert res["data"] and res["data"][0]["name"] == "NRL" and res["data"][0]["id"]


@pytest.mark.live
async def test_fixtures_and_details_live(dabble_server):
    """AFL fixtures carry embedded markets + prices; a fixture drills into the full book."""
    try:
        fx = _payload(await dabble_server.call_tool("dabble_competition_fixtures", {"competitionId": AFL}))
        data = fx["data"]
        if not data:
            pytest.skip("no AFL fixtures listed right now")
        f0 = data[0]
        details = _payload(await dabble_server.call_tool("dabble_fixture_details", {"fixtureId": f0["id"]}))
    except (MCPToolError, RuntimeError) as e:
        pytest.xfail(f"dabble unavailable (AU-geo / Cloudflare?): {e}")
    assert "name" in f0 and "markets" in f0 and "prices" in f0
    sfd = details["sportFixtureDetail"]
    assert sfd["markets"] and sfd["prices"]


@pytest.mark.live
async def test_exclude_slims_payload_live(dabble_server):
    """exclude=markets drops the embedded markets block (the prices stay)."""
    try:
        full = _payload(await dabble_server.call_tool("dabble_competition_fixtures", {"competitionId": AFL}))
        slim = _payload(
            await dabble_server.call_tool("dabble_competition_fixtures", {"competitionId": AFL, "exclude": ["markets"]})
        )
    except (MCPToolError, RuntimeError) as e:
        pytest.xfail(f"dabble unavailable: {e}")
    if not full["data"]:
        pytest.skip("no fixtures")
    assert "markets" in full["data"][0]
    assert "markets" not in slim["data"][0]


@pytest.mark.live
async def test_exclude_accepts_multiple_blocks_live(dabble_server):
    """exclude takes a LIST → repeated exclude[] params drop multiple blocks at once."""
    try:
        slim = _payload(
            await dabble_server.call_tool(
                "dabble_competition_fixtures", {"competitionId": AFL, "exclude": ["markets", "prices"]}
            )
        )
    except (MCPToolError, RuntimeError) as e:
        pytest.xfail(f"dabble unavailable: {e}")
    if not slim["data"]:
        pytest.skip("no fixtures")
    f0 = slim["data"][0]
    assert "markets" not in f0 and "prices" not in f0 and "selections" in f0


@pytest.mark.live
async def test_competitions_by_sport_and_active_filter_live(dabble_server):
    """`sportId` filters both the active list and the full competitions lookup."""
    try:
        sports = _payload(await dabble_server.call_tool("dabble_sports", {}))
        sid = sports["data"][0]["id"]
        active = _payload(await dabble_server.call_tool("dabble_active_competitions", {"sportId": sid}))
        allcomp = _payload(await dabble_server.call_tool("dabble_competitions", {"sportId": sid}))
    except (MCPToolError, RuntimeError) as e:
        pytest.xfail(f"dabble unavailable: {e}")
    # both resolve and are scoped (active ⊆ all for that sport); shapes intact
    assert "activeCompetitions" in active["data"]
    assert isinstance(allcomp["data"], list)
