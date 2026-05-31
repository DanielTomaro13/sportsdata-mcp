"""Live integration tests against AFL public endpoints (aflapi.afl.com.au, no auth).

Marked ``live`` — skipped by default. Run with::

    pytest -m live tests/integration/test_afl_public.py

These hit the real, unauthenticated public API. They are deliberately tolerant of
schedule-dependent emptiness (e.g. live streams) and assert on stable structure only.
"""

from __future__ import annotations

import json

import pytest

from sportsdata_mcp.config import Config
from sportsdata_mcp.server import build_server

pytestmark = pytest.mark.live


@pytest.fixture
async def afl_server():
    mcp, reg = build_server(
        Config(enabled_groups=["afl.public.core", "afl.public.broadcasting", "afl.public.content"])
    )
    try:
        yield mcp
    finally:
        await reg.aclose()


def _structured(result):
    """Pull the JSON payload out of a FastMCP tool-call result."""
    return result.structured_content


async def test_competitions_list(afl_server):
    res = await afl_server.call_tool("afl_competitions_list", {"pageSize": 50})
    data = _structured(res)
    comps = data["competitions"]
    assert isinstance(comps, list) and comps
    afl = next(c for c in comps if c["code"] == "AFL")
    assert afl["id"] == 1
    assert afl["providerId"].startswith("CD_")


async def test_compseason_embeds_rounds(afl_server):
    # 85 == 2026 AFL comp season (per spec example). The payload wraps the season
    # object in a `compSeasons` array; the rounds live inside that object.
    res = await afl_server.call_tool("afl_compseason_get", {"compSeasonId": 85})
    data = _structured(res)
    season = data["compSeasons"][0]
    assert isinstance(season["rounds"], list) and season["rounds"], "season should embed rounds"


async def test_ladder_has_entries(afl_server):
    res = await afl_server.call_tool("afl_ladders_get", {"compSeasonId": 85})
    data = _structured(res)
    ladders = data["ladders"]
    assert ladders, "expected at least one ladder"
    entries = ladders[0]["entries"]
    assert len(entries) >= 10  # 18 AFL teams; tolerate partial-season ordering


async def test_match_flow_list_then_get(afl_server):
    """List matches for the 2026 AFL season, then fetch one by integer id."""
    listing = _structured(
        await afl_server.call_tool("afl_matches_list", {"compSeasonId": 85, "pageSize": 5})
    )
    matches = listing["matches"]
    assert matches, "expected matches in the 2026 AFL season"
    match_id = matches[0]["id"]
    detail = _structured(await afl_server.call_tool("afl_match_get", {"matchId": match_id}))
    one = detail["matches"][0]
    assert one["id"] == match_id
    assert "home" in one and "away" in one


async def test_teams_idmap_reference_resource(afl_server):
    result = await afl_server.read_resource("afl://teams/idmap")
    payload = json.loads(result.contents[0].content)
    ids = payload["idMapResponse"]["ids"]
    assert any(k.startswith("CD_T") for k in ids)


async def test_broadcast_channels_carry_media_types(afl_server):
    res = await afl_server.call_tool("afl_broadcast_channels", {"pageSize": 100})
    data = _structured(res)
    # /broadcasting/channels paginates: {pageInfo, content:[...]}.
    channels = data["content"]
    assert channels, "expected broadcast channels"
    assert "channelTypes" in channels[0]


async def test_content_text_news_index(afl_server):
    res = await afl_server.call_tool(
        "afl_content_text_list",
        {"referenceExpression": "(AFL_COMPETITION:1)", "tagExpression": '("News")', "limit": 5},
    )
    data = _structured(res)
    content = data["content"]
    assert isinstance(content, list)
    if content:
        assert content[0]["type"] == "text"
