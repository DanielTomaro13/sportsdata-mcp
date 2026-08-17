"""FPL — registration (offline) + live probes.

The provider exists in the shape it does because of one measurement: `bootstrap-static`
is a single 1.37 MB blob whose player rows alone are ~362,000 tokens. The projection
tools are the only reason the flagship endpoint is usable, so most of what is worth
testing here is that the slicing keeps working and keeps being small.
"""

from __future__ import annotations

import json

import pytest

from sportsdata_mcp.config import Config
from sportsdata_mcp.server import build_server
from sportsdata_mcp.spec_loader import load_all_specs


@pytest.fixture
async def server():
    mcp, reg = build_server(Config(enabled_groups=["fpl.*"]))
    try:
        yield mcp
    finally:
        await reg.aclose()


def _payload(result):
    return json.loads(result.content[0].text)


# ─── offline ────────────────────────────────────────────────────────────


async def test_all_tools_register(server):
    names = {t.name for t in await server.list_tools()}
    assert {
        "fpl_players", "fpl_player_detail", "fpl_teams", "fpl_gameweeks", "fpl_game_rules",
        "fpl_fixtures", "fpl_live_gameweek", "fpl_dream_team", "fpl_event_status",
        "fpl_set_piece_notes", "fpl_manager", "fpl_manager_history", "fpl_manager_picks",
        "fpl_classic_league", "fpl_h2h_league", "fpl_my_team",
    } <= names


def test_only_your_own_squad_and_writes_need_the_session_cookie():
    """Every READ except your own squad must work with nothing configured — that is the
    whole appeal of this provider. The writes need it by definition."""
    spec = next(s for s in load_all_specs() if s.provider.id == "fpl")
    authed = {e.name for e in spec.endpoints if e.auth == "session"}
    assert authed == {"fpl_my_team", "fpl_set_lineup", "fpl_transfers"}
    # And every one of those is either your own squad or a write — never a public read.
    writes = {e.name for e in spec.endpoints if e.group.endswith(".write")}
    assert authed - writes == {"fpl_my_team"}
    assert spec.provider.requires_user_key is False


# ─── live ───────────────────────────────────────────────────────────────


@pytest.mark.live
async def test_players_are_sliced_down_to_a_usable_size(server):
    """The measurement the provider is built around. Unprojected this is ~362k tokens;
    if a future field set creeps back up, this fails rather than a user's conversation."""
    raw = (await server.call_tool("fpl_players", {})).content[0].text
    body = json.loads(raw)
    assert set(body) == {"elements"}, "pick leaked other sections"
    assert len(body["elements"]) > 400, "player list looks truncated"
    assert len(raw) < 400_000, f"{len(raw):,} bytes — too big for a context window"
    row = body["elements"][0]
    assert set(row) <= {
        "id", "web_name", "team", "element_type", "now_cost", "total_points",
        "points_per_game", "form", "selected_by_percent", "status", "news",
        "chance_of_playing_next_round", "minutes", "goals_scored", "assists",
        "clean_sheets", "bonus", "expected_goals", "expected_assists",
        "defensive_contribution", "ict_index", "ep_next",
    }, f"unexpected field survived projection: {set(row)}"


@pytest.mark.live
async def test_each_reference_slice_returns_only_its_own_section(server):
    for tool, key in [("fpl_teams", "teams"), ("fpl_gameweeks", "events")]:
        body = _payload(await server.call_tool(tool, {}))
        assert set(body) == {key}, f"{tool} returned {set(body)}"
        assert body[key]
    rules = _payload(await server.call_tool("fpl_game_rules", {}))
    assert {"element_types", "chips"} <= set(rules)
    # 1 GK, 2 DEF, 3 MID, 4 FWD — the ids every player row refers to.
    assert len(rules["element_types"]) == 4


@pytest.mark.live
async def test_gameweeks_carry_the_deadline_an_agent_needs(server):
    """Deadlines are the load-bearing field for anything automated: transfers and lineup
    changes lock at them."""
    events = _payload(await server.call_tool("fpl_gameweeks", {}))["events"]
    assert len(events) == 38
    assert all("deadline_time" in e for e in events)
    assert sum(1 for e in events if e.get("is_current")) <= 1


@pytest.mark.live
async def test_a_player_detail_carries_history_and_fixture_difficulty(server):
    body = _payload(await server.call_tool("fpl_player_detail", {"playerId": 1}))
    assert {"fixtures", "history", "history_past"} <= set(body)
    if body["fixtures"]:
        assert 1 <= body["fixtures"][0]["difficulty"] <= 5


@pytest.mark.live
async def test_fixtures_and_teams_agree_on_ids(server):
    """FPL's team ids are its own 1-20, and fixtures reference them. A mismatch here
    would mean every fixture lookup silently names the wrong club."""
    teams = {t["id"] for t in _payload(await server.call_tool("fpl_teams", {}))["teams"]}
    assert teams == set(range(1, 21))
    fixtures = _payload(await server.call_tool("fpl_fixtures", {"event": 1}))
    for f in fixtures:
        assert f["team_h"] in teams and f["team_a"] in teams


@pytest.mark.live
async def test_my_team_refuses_clearly_without_a_cookie(server, monkeypatch):
    """The error has to name the variable — "403" alone leaves a user nowhere."""
    monkeypatch.delenv("FPL_SESSION_COOKIE", raising=False)
    with pytest.raises(Exception) as e:
        await server.call_tool("fpl_my_team", {"managerId": 1})
    assert "FPL_SESSION_COOKIE" in str(e.value)
