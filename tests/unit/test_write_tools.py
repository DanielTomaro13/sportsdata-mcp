"""Write tools must be hard to enable by accident and honest about what they do.

746 of the catalogue's tools are GETs. Yahoo's sanctioned lineup/add-drop/trade calls are
the first that CHANGE something on a user's account, and two defaults were wrong for them
the moment they landed:

  * every tool was annotated `readOnlyHint: true` unconditionally — so the first write
    tool inherited a promise that it changes nothing, which is exactly backwards for the
    one tool where a client should stop and ask;
  * `*` and `all` swept the write group in, so "enable everything" would have quietly
    included "and you may change my team".

Both are now enforced here rather than remembered.
"""

from __future__ import annotations

import pytest

from sportsdata_mcp.config import Config
from sportsdata_mcp.server import build_server
from sportsdata_mcp.spec_loader import expand_wildcard_groups, load_all_specs

SPECS = load_all_specs()
WRITE_GROUPS = sorted({t.group for s in SPECS for t in s.all_tools() if t.group.endswith(".write")})


def test_there_are_write_groups_to_protect():
    """If this fails the rest of the file is vacuously passing."""
    assert WRITE_GROUPS, "no .write groups found — did the naming convention change?"


@pytest.mark.parametrize("selector", ["*", "all", "free", "fantasy", "official-stats"])
def test_no_wildcard_or_preset_enables_a_write_group(selector):
    """The important one. Enabling everything must not mean enabling actions that change
    someone's team."""
    enabled = expand_wildcard_groups([selector], SPECS)
    assert not [g for g in enabled if g.endswith(".write")], (
        f"selector {selector!r} enabled a write group"
    )


def test_a_provider_glob_does_not_enable_writes():
    """`yahoo.*` expresses "I want Yahoo", not "you may change my roster"."""
    enabled = expand_wildcard_groups(["yahoo.*"], SPECS)
    assert "yahoo.write" not in enabled
    assert len(enabled) >= 4, "the read groups should still be there"


def test_the_exact_group_name_does_enable_it():
    """Opt-in has to be possible, or the tools are unreachable."""
    assert expand_wildcard_groups(["yahoo.write"], SPECS) == ["yahoo.write"]


@pytest.mark.anyio
async def test_write_tools_do_not_claim_to_be_read_only():
    """`readOnlyHint` is a promise a client acts on — it may call such a tool without
    asking the user. A write tool claiming it would be actively dangerous."""
    write_names = {t.name for s in SPECS for t in s.all_tools() if t.group.endswith(".write")}
    mcp, reg = build_server(Config(enabled_groups=[*WRITE_GROUPS]))
    try:
        # The meta-tools (list_*, sportsdata_*) are always registered and ARE read-only;
        # only the provider write tools are under test here.
        tools = [t for t in await mcp.list_tools() if t.name in write_names]
        assert tools, "write groups registered no tools"
        for t in tools:
            a = t.annotations
            assert a is not None, t.name
            assert a.readOnlyHint is False, f"{t.name} claims to be read-only"
            assert a.destructiveHint is True, f"{t.name} does not warn it changes state"
    finally:
        await reg.aclose()


@pytest.mark.anyio
async def test_read_tools_still_claim_read_only():
    """The change to method-derived annotations must not have flipped the other 746."""
    mcp, reg = build_server(Config(enabled_groups=["nhl.*", "fpl.*", "yahoo.*"]))
    try:
        for t in await mcp.list_tools():
            if t.name.startswith(("list_", "sportsdata_")):
                continue
            assert t.annotations.readOnlyHint is True, f"{t.name} lost its read-only hint"
    finally:
        await reg.aclose()


def test_every_write_tool_is_a_non_get_method():
    """A `.write` group holding a GET would mean the naming no longer tracks behaviour,
    and the annotation logic keys off the method."""
    for spec in SPECS:
        for ep in spec.endpoints:
            if ep.group.endswith(".write"):
                assert ep.method in {"POST", "PUT", "PATCH", "DELETE"}, f"{ep.name} is {ep.method}"


def test_write_tools_tell_the_caller_to_verify_afterwards():
    """A 200 from a write is not proof the intended change happened. Every write
    description must say to read back, because that is the difference between a failed
    lineup and a silently missed week."""
    for spec in SPECS:
        for ep in spec.endpoints:
            if not ep.group.endswith(".write"):
                continue
            hint = (ep.response_hint or "").lower()
            assert "re-read" in hint or "confirm" in hint or "pending" in hint, (
                f"{ep.name} does not tell the caller to verify the result"
            )
