"""OpenDota (api.opendota.com) — registration (offline) + live probes.

Dota 2 esports analytics, the catalogue's first esports source. The assertions below
target the two conventions that silently corrupt derived numbers: Radiant/Dire slot
maths, and hero stats that are paired COUNTS rather than win rates.

Run the live tests with::

    pytest -m live tests/integration/test_opendota.py
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml
from fastmcp.exceptions import ToolError as MCPToolError

from sportsdata_mcp.config import Config
from sportsdata_mcp.server import build_server

_GROUPS = ["opendota.reference", "opendota.matches", "opendota.players"]
ACCOUNT_ID = 88367253
MATCH_ID = 8937822821


@pytest.fixture
async def dota_server():
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


def _spec() -> dict:
    path = Path(__file__).resolve().parents[2] / "src/sportsdata_mcp/specs/opendota.yaml"
    return yaml.safe_load(path.read_text())


# ─── offline ────────────────────────────────────────────────────────────


async def test_tools_registered(dota_server):
    names = {t.name for t in await dota_server.list_tools()}
    assert {
        "opendota_heroes", "opendota_hero_stats", "opendota_teams", "opendota_leagues",
        "opendota_pro_matches", "opendota_match", "opendota_public_matches",
        "opendota_player", "opendota_player_matches", "opendota_player_winloss",
        "opendota_player_heroes",
    } <= names


def test_the_4mb_pro_player_list_is_not_exposed():
    """/proPlayers is ~4.4 MB of every registered pro — almost never the answer to a
    question, and enough to blow a model's context if it is."""
    paths = [ep["path"] for ep in _spec()["endpoints"]]
    assert "/proPlayers" not in paths


def test_no_sql_explorer_endpoint():
    """OpenDota's /explorer accepts arbitrary SQL. Handing a model a SQL surface is not
    something a read-only server should do."""
    paths = [ep["path"] for ep in _spec()["endpoints"]]
    assert not any("explorer" in p for p in paths)


# ─── live ───────────────────────────────────────────────────────────────


@pytest.mark.live
async def test_heroes_live(dota_server):
    try:
        heroes = _payload(await dota_server.call_tool("opendota_heroes", {}))
    except (MCPToolError, RuntimeError) as e:
        pytest.xfail(f"opendota unavailable: {e}")
    assert len(heroes) > 100
    assert {"id", "localized_name", "primary_attr", "roles"} <= set(heroes[0])


@pytest.mark.live
async def test_hero_stats_are_paired_counts_not_rates_live(dota_server):
    """There is no win-rate field: it's <bracket>_pick / <bracket>_win pairs. A caller
    who reads a `_win` count as a rate gets a number 4 orders of magnitude wrong."""
    try:
        stats = _payload(await dota_server.call_tool("opendota_hero_stats", {}))
    except (MCPToolError, RuntimeError) as e:
        pytest.xfail(f"opendota unavailable: {e}")
    h = stats[0]
    assert "win_rate" not in h and "winrate" not in h
    assert "pro_pick" in h and "pro_win" in h
    bracket_keys = [k for k in h if k.endswith("_pick") and k[0].isdigit()]
    assert bracket_keys, "expected per-skill-bracket pick counts"
    b = bracket_keys[0][0]
    assert h[f"{b}_win"] <= h[f"{b}_pick"], "wins cannot exceed picks"


@pytest.mark.live
async def test_pro_matches_use_radiant_dire_live(dota_server):
    """Dota has no home/away — the result is `radiant_win`, and player_slot < 128 means
    Radiant. Every derived win rate depends on this."""
    try:
        matches = _payload(await dota_server.call_tool("opendota_pro_matches", {}))
    except (MCPToolError, RuntimeError) as e:
        pytest.xfail(f"opendota unavailable: {e}")
    assert matches
    m = matches[0]
    assert {"match_id", "radiant_name", "dire_name", "radiant_win", "league_name"} <= set(m)
    assert "home" not in m and "away" not in m
    assert isinstance(m["radiant_win"], bool)


@pytest.mark.live
async def test_match_detail_slot_convention_live(dota_server):
    try:
        d = _payload(await dota_server.call_tool("opendota_match", {"match_id": MATCH_ID}))
    except (MCPToolError, RuntimeError) as e:
        pytest.xfail(f"opendota unavailable: {e}")
    players = d["players"]
    assert len(players) == 10, "a Dota match is 5v5"
    radiant = [p for p in players if p["player_slot"] < 128]
    assert len(radiant) == 5, "player_slot < 128 must partition the teams 5/5"
    assert {"hero_id", "kills", "deaths", "assists", "gold_per_min"} <= set(players[0])


@pytest.mark.live
async def test_player_profile_carries_both_id_forms_live(dota_server):
    """account_id (32-bit) is what the API takes; steamid (64-bit) is what a Steam URL
    shows. Both appear on the profile, and confusing them returns an empty result."""
    try:
        d = _payload(await dota_server.call_tool("opendota_player", {"account_id": ACCOUNT_ID}))
    except (MCPToolError, RuntimeError) as e:
        pytest.xfail(f"opendota unavailable: {e}")
    profile = d.get("profile") or {}
    if not profile:
        pytest.skip("profile is private or unavailable")
    assert profile["account_id"] == ACCOUNT_ID
    assert len(str(profile["steamid"])) > len(str(profile["account_id"]))


@pytest.mark.live
async def test_player_winloss_and_matches_live(dota_server):
    try:
        wl = _payload(await dota_server.call_tool(
            "opendota_player_winloss", {"account_id": ACCOUNT_ID}))
        matches = _payload(await dota_server.call_tool(
            "opendota_player_matches", {"account_id": ACCOUNT_ID, "limit": 5}))
    except (MCPToolError, RuntimeError) as e:
        pytest.xfail(f"opendota unavailable: {e}")
    assert set(wl) == {"win", "lose"}
    assert len(matches) <= 5
    if matches:
        assert {"match_id", "hero_id", "player_slot", "radiant_win"} <= set(matches[0])
