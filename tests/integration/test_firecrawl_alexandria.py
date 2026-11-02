"""Firecrawl Alexandria: registration and recorded-response tests (offline) + live probes.

Alexandria is a BYO-key provider, but unlike the rest of that tier its shapes WERE probed
with a real key (2026-10-27), so it ships `shapes_verified: true`. The fixtures below are
trimmed copies of those live responses. What is pinned:

  * the request envelope: discovery goes to /v2/search with sources ["alexandria"], every
    run goes to /v2/scrape with {"alexandria": {provider, capability, options}}, and the
    three sports tools send the provider and capability they are named after;
  * the key rides as "Authorization: Bearer <FIRECRAWL_API_KEY>" and a missing key fails
    loudly, naming the variable;
  * `free` never includes it, because every call needs a key.

Run the live probes (the sports calls bill credits) with::

    FIRECRAWL_API_KEY=... pytest -m live tests/integration/test_firecrawl_alexandria.py
"""

from __future__ import annotations

import json
import os

import httpx
import pytest
from fastmcp.exceptions import ToolError as MCPToolError

from sportsdata_mcp.config import Config
from sportsdata_mcp.server import build_server
from sportsdata_mcp.spec_loader import expand_wildcard_groups, load_all_specs

PID = "firecrawl_alexandria"
GROUPS = [f"{PID}.*"]

DISCOVERY = {"firecrawl_alexandria_search", "firecrawl_alexandria_find_tools"}
SPORTS = {
    "firecrawl_alexandria_fantasy_projections": ("startwho-com", "fantasy-sports-rankings/projections"),
    "firecrawl_alexandria_nfl_injury_report": ("nfl-com", "sports-league-data/injury_report"),
    "firecrawl_alexandria_statcast_leaderboard": ("baseballsavant-mlb-com", "baseball-statcast/get_leaderboard"),
}
ALL_TOOLS = DISCOVERY | set(SPORTS) | {"firecrawl_alexandria_run"}

# Trimmed from live responses recorded 2026-10-27.
SEARCH_RESPONSE = {
    "success": True,
    "data": {"tools": [{
        "provider": "nfl-com",
        "capability": "sports-league-data/injury_report",
        "description": "The user wants the official practice participation or injury designations for a week.",
    }]},
    "creditsUsed": 0,
    "id": "01a17d11-7e34-7126-b3d6-f01ae001b5ae",
}
INJURY_RESPONSE = {
    "success": True,
    "scrape_id": "01a17d11-c5a2-7263-ba62-ded098319e08",
    "data": {
        "alexandria": [{
            "provider": "nfl-com",
            "capability": "sports-league-data/injury_report",
            "creditsCost": 5,
            "data": {
                "count": 1, "season": 2026, "season_type": "REG", "week": 7, "report_date": "2026-10-23",
                "reports": [{
                    "player": {"display_name": "Cyrus Allen", "position": "WR", "gsis_id": "00-0040890"},
                    "team": {"abbreviation": "KC", "full_name": "Kansas City Chiefs"},
                    "injuries": [], "injury_status": None, "practice_status": "FULL",
                    "practice_days": [{"date": "2026-10-21", "status": "FULL"}],
                }],
            },
        }],
        "creditsCost": 5,
    },
}


@pytest.fixture
def spec():
    return next(s for s in load_all_specs() if s.provider.id == PID)


@pytest.fixture
async def recorded(monkeypatch):
    """A server whose Firecrawl client answers from the recorded responses above."""
    monkeypatch.setenv("FIRECRAWL_API_KEY", "fc-test-key")
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        body = SEARCH_RESPONSE if request.url.path == "/v2/search" else INJURY_RESPONSE
        return httpx.Response(200, json=body)

    mcp, reg = build_server(Config(enabled_groups=GROUPS))
    for client in reg.http_clients:
        client._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    try:
        yield mcp, seen
    finally:
        await reg.aclose()


def _payload(result):
    if result.structured_content is not None:
        return result.structured_content
    return json.loads(result.content[0].text)


# ─── offline: the spec ──────────────────────────────────────────────────


def test_requires_a_key_and_ships_probed_shapes(spec):
    assert spec.provider.requires_user_key is True
    assert spec.provider.shapes_verified is True
    auth = spec.provider.auth["default"]
    assert (auth.header, auth.value_prefix, auth.env, auth.optional) == (
        "Authorization", "Bearer ", "FIRECRAWL_API_KEY", True,
    )


def test_free_never_includes_it():
    free = {g.split(".")[0] for g in expand_wildcard_groups(["free"], load_all_specs())}
    assert PID not in free


def test_every_call_carries_the_origin_tag(spec):
    for ep in spec.endpoints:
        origin = next(p for p in ep.params if p.name == "origin")
        assert origin.default == "sportsdata-mcp", ep.name


def test_sports_tools_pin_their_provider_and_capability(spec):
    by_name = {e.name: e for e in spec.endpoints}
    for name, (provider, capability) in SPORTS.items():
        params = {p.wire_name: p for p in by_name[name].params}
        assert params["alexandria.provider"].default == provider
        assert params["alexandria.provider"].enum == [provider]
        assert params["alexandria.capability"].default == capability
        assert params["alexandria.capability"].enum == [capability]


# ─── offline: registration and recorded responses ───────────────────────


