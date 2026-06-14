"""LaLiga (laliga.com) — registration (offline) + live probes.

The site's private APIM API ships a public subscription key (overridable via
LALIGA_SUBSCRIPTION_KEY when it rotates), so live tests work out of the box and
``xfail`` if the host is unreachable or the key has rotated (401). Run with::

    pytest -m live tests/integration/test_laliga.py
"""

from __future__ import annotations

import json

import pytest
from fastmcp.exceptions import ToolError as MCPToolError

from sportsdata_mcp.config import Config
from sportsdata_mcp.server import build_server

LALIGA_GROUPS = ["laliga.core", "laliga.teams", "laliga.players", "laliga.matches"]
SUB = "laliga-easports-2025"


@pytest.fixture
async def laliga_server():
    mcp, reg = build_server(Config(enabled_groups=LALIGA_GROUPS))
    try:
        yield mcp
    finally:
        await reg.aclose()


def _payload(result):
    if result.structured_content is not None:
        return result.structured_content
    return json.loads(result.content[0].text)


# ─── offline: registration ──────────────────────────────────────────────


async def test_laliga_tools_registered(laliga_server):
    names = {t.name for t in await laliga_server.list_tools()}
    assert {
        "laliga_competitions",
        "laliga_competition",
        "laliga_subscriptions",
        "laliga_subscription",
        "laliga_standing",
        "laliga_rounds",
    } <= names
    assert {"laliga_teams", "laliga_team", "laliga_squad"} <= names
    assert {"laliga_players_stats", "laliga_player", "laliga_player_stats"} <= names
    assert {"laliga_matches", "laliga_match"} <= names


async def test_public_key_ships_as_default():
    """The provider must construct without LALIGA_SUBSCRIPTION_KEY set — the public
    APIM key is shipped as a literal default (overridable via env when it rotates)."""
    import os

    from sportsdata_mcp.http_client import HTTPClient
    from sportsdata_mcp.spec_loader import load_all_specs

    spec = next(s for s in load_all_specs() if s.provider.id == "laliga")
    saved = os.environ.pop("LALIGA_SUBSCRIPTION_KEY", None)
    try:
        http = HTTPClient(spec.provider, Config())
        name, value = await http.mint_auth("default")
        await http.aclose()
    finally:
        if saved is not None:
            os.environ["LALIGA_SUBSCRIPTION_KEY"] = saved
    assert name == "Ocp-Apim-Subscription-Key" and value  # a non-empty default key


# ─── live: apim.laliga.com ──────────────────────────────────────────────


@pytest.mark.live
async def test_standing_live(laliga_server):
    """The 2025/26 table comes back with 20 ranked team entries."""
    try:
        res = await laliga_server.call_tool("laliga_standing", {"slug": SUB})
    except (MCPToolError, RuntimeError) as e:
        pytest.xfail(f"laliga unavailable (or key rotated): {e}")
    data = _payload(res)
    assert data["standings"] and "points" in data["standings"][0] and "team" in data["standings"][0]


@pytest.mark.live
async def test_team_directory_and_squad_live(laliga_server):
    """The global team directory paginates; a club's squad lists players."""
    try:
        teams = _payload(await laliga_server.call_tool("laliga_teams", {"limit": 10}))
        squad = _payload(await laliga_server.call_tool("laliga_squad", {"slug": "real-madrid", "subscription": SUB}))
    except (MCPToolError, RuntimeError) as e:
        pytest.xfail(f"laliga unavailable: {e}")
    assert teams["teams"] and "slug" in teams["teams"][0] and "name" in teams["teams"][0]
    assert squad["squads"] and "person" in squad["squads"][0]


@pytest.mark.live
async def test_subscription_carries_season_teams_live(laliga_server):
    """laliga_subscription embeds the 20 season teams (the season-scoped source,
    unlike the global laliga_teams directory)."""
    try:
        sub = _payload(await laliga_server.call_tool("laliga_subscription", {"slug": SUB}))
    except (MCPToolError, RuntimeError) as e:
        pytest.xfail(f"laliga unavailable: {e}")
    teams = sub["subscription"].get("teams")
    assert isinstance(teams, list) and len(teams) == 20


@pytest.mark.live
async def test_players_stats_and_profile_live(laliga_server):
    """The season player-stats feed resolves; a player's slug drills into a profile."""
    try:
        ps = _payload(await laliga_server.call_tool("laliga_players_stats", {"slug": SUB, "limit": 5}))
        pslug = ps["player_stats"][0]["slug"]
        prof = _payload(await laliga_server.call_tool("laliga_player", {"slug": pslug}))
    except (MCPToolError, RuntimeError) as e:
        pytest.xfail(f"laliga unavailable: {e}")
    assert ps["player_stats"][0]["stats"]
    assert prof["player"]["slug"] == pslug


@pytest.mark.live
async def test_matches_and_detail_live(laliga_server):
    """A real LALIGA matchweek (competition=primera-division) resolves; a match drills into detail.

    (competition= is the real filter — subscription= alone returns a mixed bag.)"""
    try:
        ms = _payload(
            await laliga_server.call_tool(
                "laliga_matches",
                {"subscription": SUB, "competition": "primera-division", "gameweek": 1, "limit": 10},
            )
        )
        mslug = ms["matches"][0]["slug"]
        detail = _payload(await laliga_server.call_tool("laliga_match", {"slug": mslug}))
    except (MCPToolError, RuntimeError) as e:
        pytest.xfail(f"laliga unavailable: {e}")
    # a real La Liga matchweek is 10 matches, all primera-division
    assert len(ms["matches"]) == 10
    assert all(m["competition"]["slug"] == "primera-division" for m in ms["matches"])
    assert detail["match"]["slug"] == mslug
