"""Every place that answers "will this work with no setup" must agree.

`required_for_access` marks one auth block of a hybrid provider as key-only — PuntersEdge
has a keyless demo group and two keyed groups on the same provider. Four places read
"does this tool need a key": the doctor verdict, the `free` preset, the model-facing
`Auth:` line and the coverage probe. When doctor learned about the block flag and the
other three did not, `free` shipped ten tools that 401 for every user in it, and each one
told the model it "works without a key" — the retry loop `_auth_line` exists to prevent.

So these hold for EVERY spec, not just PuntersEdge: the next hybrid provider is covered
the moment it sets the flag.
"""

from __future__ import annotations

import pytest

from sportsdata_mcp.coverage import _pick_probe
from sportsdata_mcp.registry import _auth_line
from sportsdata_mcp.spec import key_required
from sportsdata_mcp.spec_loader import load_all_specs, resolve_groups

pytestmark = pytest.mark.unit

SPECS = load_all_specs()
GROUPS = sorted({t.group for s in SPECS for t in s.all_tools()})
FREE = set(resolve_groups(["free"], GROUPS, SPECS))


def _auth(tool) -> str:
    return getattr(tool, "auth", "default")


def test_no_tool_that_needs_a_key_says_it_works_without_one():
    """THE model-facing half. An agent told a tool works keyless will call it, get a
    401, and retry or blame the user — instead of asking for the key it actually needs."""
    lying = [
        t.name
        for s in SPECS
        for t in s.all_tools()
        if key_required(s.provider, _auth(t)) and "works without a key" in _auth_line(s.provider, _auth(t))
    ]
    assert not lying, f"these need a key but tell the model they do not: {lying}"


def test_free_contains_no_group_where_every_tool_needs_a_key():
    """`free` is the zero-setup promise. A group made entirely of key-only tools can
    never answer anything for someone on it."""
    dead = [
        g
        for g in FREE
        if (tools := [(s, t) for s in SPECS for t in s.all_tools() if t.group == g])
        and all(key_required(s.provider, _auth(t)) for s, t in tools)
    ]
    assert not dead, f"`free` includes groups that cannot work without a key: {sorted(dead)}"


def test_a_hybrid_keeps_its_keyless_half_in_free():
    """The reason the flag is per block rather than `requires_user_key`: the provider
    flag would have dropped the demo tools from `free` along with the keyed ones."""
    pe = {g for g in FREE if g.startswith("puntersedge.")}
    assert pe == {"puntersedge.demo"}, f"expected only the demo group in free, got {sorted(pe)}"


def test_a_hybrids_tools_are_labelled_by_their_own_block():
    pe = next(s for s in SPECS if s.provider.id == "puntersedge")
    by_name = {e.name: e for e in pe.endpoints}
    demo = _auth_line(pe.provider, by_name["puntersedge_demo_best_odds"].auth)
    keyed = _auth_line(pe.provider, by_name["puntersedge_racing_next_to_go"].auth)
    assert "works without a key" in demo
    assert "needs your own key in PUNTERSEDGE_API_KEY" in keyed


def test_coverage_probes_a_keyless_endpoint_when_a_provider_has_one():
    """A keyed probe 401s without a key and reports a healthy provider as down. Before
    this, PuntersEdge only reported correctly because a demo endpoint is listed first —
    reorder the spec and it would have gone red."""
    for s in SPECS:
        if s.provider.requires_user_key:
            continue  # coverage reports these as needs_key without probing
        ep, _ = _pick_probe(s)
        has_keyless = any(not key_required(s.provider, e.auth) for e in s.endpoints if e.method == "GET")
        if ep is not None and has_keyless:
            assert not key_required(s.provider, ep.auth), (
                f"{s.provider.id}: coverage would probe {ep.name}, which needs a key, "
                "although the provider has endpoints that do not"
            )
