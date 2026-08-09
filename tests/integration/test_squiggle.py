"""Squiggle (api.squiggle.com.au) — registration (offline) + live probes.

AFL forecasting models rather than raw results: 41 independent tipsters, what each
predicted, and how it scored. The offline tests pin the etiquette this provider
depends on — Squiggle is one volunteer's server and asks callers to identify
themselves, so an honest User-Agent and a gentle rate limit are correctness, not
politeness.

Run the live tests with::

    pytest -m live tests/integration/test_squiggle.py
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml
from fastmcp.exceptions import ToolError as MCPToolError

from sportsdata_mcp.config import Config
from sportsdata_mcp.server import build_server

SEASON = 2026
ROUND = 1


@pytest.fixture
async def squiggle_server():
    mcp, reg = build_server(Config(enabled_groups=["squiggle.afl"]))
    try:
        yield mcp
    finally:
        await reg.aclose()


def _payload(result):
    if result.structured_content is not None:
        return result.structured_content
    return json.loads(result.content[0].text)


def _spec() -> dict:
    path = Path(__file__).resolve().parents[2] / "src/sportsdata_mcp/specs/squiggle.yaml"
    return yaml.safe_load(path.read_text())


# ─── offline ────────────────────────────────────────────────────────────


async def test_tools_registered(squiggle_server):
    names = {t.name for t in await squiggle_server.list_tools()}
    assert {
        "squiggle_teams", "squiggle_games", "squiggle_sources",
        "squiggle_tips", "squiggle_standings", "squiggle_ladder",
    } <= names


def test_user_agent_identifies_us_with_a_contact():
    """Squiggle asks callers to identify themselves and has blocked anonymous
    scrapers. Swapping in a browser string would be impolite AND get us blocked."""
    ua = _spec()["provider"]["default_headers"]["User-Agent"]
    assert "sportsdata-mcp" in ua
    assert "github.com" in ua, "the UA must carry a contact URL"
    assert "Mozilla" not in ua, "never impersonate a browser against a volunteer's server"


def test_rate_limit_is_gentle():
    """One person's host — a burst here is rude and gets the provider revoked."""
    assert _spec()["provider"]["defaults"]["rate_limit_rps"] <= 3


# ─── live ───────────────────────────────────────────────────────────────


@pytest.mark.live
async def test_teams_live(squiggle_server):
    try:
        res = await squiggle_server.call_tool("squiggle_teams", {})
    except (MCPToolError, RuntimeError) as e:
        pytest.xfail(f"squiggle unavailable: {e}")
    teams = _payload(res)["teams"]
    assert len(teams) >= 18
    assert {"id", "name", "abbrev"} <= set(teams[0])


@pytest.mark.live
async def test_sources_live(squiggle_server):
    """The model list is what makes this provider interesting — if it collapses to a
    couple of entries, the aggregation has broken upstream."""
    try:
        res = await squiggle_server.call_tool("squiggle_sources", {})
    except (MCPToolError, RuntimeError) as e:
        pytest.xfail(f"squiggle unavailable: {e}")
    sources = _payload(res)["sources"]
    assert len(sources) > 5, "expected a field of models, not a handful"
    assert {"id", "name"} <= set(sources[0])


@pytest.mark.live
async def test_games_live(squiggle_server):
    try:
        res = await squiggle_server.call_tool("squiggle_games", {"year": SEASON, "round": ROUND})
    except (MCPToolError, RuntimeError) as e:
        pytest.xfail(f"squiggle unavailable: {e}")
    games = _payload(res)["games"]
    if not games:
        pytest.skip(f"no games published for {SEASON} round {ROUND}")
    g = games[0]
    assert {"id", "hteam", "ateam", "date", "round"} <= set(g)


@pytest.mark.live
async def test_tips_carry_model_confidence_live(squiggle_server):
    """A tip without confidence/margin is just a pick — the numbers are the point."""
    try:
        res = await squiggle_server.call_tool("squiggle_tips", {"year": SEASON, "round": ROUND})
    except (MCPToolError, RuntimeError) as e:
        pytest.xfail(f"squiggle unavailable: {e}")
    tips = _payload(res)["tips"]
    if not tips:
        pytest.skip("no tips published for this round yet")
    t = tips[0]
    assert {"gameid", "source", "sourceid", "tip", "confidence", "margin"} <= set(t)
    assert 0 <= float(t["confidence"]) <= 100, "confidence is a percentage"


@pytest.mark.live
async def test_source_filter_narrows_tips_live(squiggle_server):
    """Without a source filter you get every model stacked together — the filter is
    how a caller gets one opinion instead of 41."""
    try:
        all_tips = _payload(await squiggle_server.call_tool(
            "squiggle_tips", {"year": SEASON, "round": ROUND}))["tips"]
        one = _payload(await squiggle_server.call_tool(
            "squiggle_tips", {"year": SEASON, "round": ROUND, "source": 1}))["tips"]
    except (MCPToolError, RuntimeError) as e:
        pytest.xfail(f"squiggle unavailable: {e}")
    if not all_tips or not one:
        pytest.skip("no tips published for this round yet")
    assert len(one) < len(all_tips)
    assert {t["sourceid"] for t in one} == {1}


@pytest.mark.live
async def test_standings_are_actual_results_live(squiggle_server):
    try:
        res = await squiggle_server.call_tool("squiggle_standings", {"year": SEASON})
    except (MCPToolError, RuntimeError) as e:
        pytest.xfail(f"squiggle unavailable: {e}")
    rows = _payload(res)["standings"]
    if not rows:
        pytest.skip("season not started")
    r = rows[0]
    assert {"rank", "name", "wins", "losses", "pts", "percentage"} <= set(r)
    assert r["rank"] == 1


@pytest.mark.live
async def test_projected_ladder_carries_simulations_live(squiggle_server):
    """`swarms` is the simulated finishing-position distribution — the thing that makes
    the projected ladder more than a guess, and the field most likely to be dropped."""
    try:
        res = await squiggle_server.call_tool(
            "squiggle_ladder", {"year": SEASON, "round": ROUND, "source": 1})
    except (MCPToolError, RuntimeError) as e:
        pytest.xfail(f"squiggle unavailable: {e}")
    rows = _payload(res)["ladder"]
    if not rows:
        pytest.skip("no projection published for this round")
    assert {"team", "teamid", "rank", "mean_rank", "source"} <= set(rows[0])
    assert isinstance(rows[0].get("swarms"), list)
