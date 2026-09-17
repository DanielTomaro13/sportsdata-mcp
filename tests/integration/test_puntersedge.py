"""PuntersEdge — registration (offline) + live probes of the keyless demo tools.

This provider is a hybrid, and the hybrid is the thing worth testing. Three tools under
`puntersedge.demo` need NO key and return real live data; the other ten read
`PUNTERSEDGE_API_KEY` and refuse without it. So unlike the BYO-key tier, the live probes
here actually run in CI — `api.puntersedge.online` is a plain public HTTPS API with no
geo-block, which is the whole reason this provider earns its place alongside the AU books
it aggregates.

Two properties are easy to break silently and are pinned below:

  * the demo tools must use the `none` auth block, so a configured key is never sent to
    an endpoint that does not want one — and, more importantly, so they keep working for
    the majority who have no key;
  * `free` must keep this provider, because the demo tools are exactly the zero-setup
    promise `free` makes. Flipping `requires_user_key` to true would quietly drop three
    working keyless tools out of the default install.

Run the live probes with::

    pytest -m live tests/integration/test_puntersedge.py
"""

from __future__ import annotations

import json
import os

import pytest
from fastmcp.exceptions import ToolError as MCPToolError

from sportsdata_mcp.config import Config
from sportsdata_mcp.server import build_server
from sportsdata_mcp.spec_loader import expand_wildcard_groups, load_all_specs

PE_GROUPS = ["puntersedge.*"]

DEMO_TOOLS = {
    "puntersedge_demo_racing_next_to_go",
    "puntersedge_demo_best_odds",
    "puntersedge_demo_book_sport",
}
KEYED_TOOLS = {
    "puntersedge_racing_next_to_go",
    "puntersedge_racing_best_odds",
    "puntersedge_racing_events",
    "puntersedge_racing_results",
    "puntersedge_racing_closing_lines",
    "puntersedge_racing_movers",
    "puntersedge_racing_venues",
    "puntersedge_sports",
    "puntersedge_sport_odds",
    "puntersedge_sport_best_odds",
}


@pytest.fixture
async def pe_server():
    mcp, reg = build_server(Config(enabled_groups=PE_GROUPS))
    try:
        yield mcp
    finally:
        await reg.aclose()


@pytest.fixture(scope="module")
def spec():
    return next(s for s in load_all_specs() if s.provider.id == "puntersedge")


def _payload(result):
    if result.structured_content is not None:
        return result.structured_content
    return json.loads(result.content[0].text) if result.content else None


def _body(result):
    """Unwrap FastMCP's `{"result": …}` envelope around a top-level array."""
    data = _payload(result)
    if isinstance(data, dict) and set(data) == {"result"}:
        return data["result"]
    return data


# ─── offline: registration ──────────────────────────────────────────────


async def test_puntersedge_tools_registered(pe_server):
    names = {t.name for t in await pe_server.list_tools()}
    assert DEMO_TOOLS <= names
    assert KEYED_TOOLS <= names


def test_demo_endpoints_never_send_a_key(spec):
    """The demo endpoints are public and must stay callable for someone with no key —
    and must not leak a configured one to an endpoint that does not want it."""
    by_name = {e.name: e for e in spec.endpoints}
    for name in DEMO_TOOLS:
        assert by_name[name].auth == "demo", f"{name} should use the keyless auth block"
    assert spec.provider.auth["demo"].type == "none"
    for name in KEYED_TOOLS:
        assert by_name[name].auth == "default", f"{name} should use the X-API-Key block"


def test_the_key_is_optional_and_named(spec):
    """`optional` is what keeps a missing key from breaking startup for everyone else;
    the env name is what turns the resulting 401 into something a user can act on."""
    auth = spec.provider.auth["default"]
    assert auth.type == "static_header"
    assert auth.header == "X-API-Key"
    assert auth.env == "PUNTERSEDGE_API_KEY"
    assert auth.optional is True


def test_free_keeps_this_provider():
    """The demo tools ARE the zero-setup promise, so `free` must include them. This is
    the ESPN-Fantasy case: the key is an upgrade, not a requirement."""
    specs = load_all_specs()
    free = {g.split(".")[0] for g in expand_wildcard_groups(["free"], specs)}
    assert "puntersedge" in free


