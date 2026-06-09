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
    # TODO(DATAGOLF_KEY): add rows for datagolf_approach_skill /
    # datagolf_hist_results_event_list once their live shapes are verified with a key.
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
