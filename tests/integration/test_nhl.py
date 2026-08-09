"""NHL (api-web.nhle.com) — registration (offline) + live probes.

The league's own web API: no key, no geo-block. The offline tests pin the two
conventions that turn a working call into a 404 — concatenated-year season ids
(20242025, not 2024) and the /now paths that 307-redirect.

Run the live tests with::

    pytest -m live tests/integration/test_nhl.py
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml
from fastmcp.exceptions import ToolError as MCPToolError

from sportsdata_mcp.config import Config
from sportsdata_mcp.server import build_server

_GROUPS = ["nhl.reference", "nhl.schedule", "nhl.game", "nhl.stats"]
# A completed regular-season game and a durable star: frozen seeds so the shapes
# under test don't move with the calendar.
GAME_ID = 2024020500
PLAYER_ID = 8478402  # Connor McDavid
TEAM = "TOR"
SEASON = "20242025"


@pytest.fixture
async def nhl_server():
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
    path = Path(__file__).resolve().parents[2] / "src/sportsdata_mcp/specs/nhl.yaml"
    return yaml.safe_load(path.read_text())


# ─── offline ────────────────────────────────────────────────────────────


async def test_tools_registered(nhl_server):
    names = {t.name for t in await nhl_server.list_tools()}
    assert {
        "nhl_seasons", "nhl_roster", "nhl_player", "nhl_schedule", "nhl_club_schedule",
        "nhl_scores", "nhl_boxscore", "nhl_game_landing", "nhl_standings",
        "nhl_skater_leaders", "nhl_goalie_leaders",
    } <= names


def test_season_params_document_the_concatenated_format():
    """A season id of `2024` returns 404, not an empty list — so the format has to be
    in the param description where the model will read it."""
    spec = _spec()
    checked = 0
    for ep in spec["endpoints"]:
        for p in ep.get("params", []):
            if p["name"] == "season":
                assert "20242025" in p["description"], f"{ep['name']} doesn't show the format"
                checked += 1
    assert checked >= 2


def test_uses_the_current_api_host():
    """statsapi.web.nhl.com has been dead since 2023; anything pointing there is stale."""
    base = _spec()["provider"]["base_urls"]["default"]
    assert base.startswith("https://api-web.nhle.com")
    assert "statsapi" not in base


async def test_bad_season_is_a_clean_error(nhl_server):
    with pytest.raises((MCPToolError, RuntimeError)):
        await nhl_server.call_tool("nhl_roster", {"team": TEAM, "season": "2024"})


# ─── live ───────────────────────────────────────────────────────────────


@pytest.mark.live
async def test_seasons_live(nhl_server):
    try:
        res = await nhl_server.call_tool("nhl_seasons", {})
    except (MCPToolError, RuntimeError) as e:
        pytest.xfail(f"NHL API unavailable: {e}")
    seasons = _payload(res)["seasons"]
    assert seasons
    assert all(len(str(s["id"])) == 8 for s in seasons[:5]), "season ids are concatenated years"


@pytest.mark.live
async def test_now_path_redirect_is_followed_live(nhl_server):
    """/standings/now 307s to a dated path. If redirects stopped being followed this
    would return nothing, so it's worth asserting rather than assuming."""
    try:
        res = await nhl_server.call_tool("nhl_standings", {"date": "now"})
    except (MCPToolError, RuntimeError) as e:
        pytest.xfail(f"NHL API unavailable: {e}")
    standings = _payload(res)["standings"]
    assert standings, "307 redirect was not followed"
    row = standings[0]
    assert {"points", "gamesPlayed", "divisionSequence", "conferenceSequence"} <= set(row)


