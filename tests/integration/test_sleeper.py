"""Sleeper (api.sleeper.app) — registration (offline) + live probes.

Fantasy football with a fully public read API: no key, no cookie. That's why every
tool here is testable against a real league, unlike ESPN Fantasy's private tier.

Seeded with league 289646328504385536 — Sleeper's own documentation example, a
completed 2018 season, so its shapes are frozen.

Run the live tests with::

    pytest -m live tests/integration/test_sleeper.py
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml
from fastmcp.exceptions import ToolError as MCPToolError

from sportsdata_mcp.config import Config
from sportsdata_mcp.server import build_server

_GROUPS = ["sleeper.reference", "sleeper.league", "sleeper.draft"]
LEAGUE = "289646328504385536"


@pytest.fixture
async def sleeper_server():
    mcp, reg = build_server(Config(enabled_groups=_GROUPS))
    try:
        yield mcp
    finally:
        await reg.aclose()


def _payload(result):
    """Arrays come back as content text — FastMCP only fills structured_content for
    objects, and most of Sleeper's endpoints return top-level arrays."""
    if result.structured_content is not None:
        d = result.structured_content
        return d["result"] if set(d) == {"result"} else d
    if not result.content:
        return []
    return json.loads(result.content[0].text)


def _spec() -> dict:
    path = Path(__file__).resolve().parents[2] / "src/sportsdata_mcp/specs/sleeper.yaml"
    return yaml.safe_load(path.read_text())


# ─── offline ────────────────────────────────────────────────────────────


async def test_tools_registered(sleeper_server):
    names = {t.name for t in await sleeper_server.list_tools()}
    assert {
        "sleeper_state", "sleeper_user", "sleeper_trending_players",
        "sleeper_user_leagues", "sleeper_league", "sleeper_league_rosters",
        "sleeper_league_users", "sleeper_matchups", "sleeper_transactions",
        "sleeper_playoff_bracket", "sleeper_traded_picks",
        "sleeper_league_drafts", "sleeper_draft", "sleeper_draft_picks",
    } <= names


def test_the_15mb_player_catalogue_is_not_exposed():
    """/players/nfl is ~15 MB — Sleeper asks callers to fetch it at most daily. As a
    tool it would blow the model's context and abuse a free API, so it must stay out;
    draft picks and trending players cover player identity instead."""
    paths = [ep["path"] for ep in _spec()["endpoints"]]
    assert not any(p.rstrip("/").endswith("/players/{sport}") for p in paths)
    assert "/players/{sport}/trending/{add_or_drop}" in paths


def test_needs_no_credentials():
    """The whole advantage over ESPN Fantasy is that no cookie is required."""
    auth = _spec()["provider"]["auth"]
    assert set(auth) == {"default"}
    assert auth["default"]["type"] == "none"


# ─── live ───────────────────────────────────────────────────────────────


@pytest.mark.live
async def test_state_live(sleeper_server):
    try:
        res = await sleeper_server.call_tool("sleeper_state", {"sport": "nfl"})
    except (MCPToolError, RuntimeError) as e:
        pytest.xfail(f"sleeper unavailable: {e}")
    d = _payload(res)
    assert {"season", "week", "season_type"} <= set(d)
    assert d["season_type"] in {"pre", "regular", "post", "off"}


@pytest.mark.live
async def test_user_lookup_live(sleeper_server):
    try:
        res = await sleeper_server.call_tool("sleeper_user", {"username_or_id": "sleeperuser"})
    except (MCPToolError, RuntimeError) as e:
        pytest.xfail(f"sleeper unavailable: {e}")
    d = _payload(res)
    assert d["user_id"], "user_id is what every league call needs"
    assert d["display_name"]


@pytest.mark.live
async def test_league_settings_live(sleeper_server):
    try:
        res = await sleeper_server.call_tool("sleeper_league", {"league_id": LEAGUE})
    except (MCPToolError, RuntimeError) as e:
        pytest.xfail(f"sleeper unavailable: {e}")
    d = _payload(res)
    assert d["league_id"] == LEAGUE
    assert {"scoring_settings", "roster_positions", "total_rosters"} <= set(d)


