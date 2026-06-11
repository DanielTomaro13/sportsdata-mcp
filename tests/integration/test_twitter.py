"""X (Twitter) — registration checks (offline) + live probes (need X_BEARER_TOKEN).

The X API has no anonymous tier, so live tests skip without a token (same
pattern as Data Golf). Run with::

    X_BEARER_TOKEN=... pytest -m live tests/integration/test_twitter.py
"""

from __future__ import annotations

import json
import os

import pytest
from fastmcp.exceptions import ToolError as MCPToolError

from sportsdata_mcp.config import Config
from sportsdata_mcp.server import build_server

TWITTER_GROUPS = ["twitter.tweets", "twitter.users", "twitter.trends"]
_NO_KEY = not os.environ.get("X_BEARER_TOKEN")


@pytest.fixture
async def twitter_server():
    mcp, reg = build_server(Config(enabled_groups=TWITTER_GROUPS))
    try:
        yield mcp
    finally:
        await reg.aclose()


def _payload(result):
    if result.structured_content is not None:
        return result.structured_content
    return json.loads(result.content[0].text)


# ─── offline: registration ──────────────────────────────────────────────


async def test_twitter_tools_registered(twitter_server):
    names = {t.name for t in await twitter_server.list_tools()}
    assert {
        "twitter_search_recent",
        "twitter_tweet_counts",
        "twitter_tweets",
        "twitter_tweet",
        "twitter_quote_tweets",
        "twitter_retweeted_by",
        "twitter_liking_users",
    } <= names
    assert {
        "twitter_user_by_username",
        "twitter_users_by_usernames",
        "twitter_user",
        "twitter_users",
        "twitter_user_tweets",
        "twitter_user_mentions",
    } <= names
    assert {"twitter_trends", "twitter_usage"} <= names


async def test_missing_token_is_actionable(twitter_server):
    """Without X_BEARER_TOKEN the error must name the env var, not be a 401 mystery."""
    if not _NO_KEY:
        pytest.skip("X_BEARER_TOKEN is set")
    with pytest.raises(MCPToolError, match="X_BEARER_TOKEN"):
        await twitter_server.call_tool("twitter_trends", {"woeid": 1})


# ─── live: api.x.com (needs X_BEARER_TOKEN) ─────────────────────────────


@pytest.mark.live
@pytest.mark.skipif(_NO_KEY, reason="X_BEARER_TOKEN not set")
async def test_user_lookup_live(twitter_server):
    try:
        res = await twitter_server.call_tool("twitter_user_by_username", {"username": "NBA"})
    except (MCPToolError, RuntimeError) as e:
        pytest.xfail(f"api.x.com unavailable: {e}")
    data = _payload(res)["data"]
    assert data["username"].lower() == "nba" and "public_metrics" in data


@pytest.mark.live
@pytest.mark.skipif(_NO_KEY, reason="X_BEARER_TOKEN not set")
async def test_search_recent_live(twitter_server):
    try:
        res = await twitter_server.call_tool(
            "twitter_search_recent", {"query": "NBA lang:en -is:retweet", "max_results": 10}
        )
    except (MCPToolError, RuntimeError) as e:
        pytest.xfail(f"api.x.com unavailable (or tier-capped): {e}")
    data = _payload(res)
    assert "data" in data or data.get("meta", {}).get("result_count") == 0