@pytest.mark.live
async def test_roster_is_split_by_position_group_live(nhl_server):
    """Three parallel arrays, not one `players` list — a consumer that assumes the
    latter gets nothing."""
    try:
        res = await nhl_server.call_tool("nhl_roster", {"team": TEAM, "season": SEASON})
    except (MCPToolError, RuntimeError) as e:
        pytest.xfail(f"NHL API unavailable: {e}")
    data = _payload(res)
    assert {"forwards", "defensemen", "goalies"} <= set(data)
    assert data["forwards"] and data["goalies"]
    assert {"id", "positionCode", "sweaterNumber"} <= set(data["forwards"][0])


@pytest.mark.live
async def test_player_landing_live(nhl_server):
    try:
        res = await nhl_server.call_tool("nhl_player", {"playerId": PLAYER_ID})
    except (MCPToolError, RuntimeError) as e:
        pytest.xfail(f"NHL API unavailable: {e}")
    d = _payload(res)
    assert d["playerId"] == PLAYER_ID
    # Names are localisation objects, not strings — pinned because it trips consumers.
    assert isinstance(d["firstName"], dict) and "default" in d["firstName"]
    assert "careerTotals" in d


@pytest.mark.live
async def test_boxscore_has_per_player_lines_live(nhl_server):
    try:
        res = await nhl_server.call_tool("nhl_boxscore", {"gameId": GAME_ID})
    except (MCPToolError, RuntimeError) as e:
        pytest.xfail(f"NHL API unavailable: {e}")
    d = _payload(res)
    assert d["id"] == GAME_ID
    stats = d["playerByGameStats"]
    home = stats["homeTeam"]
    assert {"forwards", "defense", "goalies"} <= set(home)
    skater = home["forwards"][0]
    assert {"playerId", "goals", "assists", "toi"} <= set(skater)
    assert ":" in str(skater["toi"]), "time on ice is a MM:SS string, not a number"


@pytest.mark.live
async def test_game_landing_has_scoring_summary_live(nhl_server):
    try:
        res = await nhl_server.call_tool("nhl_game_landing", {"gameId": GAME_ID})
    except (MCPToolError, RuntimeError) as e:
        pytest.xfail(f"NHL API unavailable: {e}")
    summary = _payload(res).get("summary", {})
    assert "scoring" in summary


@pytest.mark.live
async def test_schedule_live(nhl_server):
    try:
        res = await nhl_server.call_tool("nhl_schedule", {"date": "now"})
    except (MCPToolError, RuntimeError) as e:
        pytest.xfail(f"NHL API unavailable: {e}")
    d = _payload(res)
    assert "gameWeek" in d
    assert "regularSeasonStartDate" in d


@pytest.mark.live
async def test_club_schedule_live(nhl_server):
    try:
        res = await nhl_server.call_tool("nhl_club_schedule", {"team": TEAM, "season": SEASON})
    except (MCPToolError, RuntimeError) as e:
        pytest.xfail(f"NHL API unavailable: {e}")
    games = _payload(res)["games"]
    assert len(games) > 50, "a full NHL season is 82 games"
    assert {"id", "gameDate", "homeTeam", "awayTeam"} <= set(games[0])


@pytest.mark.live
async def test_scores_live(nhl_server):
    try:
        res = await nhl_server.call_tool("nhl_scores", {"date": "now"})
    except (MCPToolError, RuntimeError) as e:
        pytest.xfail(f"NHL API unavailable: {e}")
    d = _payload(res)
    assert "games" in d and "currentDate" in d


@pytest.mark.live
@pytest.mark.parametrize("tool,categories", [
    ("nhl_skater_leaders", ("goals", "assists", "points")),
    ("nhl_goalie_leaders", ("wins", "savePctg")),
])
async def test_leaders_live(nhl_server, tool, categories):
    try:
        res = await nhl_server.call_tool(tool, {"season_or_current": "current", "limit": 5})
    except (MCPToolError, RuntimeError) as e:
        pytest.xfail(f"NHL API unavailable: {e}")
    d = _payload(res)
    present = [c for c in categories if c in d]
    if not present:
        pytest.skip("no leader categories published (off-season)")
    assert d[present[0]], "leader category present but empty"