def test_only_the_demo_tools_claim_a_verified_shape(spec):
    """We probed the demo endpoints live and could not probe the keyed ones, so the
    caveat has to split per endpoint — flipping the provider flag either way would make
    one half of the catalogue lie about itself."""
    assert spec.provider.shapes_verified is False
    by_name = {e.name: e for e in spec.endpoints}
    for name in DEMO_TOOLS:
        assert by_name[name].shapes_verified is True, name
    for name in KEYED_TOOLS:
        assert by_name[name].shapes_verified is None, f"{name} should inherit the provider flag"


async def test_the_caveat_splits_the_same_way(pe_server):
    """What a model actually reads — the per-endpoint override has to survive into the
    tool description, not just sit in the spec."""
    tools = {t.name: t for t in await pe_server.list_tools()}
    for name in DEMO_TOOLS:
        assert "NOT been verified" not in tools[name].description, name
    for name in KEYED_TOOLS:
        assert "NOT been verified" in tools[name].description, name


# ─── live: the keyless demo tools ───────────────────────────────────────


@pytest.mark.live
async def test_demo_racing_next_to_go_live(pe_server):
    """Real AU/NZ races, no key. Australian racing runs roughly 00:00–14:00 UTC, so the
    race list is legitimately empty overnight — the envelope is the invariant."""
    try:
        res = await pe_server.call_tool("puntersedge_demo_racing_next_to_go", {})
    except (MCPToolError, RuntimeError) as e:
        pytest.xfail(f"api.puntersedge.online unavailable: {e}")
    data = _body(res)
    assert isinstance(data, dict)
    assert data.get("demo") is True
    assert isinstance(data.get("races"), list)
    if not data["races"]:
        pytest.skip("no races currently quoted (outside the AU racing window)")
    race = data["races"][0]
    assert {"race_id", "venue", "race_number", "category", "start_time", "runners"} <= set(race)
    runner = race["runners"][0]
    assert {"name", "number", "bookmakers"} <= set(runner)
    assert {"key", "win_price"} <= set(runner["bookmakers"][0])


@pytest.mark.live
async def test_demo_best_odds_live(pe_server):
    """Best price per selection with the arb flag, no key."""
    try:
        res = await pe_server.call_tool("puntersedge_demo_best_odds", {})
    except (MCPToolError, RuntimeError) as e:
        pytest.xfail(f"api.puntersedge.online unavailable: {e}")
    data = _body(res)
    assert data.get("demo") is True
    assert isinstance(data.get("events"), list)
    if not data["events"]:
        pytest.skip("no upcoming events currently priced")
    event = data["events"][0]
    assert {"home_team", "away_team", "commence_time", "selections", "arb_exists"} <= set(event)
    assert {"name", "best_price", "best_bookmaker"} <= set(event["selections"][0])


@pytest.mark.live
async def test_demo_book_sport_live(pe_server):
    """One book, one sport — and `type` is what says how to read `items`."""
    try:
        res = await pe_server.call_tool(
            "puntersedge_demo_book_sport", {"book": "sportsbet", "sport": "afl"}
        )
    except (MCPToolError, RuntimeError) as e:
        pytest.xfail(f"api.puntersedge.online unavailable: {e}")
    data = _body(res)
    assert data.get("demo") is True
    assert data["type"] in {"sports", "racing"}
    assert isinstance(data.get("items"), list)


@pytest.mark.live
async def test_a_keyed_tool_refuses_actionably_without_a_key(pe_server):
    """A 401 here must name the variable to set AND carry the upstream's own problem+json
    explanation, which tells the user where to get a free key. "HTTP 401" alone would
    send someone hunting for a geo-block that does not exist."""
    if os.environ.get("PUNTERSEDGE_API_KEY"):
        pytest.skip("a key is configured — this asserts the no-key path")
    with pytest.raises(MCPToolError) as ei:
        await pe_server.call_tool("puntersedge_sports", {})
    message = str(ei.value)
    assert "PUNTERSEDGE_API_KEY" in message
    assert "401" in message
