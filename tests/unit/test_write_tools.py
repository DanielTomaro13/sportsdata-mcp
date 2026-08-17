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

import contextlib

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
            # "verify" belongs here too — the point is that the description tells the
            # caller to CHECK, not that it uses one particular verb.
            assert any(w in hint for w in ("re-read", "confirm", "pending", "verify")), (
                f"{ep.name} does not tell the caller to verify the result"
            )


# ─── retry safety: the bug that makes writes expensive ──────────────────


@pytest.mark.anyio
@pytest.mark.parametrize("status", [500, 502, 503, 504])
async def test_a_post_is_never_replayed_on_a_5xx(status):
    """The engine's retry policy was written when every tool was a GET and retried purely
    on status. A 5xx is AMBIGUOUS — the server may have applied the change and then
    failed to answer — so replaying a POST can apply it twice.

    Measured before the guard: ONE tool call sent a transfer THREE times. In FPL terms
    that is three transfers, extra points hits, and players the owner never chose.
    """
    import httpx

    from sportsdata_mcp.config import Config
    from sportsdata_mcp.http_client import HTTPClient
    from sportsdata_mcp.spec_loader import load_all_specs

    sent = []

    def handler(request):
        sent.append(1)
        return httpx.Response(status, text="server error")

    spec = next(s for s in load_all_specs() if s.provider.id == "fpl")
    c = HTTPClient(spec.provider, Config())
    c._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    c._cache_ttl = 0.0
    try:
        with contextlib.suppress(Exception):
            await c.request(method="POST", base="default", url="/transfers/", json_body={"x": 1}, auth_key="default")
    finally:
        await c.aclose()
    assert len(sent) == 1, f"a transfer POST was sent {len(sent)}x on a {status}"


@pytest.mark.anyio
async def test_a_post_IS_retried_on_429():
    """429 means the request was rejected BEFORE processing, so replaying it is safe —
    and rate limits are exactly when a retry is wanted."""
    import httpx

    from sportsdata_mcp.config import Config
    from sportsdata_mcp.http_client import HTTPClient
    from sportsdata_mcp.spec_loader import load_all_specs

    sent = []

    def handler(request):
        sent.append(1)
        return httpx.Response(429, text="slow down")

    spec = next(s for s in load_all_specs() if s.provider.id == "fpl")
    c = HTTPClient(spec.provider, Config())
    c._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    c._cache_ttl = 0.0
    try:
        with contextlib.suppress(Exception):
            await c.request(method="POST", base="default", url="/transfers/", json_body={"x": 1}, auth_key="default")
    finally:
        await c.aclose()
    assert len(sent) > 1


@pytest.mark.anyio
async def test_reads_still_retry_on_5xx():
    """The guard must not blunt retries for the 800-odd tools that are reads."""
    import httpx

    from sportsdata_mcp.config import Config
    from sportsdata_mcp.http_client import HTTPClient
    from sportsdata_mcp.spec_loader import load_all_specs

    sent = []

    def handler(request):
        sent.append(1)
        return httpx.Response(503, text="down")

    spec = next(s for s in load_all_specs() if s.provider.id == "fpl")
    c = HTTPClient(spec.provider, Config())
    c._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    c._cache_ttl = 0.0
    try:
        with contextlib.suppress(Exception):
            await c.request(method="GET", base="default", url="/bootstrap-static/", auth_key="default")
    finally:
        await c.aclose()
    assert len(sent) > 1


def test_fpl_writes_require_the_csrf_header():
    """Every FPL write needs X-CSRFToken carrying the csrftoken cookie; without it FPL
    returns 403. A write tool that cannot send it is unusable."""
    from sportsdata_mcp.spec_loader import load_all_specs

    spec = next(s for s in load_all_specs() if s.provider.id == "fpl")
    for ep in spec.endpoints:
        if not ep.group.endswith(".write"):
            continue
        headers = [p for p in ep.params if p.in_ == "header"]
        assert any(p.wire_name == "X-CSRFToken" and p.required for p in headers), (
            f"{ep.name} cannot send the CSRF header"
        )
        assert ep.auth == "session", f"{ep.name} must use the authenticated session"


def test_fpl_list_body_params_are_not_typed_as_objects():
    """`object` maps to dict, and picks/transfers are ARRAYS. Typing them dict forces a
    model to wrap the array in an object, which the provider then rejects — the same
    failure already seen live on Entain."""
    from sportsdata_mcp.spec_loader import load_all_specs

    spec = next(s for s in load_all_specs() if s.provider.id == "fpl")
    for ep in spec.endpoints:
        for p in ep.params:
            if p.name in {"picks", "transfers"}:
                assert p.type == "json", f"{ep.name}.{p.name} is {p.type}, should be json"
