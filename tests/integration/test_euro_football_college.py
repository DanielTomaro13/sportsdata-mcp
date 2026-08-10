"""OpenLigaDB + EuroLeague + NCAA — registration (offline) + live probes.

Three providers tested together because each contributes one league-table-shaped
surface to the catalogue, and each has exactly one convention that silently returns
the wrong number:

  * OpenLigaDB — `matchResults[0]` is often HALF TIME, not the final score.
  * EuroLeague — a box-score player line is {player, stats}, not flat.
  * NCAA       — scoreboard entries wrap the real object under `game`, and standings
                 are grouped by conference rather than being a flat list of schools.

Three of these assertions were written from assumption first and corrected only
because the live run disagreed — which is the entire argument for probing before
documenting.

Run the live tests with::

    pytest -m live tests/integration/test_euro_football_college.py
"""

from __future__ import annotations

import json

import pytest
from fastmcp.exceptions import ToolError as MCPToolError

from sportsdata_mcp.config import Config
from sportsdata_mcp.server import build_server

_GROUPS = ["openligadb.football", "euroleague.basketball", "ncaa.college"]
BL_SEASON = "2024"
EL_SEASON = "E2024"


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


# ─── offline ────────────────────────────────────────────────────────────


async def test_tools_registered(server):
    names = {t.name for t in await server.list_tools()}
    assert {
        "openligadb_leagues", "openligadb_teams", "openligadb_matchdays",
        "openligadb_current_matchday", "openligadb_season_matches",
        "openligadb_matchday_matches", "openligadb_match", "openligadb_table",
        "euroleague_seasons", "euroleague_clubs", "euroleague_people",
        "euroleague_rounds", "euroleague_games", "euroleague_game",
        "euroleague_game_stats",
        "ncaa_scoreboard", "ncaa_standings", "ncaa_rankings",
    } <= names


# ─── live: OpenLigaDB ───────────────────────────────────────────────────


@pytest.mark.live
async def test_bundesliga_table_live(server):
    try:
        table = _payload(await server.call_tool(
            "openligadb_table", {"league": "bl1", "season": BL_SEASON}))
    except (MCPToolError, RuntimeError) as e:
        pytest.xfail(f"openligadb unavailable: {e}")
    assert len(table) == 18, "the Bundesliga has 18 clubs"
    row = table[0]
    assert {"teamName", "points", "matches", "goals", "opponentGoals", "goalDiff"} <= set(row)
    # `goals` is scored and `opponentGoals` conceded — an easy misread when both sit
    # on the same object, so pin the relationship.
    assert row["goalDiff"] == row["goals"] - row["opponentGoals"]


@pytest.mark.live
async def test_full_time_score_is_not_the_first_result_entry_live(server):
    """matchResults holds BOTH half time and full time. Taking [0] gives half time in
    many matches — the single most damaging mistake against this API."""
    try:
        matches = _payload(await server.call_tool(
            "openligadb_matchday_matches",
            {"league": "bl1", "season": BL_SEASON, "matchday": 1}))
    except (MCPToolError, RuntimeError) as e:
        pytest.xfail(f"openligadb unavailable: {e}")
    finished = [m for m in matches if m.get("matchIsFinished")]
    if not finished:
        pytest.skip("no finished matches on this matchday")
    results = finished[0]["matchResults"]
    names = {r["resultName"] for r in results}
    assert "Endergebnis" in names, "expected a full-time result entry to select on"
    assert len(results) >= 2, "half time and full time both present — [0] is not the final score"


@pytest.mark.live
async def test_unknown_league_is_a_clean_error_live(server):
    """An unknown shortcut 404s rather than returning empty data — which is the GOOD
    outcome: a typo surfaces as an error instead of looking like an off-season. I had
    documented the opposite from assumption; this test is what caught it."""
    with pytest.raises((MCPToolError, RuntimeError)):
        await server.call_tool(
            "openligadb_teams", {"league": "notaleague", "season": BL_SEASON})


# ─── live: EuroLeague ───────────────────────────────────────────────────


