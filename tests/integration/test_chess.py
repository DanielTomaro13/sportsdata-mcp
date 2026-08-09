"""Lichess + Chess.com — registration (offline) + live probes.

Two providers, one domain, tested together because the interesting assertions are
about how they DIFFER: ratings are not comparable across platforms, and only one of
them can serve game history as JSON.

Run the live tests with::

    pytest -m live tests/integration/test_chess.py
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml
from fastmcp.exceptions import ToolError as MCPToolError

from sportsdata_mcp.config import Config
from sportsdata_mcp.server import build_server

_GROUPS = ["lichess.chess", "chesscom.chess"]


@pytest.fixture
async def chess_server():
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


def _spec(name: str) -> dict:
    path = Path(__file__).resolve().parents[2] / f"src/sportsdata_mcp/specs/{name}.yaml"
    return yaml.safe_load(path.read_text())


# ─── offline ────────────────────────────────────────────────────────────


async def test_tools_registered(chess_server):
    names = {t.name for t in await chess_server.list_tools()}
    assert {
        "lichess_user", "lichess_users_status", "lichess_leaderboard",
        "lichess_leaderboards_all", "lichess_daily_puzzle", "lichess_tournaments",
        "chesscom_player", "chesscom_player_stats", "chesscom_leaderboards",
        "chesscom_titled_players", "chesscom_archives", "chesscom_monthly_games",
        "chesscom_club",
    } <= names


def test_no_lichess_ndjson_endpoints_are_modelled():
    """Lichess streams game exports, broadcasts and team members as newline-delimited
    JSON, which this engine cannot decode (verified: /api/broadcast fails with
    'Extra data: line 2'). Adding one would produce a tool that always errors."""
    paths = [ep["path"] for ep in _spec("lichess")["endpoints"]]
    forbidden = ("/games/", "/broadcast", "/team/", "/tournament/")
    bad = [p for p in paths if any(f in p for f in forbidden)]
    assert not bad, f"NDJSON endpoints must not be modelled: {bad}"


def test_chesscom_issues_requests_serially():
    """Chess.com throttles on CONCURRENCY, not on rate — burst 1 is the whole point,
    and widening it produces intermittent 429s that look like random flakiness."""
    defaults = _spec("chesscom")["provider"]["defaults"]
    assert defaults["burst"] == 1, "burst must stay 1: Chess.com throttles parallel requests"


def test_both_chess_providers_identify_themselves():
    for name in ("lichess", "chesscom"):
        ua = _spec(name)["provider"]["default_headers"]["User-Agent"]
        assert "github.com" in ua, f"{name} UA needs a contact URL"


# ─── live: Lichess ──────────────────────────────────────────────────────


@pytest.mark.live
async def test_lichess_user_has_per_perf_ratings_live(chess_server):
    """There is no single 'rating' — it's per time control, and a consumer that looks
    for `rating` at the top level finds nothing."""
    try:
        res = await chess_server.call_tool("lichess_user", {"username": "thibault"})
    except (MCPToolError, RuntimeError) as e:
        pytest.xfail(f"lichess unavailable: {e}")
    d = _payload(res)
    assert "rating" not in d
    perfs = d["perfs"]
    assert any(p in perfs for p in ("blitz", "bullet", "rapid"))
    some = next(p for p in ("blitz", "bullet", "rapid") if p in perfs)
    assert "rating" in perfs[some]


@pytest.mark.live
async def test_lichess_leaderboard_live(chess_server):
    try:
        res = await chess_server.call_tool("lichess_leaderboard", {"count": 5, "perf": "blitz"})
    except (MCPToolError, RuntimeError) as e:
        pytest.xfail(f"lichess unavailable: {e}")
    users = _payload(res)["users"]
    assert 0 < len(users) <= 5
    assert "username" in users[0]


@pytest.mark.live
async def test_lichess_tournaments_are_three_lists_live(chess_server):
    """Not one list — reading the top level as a list gets nothing."""
    try:
        res = await chess_server.call_tool("lichess_tournaments", {})
    except (MCPToolError, RuntimeError) as e:
        pytest.xfail(f"lichess unavailable: {e}")
    d = _payload(res)
    assert {"created", "started", "finished"} <= set(d)


@pytest.mark.live
async def test_lichess_daily_puzzle_live(chess_server):
    try:
        res = await chess_server.call_tool("lichess_daily_puzzle", {})
    except (MCPToolError, RuntimeError) as e:
        pytest.xfail(f"lichess unavailable: {e}")
    d = _payload(res)
    assert {"game", "puzzle"} <= set(d)
    assert d["puzzle"]["solution"]


# ─── live: Chess.com ────────────────────────────────────────────────────


@pytest.mark.live
async def test_chesscom_player_live(chess_server):
    try:
        res = await chess_server.call_tool("chesscom_player", {"username": "hikaru"})
    except (MCPToolError, RuntimeError) as e:
        pytest.xfail(f"chess.com unavailable: {e}")
    d = _payload(res)
    assert d["username"].lower() == "hikaru"
    # Unix seconds, not ISO — pinned because rendering it raw shows a 10-digit number.
    assert isinstance(d["joined"], int) and d["joined"] > 1_000_000_000


@pytest.mark.live
async def test_chesscom_stats_omit_unplayed_formats_live(chess_server):
    """A missing format means 'never played', not 'rating zero'."""
    try:
        res = await chess_server.call_tool("chesscom_player_stats", {"username": "hikaru"})
    except (MCPToolError, RuntimeError) as e:
        pytest.xfail(f"chess.com unavailable: {e}")
    d = _payload(res)
    played = [k for k in ("chess_blitz", "chess_bullet", "chess_rapid", "chess_daily") if k in d]
    assert played
    assert "last" in d[played[0]] and "rating" in d[played[0]]["last"]


@pytest.mark.live
async def test_chesscom_game_history_via_archives_live(chess_server):
    """There is no 'recent games' endpoint: you read the archive list, take the last
    year/month, then fetch it. This pins the two-step chain."""
    try:
        archives = _payload(await chess_server.call_tool(
            "chesscom_archives", {"username": "hikaru"}))["archives"]
        year, month = archives[-1].rsplit("/", 2)[-2:]
        games = _payload(await chess_server.call_tool(
            "chesscom_monthly_games", {"username": "hikaru", "year": year, "month": month}))["games"]
    except (MCPToolError, RuntimeError) as e:
        pytest.xfail(f"chess.com unavailable: {e}")
    assert len(month) == 2, "month must stay zero-padded or the fetch 404s"
    if not games:
        pytest.skip("no games in the latest archive month yet")
    assert {"pgn", "white", "black", "time_class"} <= set(games[0])


@pytest.mark.live
async def test_chesscom_titled_players_are_bare_strings_live(chess_server):
    try:
        res = await chess_server.call_tool("chesscom_titled_players", {"title": "GM"})
    except (MCPToolError, RuntimeError) as e:
        pytest.xfail(f"chess.com unavailable: {e}")
    players = _payload(res)["players"]
    assert players and isinstance(players[0], str), "usernames, not objects"


# ─── live: the cross-platform caveat ────────────────────────────────────


@pytest.mark.live
async def test_the_two_platforms_are_separate_rating_pools_live(chess_server):
    """Same person, both platforms, different numbers. This isn't a bug to reconcile —
    the pools and formulas differ — and the test exists so nobody 'fixes' the docs by
    presenting the two ratings as one."""
    try:
        li = _payload(await chess_server.call_tool("lichess_user", {"username": "hikaru"}))
        cc = _payload(await chess_server.call_tool("chesscom_player_stats", {"username": "hikaru"}))
    except (MCPToolError, RuntimeError) as e:
        pytest.xfail(f"a chess platform is unavailable: {e}")
    li_blitz = (li.get("perfs") or {}).get("blitz", {}).get("rating")
    cc_blitz = ((cc.get("chess_blitz") or {}).get("last") or {}).get("rating")
    if not (li_blitz and cc_blitz):
        pytest.skip("one platform has no blitz rating for this account")
    assert li_blitz != cc_blitz, "identical ratings would suggest one source is being reused"