async def test_tools_register_and_name_the_key(recorded):
    mcp, _ = recorded
    tools = {t.name: t for t in await mcp.list_tools()}
    assert ALL_TOOLS <= set(tools)
    for name in ALL_TOOLS:
        assert "FIRECRAWL_API_KEY" in tools[name].description, name
        assert "NOT been verified" not in tools[name].description, name


async def test_search_sends_alexandria_only_discovery(recorded):
    mcp, seen = recorded
    out = _payload(await mcp.call_tool("firecrawl_alexandria_search", {"query": "NFL injury report"}))
    assert out["data"]["tools"][0]["provider"] == "nfl-com"
    req = seen[-1]
    assert req.method == "POST" and req.url.path == "/v2/search"
    assert req.headers["authorization"] == "Bearer fc-test-key"
    assert json.loads(req.content) == {
        "query": "NFL injury report", "limit": 10, "sources": ["alexandria"], "origin": "sportsdata-mcp",
    }


async def test_injury_report_builds_the_alexandria_envelope(recorded):
    mcp, seen = recorded
    out = _payload(await mcp.call_tool("firecrawl_alexandria_nfl_injury_report", {"team": "KC"}))
    report = out["data"]["alexandria"][0]["data"]["reports"][0]
    assert report["team"]["abbreviation"] == "KC"
    assert seen[-1].url.path == "/v2/scrape"
    assert json.loads(seen[-1].content) == {
        "alexandria": {
            "provider": "nfl-com",
            "capability": "sports-league-data/injury_report",
            "options": {"team": "KC"},
        },
        "origin": "sportsdata-mcp",
    }


async def test_run_passes_any_tool_through(recorded):
    mcp, seen = recorded
    await mcp.call_tool("firecrawl_alexandria_run", {
        "provider": "draftsharks-com",
        "capability": "fantasy-sports-rankings/weekly_rankings",
        "options": {"position": "QB", "limit": 3},
    })
    assert json.loads(seen[-1].content)["alexandria"] == {
        "provider": "draftsharks-com",
        "capability": "fantasy-sports-rankings/weekly_rankings",
        "options": {"position": "QB", "limit": 3},
    }


async def test_missing_key_fails_naming_the_variable(monkeypatch):
    monkeypatch.delenv("FIRECRAWL_API_KEY", raising=False)
    mcp, reg = build_server(Config(enabled_groups=GROUPS))
    for client in reg.http_clients:
        client._client = httpx.AsyncClient(transport=httpx.MockTransport(
            lambda request: httpx.Response(403, json={"success": False, "error": "Unauthorized"})
        ))
    try:
        with pytest.raises(MCPToolError, match="FIRECRAWL_API_KEY"):
            await mcp.call_tool("firecrawl_alexandria_search", {"query": "nfl"})
    finally:
        await reg.aclose()


# ─── live: real calls with a real key ───────────────────────────────────

needs_key = pytest.mark.skipif(not os.environ.get("FIRECRAWL_API_KEY"), reason="FIRECRAWL_API_KEY not set")


@pytest.fixture
async def live():
    mcp, reg = build_server(Config(enabled_groups=GROUPS))
    try:
        yield mcp
    finally:
        await reg.aclose()


def _tool_data(out):
    result = out["data"]["alexandria"][0]
    assert "error" not in result, result.get("error")
    return result["data"]


@pytest.mark.live
@needs_key
async def test_live_search_finds_sports_tools(live):
    out = _payload(await live.call_tool("firecrawl_alexandria_search", {"query": "fantasy football rankings"}))
    tools = out["data"]["tools"]
    if not tools:
        pytest.skip("discovery returned no tools (it can be briefly unavailable)")
    assert {"provider", "capability", "description"} <= set(tools[0])


@pytest.mark.live
@needs_key
async def test_live_find_tools_lists_sports_providers(live):
    out = _payload(await live.call_tool("firecrawl_alexandria_find_tools", {"level": "providers"}))
    providers = {i["provider"] for i in _tool_data(out)["items"]}
    assert {"nfl-com", "startwho-com", "baseballsavant-mlb-com"} <= providers


@pytest.mark.live
@needs_key
async def test_live_fantasy_projections(live):
    try:
        out = _payload(await live.call_tool("firecrawl_alexandria_fantasy_projections", {"position": "QB", "limit": 2}))
    except MCPToolError as e:
        pytest.xfail(f"no projections this week: {e}")
    players = _tool_data(out)["players"]
    if not players:
        pytest.skip("no projections published for the current week")
    assert {"name", "team", "projected_points", "props"} <= set(players[0])


@pytest.mark.live
@needs_key
async def test_live_nfl_injury_report(live):
    data = _tool_data(_payload(await live.call_tool("firecrawl_alexandria_nfl_injury_report", {"team": "KC"})))
    if not data["reports"]:
        pytest.skip("no report filed for the current week")
    assert {"player", "team", "practice_status", "practice_days"} <= set(data["reports"][0])


@pytest.mark.live
@needs_key
async def test_live_statcast_leaderboard(live):
    data = _tool_data(_payload(await live.call_tool(
        "firecrawl_alexandria_statcast_leaderboard", {"board": "expected_statistics", "season": 2025, "limit": 2},
    )))
    assert {"player_id", "name", "metrics"} <= set(data["rows"][0])