@pytest.mark.live
async def test_the_roster_to_human_join_works_live(sleeper_server):
    """roster_id -> owner_id -> display_name is the join this API forces on you, and
    the one most consumers get wrong. If it breaks, matchups become anonymous."""
    try:
        rosters = _payload(await sleeper_server.call_tool(
            "sleeper_league_rosters", {"league_id": LEAGUE}))
        users = _payload(await sleeper_server.call_tool(
            "sleeper_league_users", {"league_id": LEAGUE}))
    except (MCPToolError, RuntimeError) as e:
        pytest.xfail(f"sleeper unavailable: {e}")
    assert rosters and users
    by_user = {u["user_id"]: u for u in users}
    owned = [r for r in rosters if r.get("owner_id")]
    assert owned, "no roster had an owner"
    assert any(r["owner_id"] in by_user for r in owned), "owner_id does not join to users"
    assert {"roster_id", "players", "settings"} <= set(rosters[0])


@pytest.mark.live
async def test_matchups_pair_by_matchup_id_live(sleeper_server):
    """One row per ROSTER, not per game — rows sharing a matchup_id played each other,
    and there is no home/away to lean on."""
    try:
        rows = _payload(await sleeper_server.call_tool(
            "sleeper_matchups", {"league_id": LEAGUE, "week": 1}))
    except (MCPToolError, RuntimeError) as e:
        pytest.xfail(f"sleeper unavailable: {e}")
    if not rows:
        pytest.skip("no matchups for week 1")
    assert {"roster_id", "matchup_id", "points", "starters"} <= set(rows[0])
    paired = [r for r in rows if r.get("matchup_id") is not None]
    counts = {}
    for r in paired:
        counts[r["matchup_id"]] = counts.get(r["matchup_id"], 0) + 1
    assert any(c == 2 for c in counts.values()), "expected rosters to pair up by matchup_id"


@pytest.mark.live
async def test_draft_picks_carry_player_names_live(sleeper_server):
    """The reason we can skip the 15 MB player file: each pick's metadata names the
    player outright."""
    try:
        drafts = _payload(await sleeper_server.call_tool(
            "sleeper_league_drafts", {"league_id": LEAGUE}))
        if not drafts:
            pytest.skip("league has no drafts")
        picks = _payload(await sleeper_server.call_tool(
            "sleeper_draft_picks", {"draft_id": drafts[0]["draft_id"]}))
    except (MCPToolError, RuntimeError) as e:
        pytest.xfail(f"sleeper unavailable: {e}")
    assert picks
    p = picks[0]
    assert {"pick_no", "round", "player_id"} <= set(p)
    meta = p.get("metadata") or {}
    assert meta.get("first_name") and meta.get("position")


@pytest.mark.live
async def test_playoff_bracket_live(sleeper_server):
    try:
        rows = _payload(await sleeper_server.call_tool(
            "sleeper_playoff_bracket", {"league_id": LEAGUE, "bracket": "winners_bracket"}))
    except (MCPToolError, RuntimeError) as e:
        pytest.xfail(f"sleeper unavailable: {e}")
    if not rows:
        pytest.skip("no bracket for this league")
    # Terse keys: r=round, m=match, t1/t2=roster ids, w=winner.
    assert {"r", "m"} <= set(rows[0])


@pytest.mark.live
async def test_trending_players_live(sleeper_server):
    try:
        rows = _payload(await sleeper_server.call_tool(
            "sleeper_trending_players", {"sport": "nfl", "add_or_drop": "add", "limit": 5}))
    except (MCPToolError, RuntimeError) as e:
        pytest.xfail(f"sleeper unavailable: {e}")
    if not rows:
        pytest.skip("no trending data right now")
    assert len(rows) <= 5
    assert {"player_id", "count"} <= set(rows[0])


@pytest.mark.live
async def test_transactions_live(sleeper_server):
    try:
        rows = _payload(await sleeper_server.call_tool(
            "sleeper_transactions", {"league_id": LEAGUE, "week": 1}))
    except (MCPToolError, RuntimeError) as e:
        pytest.xfail(f"sleeper unavailable: {e}")
    if not rows:
        pytest.skip("no transactions in this league")
    assert {"type", "status", "roster_ids"} <= set(rows[0])
