"""WMCTok anonymous-token flow: mint, cache, invalidation, single-flight."""

from __future__ import annotations

import asyncio

import httpx
import pytest

from sportsdata_mcp.auth.afl import AFLTokenProvider
from sportsdata_mcp.config import Config
from sportsdata_mcp.http_client import HTTPClient
from sportsdata_mcp.spec import AuthAFLWMCTok, AuthNone, Provider

MINT_URL = "https://api.afl.com.au/cfs/afl/WMCTok"


def _spec() -> AuthAFLWMCTok:
    return AuthAFLWMCTok(
        type="afl_wmctok",
        mint_url=MINT_URL,
        mint_headers={"Origin": "https://www.afl.com.au"},
        header="x-media-mis-token",
    )


def _async_client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


async def test_mint_then_cache_hit():
    """First get() mints; second reuses the cached token (one POST total)."""
    calls = {"mint": 0}

    def handler(req: httpx.Request) -> httpx.Response:
        assert req.url == MINT_URL
        assert req.method == "POST"
        calls["mint"] += 1
        return httpx.Response(200, json={"token": "abc123"})

    async with _async_client(handler) as client:
        ap = AFLTokenProvider(_spec(), client)
        name, value = await ap.get()
        assert (name, value) == ("x-media-mis-token", "abc123")
        await ap.get()
        assert calls["mint"] == 1


async def test_invalidate_forces_remint():
    tokens = iter(["tok-1", "tok-2"])

    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"token": next(tokens)})

    async with _async_client(handler) as client:
        ap = AFLTokenProvider(_spec(), client)
        _, first = await ap.get()
        ap.invalidate()
        _, second = await ap.get()
        assert first == "tok-1"
        assert second == "tok-2"


async def test_single_flight_under_contention():
    """Concurrent first-time gets mint exactly once (async lock single-flight)."""
    calls = {"mint": 0}

    async def handler(req: httpx.Request) -> httpx.Response:
        calls["mint"] += 1
        await asyncio.sleep(0.01)  # widen the race window
        return httpx.Response(200, json={"token": "shared"})

    async with _async_client(handler) as client:
        ap = AFLTokenProvider(_spec(), client)
        results = await asyncio.gather(*(ap.get() for _ in range(8)))
        assert calls["mint"] == 1
        assert {v for _, v in results} == {"shared"}


@pytest.mark.parametrize(
    "payload",
    [
        {"token": "t"},
        {"mediaAuthToken": "t"},
        {"data": {"token": "t"}},
    ],
)
async def test_token_extracted_from_known_envelopes(payload):
    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=payload)

    async with _async_client(handler) as client:
        ap = AFLTokenProvider(_spec(), client)
        _, value = await ap.get()
        assert value == "t"


async def test_missing_token_raises():
    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"message": "Missing Authentication Token"})

    async with _async_client(handler) as client:
        ap = AFLTokenProvider(_spec(), client)
        with pytest.raises(RuntimeError, match="did not contain a token"):
            await ap.get()


# ─── HTTPClient end-to-end: token injection + 401 retry ────────────────────


def _premium_provider() -> Provider:
    return Provider(
        id="afl",
        display_name="AFL",
        base_urls={"premium": "https://api.afl.com.au"},
        auth={"premium": _spec(), "public": AuthNone()},
    )


def _install_mock(http: HTTPClient, handler) -> None:
    """Swap the client's transport so both the mint and the data call are mocked."""
    http._client = _async_client(handler)


async def test_httpclient_attaches_minted_token():
    seen_headers = {}

    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path == "/cfs/afl/WMCTok":
            return httpx.Response(200, json={"token": "MINTED"})
        seen_headers.update(req.headers)
        return httpx.Response(200, json={"ok": True}, headers={"content-type": "application/json"})

    http = HTTPClient(_premium_provider(), Config())
    _install_mock(http, handler)
    out = await http.request_json(
        method="GET", base="premium", url="/cfs/afl/matchItem/CD_M1", auth_key="premium"
    )
    assert out == {"ok": True}
    assert seen_headers.get("x-media-mis-token") == "MINTED"
    await http.aclose()


async def test_httpclient_remints_on_401():
    state = {"data_calls": 0, "mints": 0}

    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path == "/cfs/afl/WMCTok":
            state["mints"] += 1
            return httpx.Response(200, json={"token": f"tok{state['mints']}"})
        state["data_calls"] += 1
        if state["data_calls"] == 1:
            return httpx.Response(401, json={"code": "CFSAPI001"}, headers={"content-type": "application/json"})
        return httpx.Response(200, json={"ok": True}, headers={"content-type": "application/json"})

    http = HTTPClient(_premium_provider(), Config())
    _install_mock(http, handler)
    out = await http.request_json(
        method="GET", base="premium", url="/cfs/afl/matchItem/CD_M1", auth_key="premium"
    )
    assert out == {"ok": True}
    assert state["mints"] == 2  # initial mint + re-mint after 401
    assert state["data_calls"] == 2
    await http.aclose()