@pytest.mark.live
async def test_euroleague_list_envelope_live(server):
    try:
        d = _payload(await server.call_tool(
            "euroleague_games", {"competition": "E", "season": EL_SEASON, "limit": 5}))
    except (MCPToolError, RuntimeError) as e:
        pytest.xfail(f"euroleague unavailable: {e}")
    assert {"total", "data"} <= set(d)
    game = d["data"][0]
    # local/road, not home/away.
    assert {"local", "road", "gameCode"} <= set(game)
    assert "home" not in game and "away" not in game


@pytest.mark.live
async def test_euroleague_single_game_is_unwrapped_live(server):
    """List endpoints wrap in {data}; a single game does NOT. Assuming one shape for
    both is the usual error here."""
    try:
        d = _payload(await server.call_tool(
            "euroleague_game", {"competition": "E", "season": EL_SEASON, "gameCode": 1}))
    except (MCPToolError, RuntimeError) as e:
        pytest.xfail(f"euroleague unavailable: {e}")
    assert "data" not in d
    assert d["gameCode"] == 1


@pytest.mark.live
async def test_euroleague_boxscore_uses_pir_live(server):
    """`valuation` is PIR, European basketball's efficiency metric — it has no
    equivalent in the NBA provider, so it must survive into the payload."""
    try:
        d = _payload(await server.call_tool(
            "euroleague_game_stats", {"competition": "E", "season": EL_SEASON, "gameCode": 1}))
    except (MCPToolError, RuntimeError) as e:
        pytest.xfail(f"euroleague unavailable: {e}")
    assert {"local", "road"} <= set(d)
    players = d["local"]["players"]
    if not players:
        pytest.skip("no player lines for this game")
    entry = players[0]
    # A player line is NESTED: identity under `player`, numbers under `stats`.
    # Reading entry["points"] gets nothing — a shape I documented wrongly at first.
    assert set(entry) >= {"player", "stats"}
    stats = entry["stats"]
    assert "valuation" in stats, "PIR must survive into the payload"
    assert isinstance(stats["timePlayed"], (int, float)), "timePlayed is SECONDS, not MM:SS"


# ─── live: NCAA ─────────────────────────────────────────────────────────


@pytest.mark.live
async def test_ncaa_scoreboard_double_wrapping_live(server):
    """Each entry is a one-key object wrapping `game` — reading games[0] directly gets
    a wrapper, not a game."""
    try:
        d = _payload(await server.call_tool(
            "ncaa_scoreboard", {"sport": "football", "division": "fbs"}))
    except (MCPToolError, RuntimeError) as e:
        pytest.xfail(f"ncaa-api unavailable: {e}")
    assert "games" in d
    if not d["games"]:
        pytest.skip("off-season — no games on the board")
    entry = d["games"][0]
    assert set(entry) == {"game"}, "entries wrap the real object under `game`"
    game = entry["game"]
    assert {"home", "away", "gameState"} <= set(game)


@pytest.mark.live
async def test_ncaa_rankings_are_uppercase_keys_live(server):
    """Rankings use UPPERCASE keys while standings use spaced title-case — the two
    tools genuinely disagree, so both conventions are pinned."""
    try:
        d = _payload(await server.call_tool(
            "ncaa_rankings",
            {"sport": "football", "division": "fbs", "poll": "associated-press"}))
    except (MCPToolError, RuntimeError) as e:
        pytest.xfail(f"ncaa-api unavailable: {e}")
    rows = d.get("data") or []
    if not rows:
        pytest.skip("no poll published right now")
    assert {"RANK", "SCHOOL"} <= set(rows[0])


@pytest.mark.live
async def test_ncaa_standings_have_spaced_column_names_live(server):
    try:
        d = _payload(await server.call_tool(
            "ncaa_standings", {"sport": "football", "division": "fbs"}))
    except (MCPToolError, RuntimeError) as e:
        pytest.xfail(f"ncaa-api unavailable: {e}")
    rows = d.get("data") or []
    if not rows:
        pytest.skip("no standings published right now")
    # Grouped BY CONFERENCE: data[] is conferences, each with its own standings list.
    # data[0] is a conference, not a team.
    assert {"conference", "standings"} <= set(rows[0])
    teams = rows[0]["standings"]
    assert teams and "School" in teams[0]
    assert any(" " in k for k in teams[0]), "inner columns are spaced, human-readable names"
