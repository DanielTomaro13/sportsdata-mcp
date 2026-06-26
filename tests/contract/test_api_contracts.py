"""Live API response-contract tests.

Purpose
-------
Catch the two regressions that the offline suite cannot:

1. **We broke a spec** — a wrong path, base URL, or required param. The upstream
   answers with a 4xx, or with a 200 whose shape no longer matches what we
   documented in the spec's ``response_hint`` and in ``documentation/*.md``.
2. **The upstream changed shape** — it still answers 200 but the documented
   top-level keys are gone.

Each case calls a real tool against the real API and asserts the documented
top-level structure (and, for list payloads, the documented keys on the first
item). Expectations are written **explicitly** here (not derived from the spec) so
this file is an independent contract: if someone edits a ``response_hint`` to match
a drifted API, this test still fails until the change is acknowledged.

Resilience (so it never blocks a PR on something outside our control)
--------------------------------------------------------------------
* **FAIL** — the API responded but the structure is wrong, OR it returned a
  ``400 / 404 / 405 / 422`` (our path/params are wrong). This is a real contract break.
* **SKIP** — transient or environmental: a network error, timeout, ``5xx``, an
  auth/geo block (``401 / 403 / 429``), a non-JSON block page, a missing API key
  (e.g. ``DATAGOLF_KEY``), or a feed that legitimately returned an empty list.

Run locally with::

    pytest -m contract
    DATAGOLF_KEY=... pytest -m contract     # also exercises Data Golf
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

import pytest
from fastmcp.exceptions import ToolError as MCPToolError

from sportsdata_mcp.config import Config
from sportsdata_mcp.server import build_server
from sportsdata_mcp.spec_loader import load_all_specs

# HTTP statuses that mean "our request was wrong" → a genuine contract break.
_BREAK_STATUSES = {400, 404, 405, 410, 422}


@dataclass(frozen=True)
class Contract:
    """One documented response shape to verify against the live API."""

    tool: str
    params: dict = field(default_factory=dict)
    # Required top-level keys when the payload is a JSON object.
    top_keys: tuple[str, ...] = ()
    # If set, the list to inspect: "" = the payload itself is a top-level array,
    # otherwise the name of the object key whose value is the list.
    list_at: str | None = None
    # Required keys on the first element of that list.
    item_keys: tuple[str, ...] = ()


# ─── The contract table ──────────────────────────────────────────────────
# Verified live 2026-06-06. Stable historical ids are used where a fixed target
# is needed (e.g. a 2025 MLB gamePk) so the shape doesn't drift with the calendar.
CONTRACTS: list[Contract] = [
    # ── MLB (statsapi.mlb.com — public) ──
    Contract("mlb_teams", {"sportId": 1}, ("teams",), "teams", ("id", "name", "abbreviation")),
    Contract("mlb_schedule", {"sportId": 1, "date": "2025-09-01"}, ("dates", "totalGames")),
    Contract("mlb_standings", {"leagueId": "103,104", "season": 2025}, ("records",), "records", ("teamRecords",)),
    Contract("mlb_boxscore", {"gamePk": 776498}, ("teams",)),
    Contract("mlb_live_feed", {"gamePk": 776498}, ("gamePk", "gameData", "liveData")),
    Contract("mlb_player", {"personId": 592450}, ("people",), "people", ("id", "fullName")),
    Contract("mlb_leaders", {"leaderCategories": ["homeRuns"], "season": 2025, "limit": 5}, ("leagueLeaders",)),
    Contract("mlb_meta", {"type": "positions"}, list_at="", item_keys=("code", "abbrev", "type")),
    Contract("mlb_awards_list", {}, ("awards",), "awards", ("id", "name")),
    Contract("mlb_seasons_all", {"sportId": 1}, ("seasons",), "seasons", ("seasonId", "seasonStartDate", "seasonEndDate")),
    Contract("mlb_people_changes", {"updatedSince": "2026-06-01T00:00:00Z"}, ("people",), "people", ("id", "fullName")),
    # ── OpenF1 (api.openf1.org — public) ──
    Contract("openf1_sessions", {"session_key": "latest"}, list_at="", item_keys=("session_key", "session_name")),
    Contract("openf1_meetings", {"meeting_key": "latest"}, list_at="", item_keys=("meeting_key", "meeting_name")),
    Contract("openf1_drivers", {"session_key": "latest"}, list_at="", item_keys=("driver_number", "full_name")),
    # ── Cricket Australia (apiv2.cricket.com.au — public) ──
    Contract("cricketaustralia_fixtures", {"isCompleted": True, "limit": 5}, ("fixtures",), "fixtures", ("id", "competitionId")),
    Contract("cricketaustralia_teams", {}, ("teams",), "teams", ("id", "name")),
    Contract("cricketaustralia_competitions", {}, ("competitions",)),
    # ── ESPN (site.api.espn.com — public) ──
    Contract("espn_scoreboard", {"sport": "baseball", "league": "mlb"}, ("leagues", "events")),
    Contract("espn_teams", {"sport": "baseball", "league": "mlb"}, ("sports",)),
    # ── NBA (cdn.nba.com — public) ──
    Contract("nba_scoreboard_today", {}, ("scoreboard",)),
    Contract("nba_schedule", {}, ("leagueSchedule",)),
    # ── NRL (mc.championdata.com — public) ──
    Contract("nrl_competitions", {}, ("competitionDetails",)),
    # ── AFL (api.afl.com.au — public core) ──
    Contract("afl_competitions_list", {}, ("meta", "competitions"), "competitions", ("id",)),
    # ── Data Golf (needs DATAGOLF_KEY → skips in CI) ──
    Contract("datagolf_player_list", {}, list_at="", item_keys=("dg_id", "player_name")),
    Contract("datagolf_approach_skill", {}, ("last_updated", "time_period", "data"), "data", ("dg_id", "player_name")),
    Contract("datagolf_hist_results_event_list", {}, list_at="", item_keys=("event_id", "event_name", "calendar_year", "tour")),
    # ── Kalshi (api.elections.kalshi.com — public market data) ──
    Contract("kalshi_markets", {"limit": 2}, ("cursor", "markets"), "markets", ("ticker", "event_ticker", "title", "status")),
    Contract("kalshi_series_list", {"category": "Sports"}, ("series",), "series", ("ticker", "title", "category")),
    Contract("kalshi_exchange_status", {}, ("exchange_active", "trading_active")),
    Contract("kalshi_structured_targets", {"page_size": 2}, ("cursor", "structured_targets"), "structured_targets", ("id", "name", "type")),
    # ── Polymarket (geo-gated: skips where edge-blocked, verifies from US runners) ──
    Contract("polymarket_markets", {"limit": 2, "active": True, "closed": False}, list_at="", item_keys=("id", "question", "slug")),
    Contract("polymarket_events", {"limit": 2, "active": True, "closed": False}, list_at="", item_keys=("id", "title", "slug")),
    # ── X/Twitter (needs X_BEARER_TOKEN → skips without one) ──
    Contract("twitter_user_by_username", {"username": "NBA"}, ("data",)),
    Contract("twitter_trends", {"woeid": 1}, ("data",)),
    # ── Premier League (premierleague.com private APIs — public, global, runs in CI) ──
    Contract("pl_competitions", {"limit": 5}, ("pagination", "data"), "data", ("id", "name")),
    Contract("pl_teams", {"cid": 8, "limit": 60}, ("pagination", "data"), "data", ("id", "name", "shortName")),
    Contract("pl_standings", {"cid": 8, "sid": 2025, "live": False}, ("matchweek", "tables")),
    Contract("pl_player_leaderboard", {"cid": 8, "sid": 2025, "sort": "goals:desc", "limit": 5}, ("pagination", "data")),
    # ── LaLiga (apim.laliga.com — ships a public key; global, runs in CI unless the key rotated) ──
    Contract("laliga_competitions", {}, ("competitions",), "competitions", ("id", "slug", "opta_id")),
    Contract("laliga_standing", {"slug": "laliga-easports-2025"}, ("total", "standings"), "standings", ("position", "points", "team")),
    Contract("laliga_players_stats", {"slug": "laliga-easports-2025", "limit": 5}, ("total", "player_stats"), "player_stats", ("slug", "opta_id", "stats")),
    Contract("laliga_matches", {"subscription": "laliga-easports-2025", "competition": "primera-division", "gameweek": 1, "limit": 10}, ("total", "matches"), "matches", ("slug", "home_team", "away_team", "competition")),
    # ── Serie A (api-sdp.legaseriea.it — public no-auth; global, runs in CI) ──
    Contract("seriea_competitions", {}, ("competitions",), "competitions", ("competitionId", "name")),
    Contract("seriea_seasons", {}, ("seasons",), "seasons", ("seasonId", "seasonName")),
    Contract("seriea_standings", {"seasonId": "serie-a::Football_Season::5f0e080fc3a44073984b75b3a8e06a8a"}, ("standings",), "standings", ("type", "teams")),
    Contract("seriea_team_stats", {"seasonId": "serie-a::Football_Season::5f0e080fc3a44073984b75b3a8e06a8a"}, ("teams",), "teams", ("teamId", "stats")),
    Contract("seriea_matches", {"seasonId": "serie-a::Football_Season::5f0e080fc3a44073984b75b3a8e06a8a"}, ("matches",), "matches", ("matchId", "home", "away", "status")),
    # ── Bookmakers (often geo/bot-blocked from CI → skip; verified locally) ──
    # These pin each book's response shape for local regression value; in CI they
    # mostly skip because GitHub's runners are geo/bot-blocked by the AU books.
    Contract("tab_sports", {}, ("sports",)),
    Contract("pinnacle_sports", {}, list_at="", item_keys=("id", "matchupCount")),
    Contract("racingandsports_todays_racing", {}, list_at="", item_keys=("Discipline", "Countries")),
    Contract("sportsbet_upcoming_events", {}, list_at="", item_keys=("id", "name", "className")),
    Contract("pointsbet_events_nextup", {}, ("events",)),
    Contract("betr_event_types", {}, ("Items",)),
    Contract("unibet_kambi_odds_ladder", {}, list_at="", item_keys=("name", "steps")),
    Contract("entain_racing_search", {}, ("facets", "meta")),
    Contract("fanduel_racing_quicklinks", {}, list_at="", item_keys=("id", "name", "quicklinks")),
    Contract("betfair_navigation", {"nodeIds": ["EVENT_TYPE:7"]}, ("nodes", "edges")),
    Contract("dabble_active_competitions", {}, ("data",)),
    Contract("dabble_competition_fixtures", {"competitionId": "ad4c78ec-e39d-45ee-8cec-ff5d485a3205"}, ("data",)),
    # ── SuperCoach (supercoach.com.au — public, no auth, not geo-blocked → runs in CI) ──
    # Uniform surface across all 7 games; AFL (calendar-year, in-season) is the probe.
    Contract("supercoach_settings", {"sport": "afl", "year": 2026}, ("competition", "system", "game")),
    Contract("supercoach_teams", {"sport": "afl", "year": 2026}, list_at="", item_keys=("id", "name", "abbrev")),
    Contract(
        "supercoach_players",
        {"sport": "afl", "year": 2026, "round": 1, "embed": "player_stats"},
        list_at="",
        item_keys=("id", "first_name", "last_name", "player_stats"),
    ),
    Contract(
        "supercoach_real_fixture",
        {"sport": "afl", "year": 2026, "round": 1, "page_size": 5},
        list_at="",
        item_keys=("id", "team1", "team2", "round"),
    ),
    Contract("supercoach_player", {"sport": "afl", "year": 2026, "id": 1}, ("id", "first_name", "team_id")),
    Contract("supercoach_leagues", {"sport": "afl", "year": 2026}, list_at="", item_keys=("id", "name", "code", "type")),
    # draft mode (mode=draft) — players carry the extra top-level predraft_rank
    Contract(
        "supercoach_players",
        {"sport": "afl", "year": 2026, "mode": "draft", "round": 1, "embed": "player_stats"},
        list_at="",
        item_keys=("id", "first_name", "predraft_rank"),
    ),
    # ── NBL (prod.rosetta.nbl.com.au — public, referer-gated; runs in CI) ──
    # Enveloped {type, count, data:[…]}; NBL26 (year 2025) is the current season.
    Contract("nbl_seasons", {}, ("type", "count", "data"), "data", ("id", "name", "year", "season_type")),
    Contract("nbl_teams", {}, ("type", "count", "data"), "data", ("id", "name", "team_code")),
    Contract("nbl_ladder", {"year": 2025, "seasonType": "regular"}, ("type", "count", "data"), "data", ("position", "won", "lost")),
    Contract("nbl_schedule", {"year": 2025, "seasonType": "all"}, ("type", "count", "data"), "data", ("id", "round", "home_team", "away_team")),
    Contract("nbl_players", {"year": 2025}, ("type", "count", "data"), "data", ("jersey_number", "player", "team")),
    Contract("nbl_news", {"limit": 5}, list_at="", item_keys=("id", "title", "slug", "published_date")),
    # ── WTA (api.wtatennis.com — official, public, no auth; runs in CI) ──
    Contract(
        "wta_rankings",
        {"type": "rankSingles", "metric": "singles", "pageSize": 5},
        list_at="",
        item_keys=("player", "ranking", "points", "movement"),
    ),
    Contract("wta_players", {"name": "Swiatek"}, ("pageInfo", "content"), "content", ("id", "fullName", "countryCode")),
    Contract("wta_player", {"playerId": 320760}, ("id", "fullName", "countryCode")),
    Contract("wta_tournaments", {"pageSize": 5}, ("pageInfo", "content"), "content", ("tournamentGroup", "year", "title")),
    Contract("wta_tournament_matches", {"groupId": 901, "year": 2025}, ("tournament", "matches")),
]


@pytest.fixture
async def contract_server():
    """A server with every group enabled (so any tool in the table is callable)."""
    specs = load_all_specs()
    groups = sorted({t.group for s in specs for t in list(s.endpoints) + list(s.dispatchers)})
    mcp, reg = build_server(Config(enabled_groups=groups))
    try:
        yield mcp
    finally:
        await reg.aclose()


def _payload(result):
    if result.structured_content is not None:
        return result.structured_content
    return json.loads(result.content[0].text) if result.content else None


def _is_contract_break(err: Exception) -> bool:
    """True only when the error means *our request* was wrong (a real break)."""
    m = re.search(r"HTTP (\d{3})", str(err))
    return bool(m) and int(m.group(1)) in _BREAK_STATUSES


# ─── offline guard ───────────────────────────────────────────────────────
# Runs in the deterministic suite (no `live` marker). A typo'd or renamed tool in
# the table would otherwise raise "Unknown tool" at call time — which the live test
# classifies as a SKIP — so the contract would silently stop running. This fails
# loudly instead, with no network needed.


async def test_contract_table_is_well_formed(contract_server):
    registered = {t.name for t in await contract_server.list_tools()}
    unknown = sorted({c.tool for c in CONTRACTS} - registered)
    assert not unknown, f"contract table references tools that don't exist: {unknown}"
    # every row must assert *something* (a no-op contract is a silent gap)
    empty = [c.tool for c in CONTRACTS if not c.top_keys and c.list_at is None]
    assert not empty, f"contract rows with no expectations: {empty}"


# ─── live contract checks ─────────────────────────────────────────────────


@pytest.mark.live
@pytest.mark.contract
@pytest.mark.parametrize("c", CONTRACTS, ids=lambda c: c.tool)
async def test_response_contract(contract_server, c: Contract):
    try:
        result = await contract_server.call_tool(c.tool, c.params)
    except (MCPToolError, RuntimeError, ValueError) as e:
        if _is_contract_break(e):
            pytest.fail(f"{c.tool} {c.params}: contract break — {e}")
        pytest.skip(f"{c.tool}: unreachable / blocked / keyless — {e}")

    payload = _payload(result)
    assert payload is not None, f"{c.tool}: empty response body"

    # Top-level object keys (documented structure).
    if c.top_keys:
        assert isinstance(payload, dict), f"{c.tool}: expected an object, got {type(payload).__name__}"
        missing = [k for k in c.top_keys if k not in payload]
        assert not missing, f"{c.tool}: missing documented top-level keys {missing}; got {sorted(payload)[:12]}"

    # List shape + the documented keys on its first element.
    if c.list_at is not None:
        seq = payload if c.list_at == "" else payload.get(c.list_at)
        assert isinstance(seq, list), f"{c.tool}: expected a list at {c.list_at or '<root>'!r}, got {type(seq).__name__}"
        if not seq:
            pytest.skip(f"{c.tool}: list at {c.list_at or '<root>'!r} is empty (data availability)")
        first = seq[0]
        assert isinstance(first, dict), f"{c.tool}: list items should be objects"
        missing = [k for k in c.item_keys if k not in first]
        assert not missing, f"{c.tool}: list item missing documented keys {missing}; got {sorted(first)[:12]}"
