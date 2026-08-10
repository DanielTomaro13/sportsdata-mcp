"""The BYO-key tier: registration (offline) + keyless-refusal probes (live).

We hold no key for any of these providers, so the usual contract test — freeze a real
response and fail if its shape moves — is not available. What CAN be tested, and is
worth testing, is everything either side of the key:

  * the specs register, and every tool carries the "shape unverified" caveat so a model
    is told not to trust the documented nesting too hard;
  * `free` never includes them, because `free` is a promise of zero setup;
  * the hosts exist, the paths exist, and a keyless call fails LOUDLY rather than
    returning something a model would read as data.

That last point is the one with teeth. Two of these providers answer a keyless request
with HTTP 200 and an error body:

    api-tennis   200  {"error":"1", …"The field is mandatory"}
    cricketdata  200  {"status":"failure","reason":"Invalid API Key"}

Left alone, the engine would decode that and hand it over as a result. The live tests
below assert the ToolError that `error_signals` produces instead.

Run the live probes with::

    pytest -m live tests/integration/test_byo_key_providers.py
"""

from __future__ import annotations

import os

import pytest
from fastmcp.exceptions import ToolError as MCPToolError

from sportsdata_mcp.config import Config
from sportsdata_mcp.server import build_server
from sportsdata_mcp.spec_loader import load_all_specs

BYO = ["theoddsapi", "pandascore", "cfbd", "footballdataorg", "apitennis", "cricketdata"]

_GROUPS = [f"{p}.*" for p in BYO]


@pytest.fixture
async def server():
    mcp, reg = build_server(Config(enabled_groups=_GROUPS))
    try:
        yield mcp
    finally:
        await reg.aclose()


# ─── offline: the contract around the key ───────────────────────────────


async def test_every_byo_provider_registers_tools(server):
    names = {t.name for t in await server.list_tools()}
    for pid in BYO:
        assert any(n.startswith(f"{pid}_") for n in names), f"{pid} registered no tools"


async def test_tools_warn_that_shapes_are_unverified(server):
    """A model that trusts an invented nesting will write confidently wrong code. The
    caveat is the only honest signal we can give when we cannot probe."""
    for tool in await server.list_tools():
        if tool.name.split("_")[0] in BYO:
            assert "has NOT been verified" in tool.description, tool.name


def test_all_are_flagged_and_none_leak_into_free():
    specs = {s.provider.id: s.provider for s in load_all_specs()}
    for pid in BYO:
        assert specs[pid].requires_user_key is True, pid
        assert specs[pid].shapes_verified is False, pid


def test_each_declares_the_env_var_it_needs():
    """"Set a key" is useless advice without the variable's name; the error messages are
    built from these, so an unset `env` would produce an unactionable failure."""
    specs = {s.provider.id: s.provider for s in load_all_specs()}
    for pid in BYO:
        envs = [getattr(a, "env", None) for a in specs[pid].auth.values()]
        assert any(envs), f"{pid} declares no env var to read its key from"


# ─── live: what a keyless call actually does ────────────────────────────


@pytest.mark.live
@pytest.mark.skipif(bool(os.environ.get("API_TENNIS_KEY")), reason="a key is set — this probes the keyless path")
async def test_apitennis_keyless_raises_instead_of_returning_the_error_body(server):
    """VERIFIED live 2026-08-10: HTTP 200 + {"error":"1", …}. Must surface as an error."""
    with pytest.raises(MCPToolError) as e:
        await server.call_tool("apitennis_events", {})
    msg = str(e.value)
    assert "API_TENNIS_KEY" in msg or "error body" in msg


@pytest.mark.live
@pytest.mark.skipif(bool(os.environ.get("CRICKETDATA_API_KEY")), reason="a key is set — this probes the keyless path")
async def test_cricketdata_keyless_raises_instead_of_returning_the_failure_object(server):
    """VERIFIED live 2026-08-10: HTTP 200 + {"status":"failure","reason":"Invalid API Key"}."""
    with pytest.raises(MCPToolError) as e:
        await server.call_tool("cricketdata_current_matches", {})
    assert "CRICKETDATA_API_KEY" in str(e.value) or "Invalid API Key" in str(e.value)


@pytest.mark.live
@pytest.mark.skipif(bool(os.environ.get("THE_ODDS_API_KEY")), reason="a key is set")
async def test_theoddsapi_keyless_gives_a_clean_401(server):
    """This one behaves properly: 401 {"message":"API key is missing"}."""
    with pytest.raises(MCPToolError):
        await server.call_tool("theoddsapi_sports", {})


@pytest.mark.live
@pytest.mark.skipif(bool(os.environ.get("CFBD_API_KEY")), reason="a key is set")
async def test_cfbd_keyless_gives_a_clean_401(server):
    with pytest.raises(MCPToolError):
        await server.call_tool("cfbd_teams", {})


@pytest.mark.live
async def test_footballdataorg_open_endpoints_still_work_without_a_key(server):
    """Not everything behind a BYO flag is locked: three football-data.org endpoints are
    open, and were probed live. This is why the provider is `optional` rather than hard
    -required — dropping it entirely would lose 189 competitions of free reference data.
    """
    res = await server.call_tool("footballdataorg_competitions", {})
    assert res is not None
