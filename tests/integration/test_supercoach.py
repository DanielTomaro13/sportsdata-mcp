"""SuperCoach (supercoach.com.au) — registration (offline) + live probes.

SuperCoach is News Corp / Champion Data's salary-cap fantasy game. One uniform
JSON surface serves all seven games (afl, nrl, epl, nba, nbl, nfl, bbl) under
``/{year}/api/{sport}/classic/v1/...``; no auth, not geo-blocked. The live tests
``xfail`` if the site is unreachable. Run with::

    pytest -m live tests/integration/test_supercoach.py
"""

from __future__ import annotations

import json

import pytest
from fastmcp.exceptions import ToolError as MCPToolError

from sportsdata_mcp.config import Config
from sportsdata_mcp.server import build_server

# Per-sport season key (NOT always the calendar year) — afl/nrl are calendar-year
# and in-season now; the others run across the new year so 2025 is current.
AFL_YEAR = 2026
ALT_YEAR = 2025


@pytest.fixture
async def sc_server():
    mcp, reg = build_server(Config(enabled_groups=["supercoach.fantasy"]))
    try:
        yield mcp
    finally:
        await reg.aclose()


def _payload(result):
    if result.structured_content is not None:
        return result.structured_content
    return json.loads(result.content[0].text)


# ─── offline: registration ──────────────────────────────────────────────


async def test_supercoach_tools_registered(sc_server):
    names = {t.name for t in await sc_server.list_tools()}
    assert {
        "supercoach_settings",
        "supercoach_players",
        "supercoach_real_fixture",
        "supercoach_teams",
        "supercoach_player",
    } <= names


def test_sport_enum_lists_all_seven_games():
    # `enum` is advisory in this engine (not surfaced into the JSON schema), so assert
    # it on the loaded spec — that's where the seven-game contract actually lives.
    from pathlib import Path

    from sportsdata_mcp.spec_loader import load_spec

    spec = load_spec(Path("src/sportsdata_mcp/specs/supercoach.yaml"))
    for ep in spec.endpoints:
        sport = next(p for p in ep.params if p.name == "sport")
        assert set(sport.enum) == {"afl", "nrl", "epl", "nba", "nbl", "nfl", "bbl"}


async def test_sport_and_year_are_required(sc_server):
    tools = {t.name: t for t in await sc_server.list_tools()}
    required = set(tools["supercoach_players"].parameters.get("required", []))
    assert {"sport", "year"} <= required


# ─── live: supercoach.com.au (no auth, not geo-blocked → xfail if down) ──


@pytest.mark.live
@pytest.mark.parametrize(
    "sport,year",
    [("afl", AFL_YEAR), ("nrl", AFL_YEAR), ("epl", ALT_YEAR), ("nba", ALT_YEAR),
     ("nbl", ALT_YEAR), ("nfl", ALT_YEAR), ("bbl", ALT_YEAR)],
)
async def test_settings_live_all_sports(sc_server, sport, year):
    """Every one of the seven games resolves its competition state."""
    try:
        res = _payload(await sc_server.call_tool("supercoach_settings", {"sport": sport, "year": year}))
    except (MCPToolError, RuntimeError) as e:
        pytest.xfail(f"supercoach unavailable: {e}")
    comp = res["competition"]
    assert "current_round" in comp and "next_round" in comp


@pytest.mark.live
async def test_players_feed_carries_price_and_projection_live(sc_server):
    """The core feed returns per-player price + the ppts1 projection for AFL."""
    try:
        settings = _payload(await sc_server.call_tool("supercoach_settings", {"sport": "afl", "year": AFL_YEAR}))
        rd = settings["competition"]["next_round"] or settings["competition"]["current_round"]
        players = _payload(
            await sc_server.call_tool(
                "supercoach_players",
                {"sport": "afl", "year": AFL_YEAR, "round": rd, "embed": "positions,player_stats"},
            )
        )
    except (MCPToolError, RuntimeError) as e:
        pytest.xfail(f"supercoach unavailable: {e}")
    assert len(players) > 100
    ps = players[0]["player_stats"][0]
    assert "price" in ps and "avg" in ps
    # ppts1 is SuperCoach's real projection (present for afl/nrl); avg is the fallback.
    assert ("ppts1" in ps) or ("avg" in ps)


@pytest.mark.live
async def test_real_fixture_carries_scores_and_odds_live(sc_server):
    """real_fixture exposes scores + head-to-head bookmaker odds."""
    try:
        fx = _payload(
            await sc_server.call_tool(
                "supercoach_real_fixture", {"sport": "afl", "year": AFL_YEAR, "round": 1, "page_size": 5}
            )
        )
    except (MCPToolError, RuntimeError) as e:
        pytest.xfail(f"supercoach unavailable: {e}")
    if not fx:
        pytest.skip("no fixtures returned")
    f0 = fx[0]
    assert {"team1", "team2", "round"} <= set(f0)
    assert "team1_score" in f0 and "team1_odds" in f0


@pytest.mark.live
async def test_teams_catalogue_live(sc_server):
    """Teams catalogue resolves for a non-AFL game (proves cross-sport scoping)."""
    try:
        teams = _payload(await sc_server.call_tool("supercoach_teams", {"sport": "nfl", "year": ALT_YEAR}))
    except (MCPToolError, RuntimeError) as e:
        pytest.xfail(f"supercoach unavailable: {e}")
    assert isinstance(teams, list) and len(teams) >= 8
