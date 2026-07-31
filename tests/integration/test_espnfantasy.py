"""ESPN Fantasy (lm-api-reads.fantasy.espn.com) — registration (offline) + live probes.

ESPN's fantasy-league platform: one URL per league whose payload is selected by a
repeatable ``view`` query param. The offline tests pin the two things that are easy
to break silently and impossible to notice at runtime:

  * ``view`` params MUST be ``string_list`` (repeated ``?view=a&view=b``). A
    comma-joined list is accepted by ESPN with HTTP 200 and returns the bare league
    skeleton — a wrong param type looks exactly like an empty league.
  * league-scoped endpoints use the ``private`` (optional-cookie) auth key, so public
    leagues work anonymously and ``ESPN_FANTASY_COOKIE`` upgrades the same tools.

Live tests run against **public league 1234, season 2018** — a league that is public,
complete and frozen, so its shapes don't drift. They ``xfail`` when ESPN is
unreachable. Run with::

    pytest -m live tests/integration/test_espnfantasy.py
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml
from fastmcp.exceptions import ToolError as MCPToolError

from sportsdata_mcp.config import Config
from sportsdata_mcp.server import build_server

_GROUPS = [
    "espnfantasy.reference",
    "espnfantasy.league",
    "espnfantasy.scoring",
    "espnfantasy.players",
]

# Public, completed, frozen — see module docstring.
LEAGUE_ID = 1234
SEASON = 2018
WEEK = 3


@pytest.fixture
async def espnf_server():
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
    path = Path(__file__).resolve().parents[2] / "src/sportsdata_mcp/specs/espnfantasy.yaml"
    return yaml.safe_load(path.read_text())


def _league_args(**extra):
    return {"game": "ffl", "seasonId": SEASON, "leagueId": LEAGUE_ID, **extra}


# ─── offline: registration + spec invariants ────────────────────────────


async def test_espnfantasy_tools_registered(espnf_server):
    names = {t.name for t in await espnf_server.list_tools()}
    assert {
        "espnfantasy_games",
        "espnfantasy_pro_teams",
        "espnfantasy_league_settings",
        "espnfantasy_teams",
        "espnfantasy_rosters",
        "espnfantasy_matchups",
        "espnfantasy_draft",
        "espnfantasy_transactions",
        "espnfantasy_boxscore",
        "espnfantasy_player_info",
        "espnfantasy_player_card",
        "espnfantasy_everything",
    } <= names


def test_view_params_are_string_list_not_csv():
    """A comma-joined `view` is silently ignored by ESPN (HTTP 200 + bare skeleton),
    so `string_csv` here would produce empty-looking leagues with no error anywhere."""
    offenders = [
        f"{ep['name']}.{p['name']}"
        for ep in _spec()["endpoints"]
        for p in ep.get("params", [])
        if p["name"] == "view" and p["type"] != "string_list"
    ]
    assert not offenders, f"view params must be string_list: {offenders}"


def test_league_scoped_endpoints_use_optional_cookie_auth():
    """League reads must use the `private` key: optional cookie auth, so public
    leagues work anonymously and ESPN_FANTASY_COOKIE reaches private ones."""
    spec = _spec()
    private = spec["provider"]["auth"]["private"]
    assert private["type"] == "static_header"
    assert private["header"] == "Cookie"
    assert private["env"] == "ESPN_FANTASY_COOKIE"
    assert private["optional"] is True, "must be optional or public leagues break without cookies"

    wrong = [
        ep["name"]
        for ep in spec["endpoints"]
        if "{leagueId}" in ep["path"] and ep.get("auth") != "private"
    ]
    assert not wrong, f"league-scoped endpoints must use the private auth key: {wrong}"


def test_no_secrets_in_spec():
    """The cookie is a real ESPN session credential — the spec may only name the env var."""
    raw = (Path(__file__).resolve().parents[2] / "src/sportsdata_mcp/specs/espnfantasy.yaml").read_text()
    assert "espn_s2=" not in raw or "ESPN_FANTASY_COOKIE=" in raw
    assert "value:" not in _spec()["provider"]["auth"]["private"]


def test_all_five_fantasy_games_are_selectable():
    games = {"ffl", "flb", "fba", "fhl", "wfba"}
    for ep in _spec()["endpoints"]:
        for p in ep.get("params", []):
            if p["name"] == "game":
                assert set(p["enum"]) == games, f"{ep['name']} game enum drifted"


async def test_unknown_league_is_a_clean_error(espnf_server):
    with pytest.raises((MCPToolError, RuntimeError)):
        await espnf_server.call_tool("espnfantasy_league_settings", _league_args(seasonId=1999))


# ─── live ───────────────────────────────────────────────────────────────


@pytest.mark.live
async def test_games_catalogue_live(espnf_server):
    try:
        res = await espnf_server.call_tool("espnfantasy_games", {})
    except (MCPToolError, RuntimeError) as e:
        pytest.xfail(f"ESPN fantasy unavailable: {e}")
    data = _payload(res)
    assert isinstance(data, list) and len(data) == 5
    abbrevs = {g["abbrev"] for g in data}
    assert {"FFL", "FLB", "FBA", "FHL", "WFBA"} == abbrevs
    # Every game must expose the season + scoring period the other tools need.
    for g in data:
        assert g["currentSeasonId"] > 2020
        assert g["currentSeason"]["currentScoringPeriod"]["id"] >= 1


@pytest.mark.live
async def test_pro_teams_live(espnf_server):
    try:
        res = await espnf_server.call_tool("espnfantasy_pro_teams", {"game": "ffl", "seasonId": 2025})
    except (MCPToolError, RuntimeError) as e:
        pytest.xfail(f"ESPN fantasy unavailable: {e}")
    teams = _payload(res)["settings"]["proTeams"]
    assert len(teams) == 33  # 32 NFL clubs + id 0 (free agent)
    by_id = {t["id"]: t["abbrev"].upper() for t in teams}
    assert by_id[12] == "KC" and by_id[33] == "BAL"


@pytest.mark.live
async def test_league_settings_live(espnf_server):
    try:
        res = await espnf_server.call_tool("espnfantasy_league_settings", _league_args())
    except (MCPToolError, RuntimeError) as e:
        pytest.xfail(f"ESPN fantasy unavailable: {e}")
    settings = _payload(res)["settings"]
    assert settings["name"]
    assert settings["size"] >= 2
    assert "scoringSettings" in settings and "rosterSettings" in settings


@pytest.mark.live
async def test_teams_carry_records_live(espnf_server):
    """Guards the view model: without a working `view` the teams[] entries come back
    as bare {id, abbrev, owners} stubs, which is what a comma-joined view produces."""
    try:
        res = await espnf_server.call_tool("espnfantasy_teams", _league_args())
    except (MCPToolError, RuntimeError) as e:
        pytest.xfail(f"ESPN fantasy unavailable: {e}")
    teams = _payload(res)["teams"]
    assert teams, "no teams returned"
    assert "record" in teams[0], "mTeam view did not take (repeated-param regression?)"
    assert "overall" in teams[0]["record"]


@pytest.mark.live
async def test_multiple_views_compose_live(espnf_server):
    """Two views in one call must BOTH apply — the repeated-param contract."""
    try:
        res = await espnf_server.call_tool(
            "espnfantasy_league", _league_args(view=["mTeam", "mMatchup"])
        )
    except (MCPToolError, RuntimeError) as e:
        pytest.xfail(f"ESPN fantasy unavailable: {e}")
    data = _payload(res)
    assert "record" in data["teams"][0], "mTeam did not apply"
    assert data.get("schedule"), "mMatchup did not apply"


@pytest.mark.live
async def test_matchups_live(espnf_server):
    try:
        res = await espnf_server.call_tool("espnfantasy_matchups", _league_args())
    except (MCPToolError, RuntimeError) as e:
        pytest.xfail(f"ESPN fantasy unavailable: {e}")
    schedule = _payload(res)["schedule"]
    assert schedule
    m = schedule[0]
    assert "matchupPeriodId" in m and "home" in m
    assert "totalPoints" in m["home"]


@pytest.mark.live
async def test_draft_picks_live(espnf_server):
    try:
        res = await espnf_server.call_tool("espnfantasy_draft", _league_args())
    except (MCPToolError, RuntimeError) as e:
        pytest.xfail(f"ESPN fantasy unavailable: {e}")
    detail = _payload(res)["draftDetail"]
    assert detail["drafted"] is True
    picks = detail["picks"]
    assert picks and picks[0]["overallPickNumber"] == 1
    assert "playerId" in picks[0] and "roundId" in picks[0]


@pytest.mark.live
async def test_boxscore_has_lineups_live(espnf_server):
    try:
        res = await espnf_server.call_tool("espnfantasy_boxscore", _league_args(scoringPeriodId=WEEK))
    except (MCPToolError, RuntimeError) as e:
        pytest.xfail(f"ESPN fantasy unavailable: {e}")
    schedule = _payload(res)["schedule"]
    assert schedule
    assert any("totalPoints" in m.get("home", {}) for m in schedule)


@pytest.mark.live
async def test_transactions_need_scoring_period_live(espnf_server):
    """`transactions` only appears when scoringPeriodId is sent — a documented trap."""
    try:
        res = await espnf_server.call_tool("espnfantasy_transactions", _league_args(scoringPeriodId=WEEK))
    except (MCPToolError, RuntimeError) as e:
        pytest.xfail(f"ESPN fantasy unavailable: {e}")
    data = _payload(res)
    if "transactions" not in data:
        pytest.skip("no transactions in this scoring period")
    assert isinstance(data["transactions"], list)


@pytest.mark.live
async def test_free_agent_filter_live(espnf_server):
    """Exercises the JSON header param end-to-end: a dict must reach ESPN as JSON
    (a Python repr would be rejected) AND the filter must actually narrow the set."""
    args = _league_args(
        scoringPeriodId=WEEK,
        fantasy_filter={
            "players": {
                "filterStatus": {"value": ["FREEAGENT", "WAIVERS"]},
                "limit": 5,
                "sortPercOwned": {"sortPriority": 1, "sortAsc": False},
            }
        },
    )
    try:
        res = await espnf_server.call_tool("espnfantasy_player_info", args)
    except (MCPToolError, RuntimeError) as e:
        pytest.xfail(f"ESPN fantasy unavailable: {e}")
    players = _payload(res)["players"]
    assert 0 < len(players) <= 5, "limit did not apply — filter header not serialised as JSON?"
    assert {p["status"] for p in players} <= {"FREEAGENT", "WAIVERS"}
    assert "ownership" in players[0]["player"]


@pytest.mark.live
async def test_player_card_live(espnf_server):
    args = _league_args(
        fantasy_filter={
            "players": {
                "filterIds": {"value": [15825]},
                "filterStatsForTopScoringPeriodIds": {
                    "value": 16,
                    "additionalValue": ["002018", "102018"],
                },
            }
        }
    )
    try:
        res = await espnf_server.call_tool("espnfantasy_player_card", args)
    except (MCPToolError, RuntimeError) as e:
        pytest.xfail(f"ESPN fantasy unavailable: {e}")
    players = _payload(res)["players"]
    if not players:
        pytest.skip("player card empty for this seed")
    assert players[0]["player"]["fullName"]


@pytest.mark.live
async def test_communication_404_is_a_clean_error_live(espnf_server):
    """The test league never used the message board — ESPN 404s. Assert it surfaces as
    a tool error rather than something that looks like a bug in the spec."""
    with pytest.raises((MCPToolError, RuntimeError)):
        await espnf_server.call_tool("espnfantasy_communication", _league_args())
