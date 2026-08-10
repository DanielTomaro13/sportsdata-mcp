"""The `shapes_verified` flag.

Providers whose data needs a key we don't hold have response_hints derived from the
VENDOR'S DOCS rather than a live probe. That distinction matters: while building this
catalogue, roughly a third of the shapes assumed without probing turned out wrong —
nested where they looked flat, grouped where they looked like a list — and those errors
are the silent kind that produce confident wrong answers rather than an exception.

So the flag is not a comment: it is surfaced in every affected tool's description, so
the model knows to read what it actually received.
"""

from __future__ import annotations

from sportsdata_mcp.config import Config
from sportsdata_mcp.server import build_server
from sportsdata_mcp.spec_loader import load_all_specs


def test_unverified_providers_are_explicitly_flagged():
    """Anything not probed live must say so in the spec, not just in prose."""
    unverified = {s.provider.id for s in load_all_specs() if not s.provider.shapes_verified}
    # Every keyless provider WAS probed; only BYO-key ones may be unverified.
    for spec in load_all_specs():
        if spec.provider.shapes_verified:
            continue
        # `username_env` is the HTTP Basic case (MySportsFeeds). Checking only `env`
        # made this fire on it — correctly reporting that the RULE had a blind spot,
        # not that the provider was wrong. The same blind spot existed in the engine's
        # "which key is missing" message, and this is what surfaced it.
        needs_key = any(
            getattr(a, attr, None)
            for a in spec.provider.auth.values()
            for attr in ("env", "username_env")
        )
        assert needs_key, (
            f"{spec.provider.id} is flagged unverified but needs no key — "
            "if we can call it, we should have probed it"
        )
    assert unverified, "expected at least one BYO-key provider"


async def test_the_caveat_reaches_the_tool_description():
    """A model reading the tool description must learn the shape is approximate."""
    specs = load_all_specs()
    unverified = [s for s in specs if not s.provider.shapes_verified]
    assert unverified
    spec = unverified[0]
    group = next(iter({t.group for t in spec.all_tools()}))
    mcp, reg = build_server(Config(enabled_groups=[group]))
    try:
        tools = {t.name: t for t in await mcp.list_tools()}
        sample = next(t for name, t in tools.items() if name.startswith(spec.provider.id))
        assert "NOT been verified" in sample.description
        assert "approximate" in sample.description
    finally:
        await reg.aclose()


async def test_verified_providers_carry_no_caveat():
    """The note must not leak onto providers we DID probe — it would undersell them."""
    mcp, reg = build_server(Config(enabled_groups=["nhl.stats"]))
    try:
        tools = {t.name: t for t in await mcp.list_tools()}
        assert "NOT been verified" not in tools["nhl_standings"].description
    finally:
        await reg.aclose()
