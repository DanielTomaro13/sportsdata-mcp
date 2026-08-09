"""Short-lived GET response cache.

The cache absorbs the duplicate calls a model makes while reasoning over one question
(and the retry storms a confused one makes), without ever letting a *stale price* or a
*wrong tier's document* reach the caller — this server exists to report live odds, so a
cache that is too eager is worse than none.
"""

from __future__ import annotations

import httpx
import pytest

from sportsdata_mcp.config import Config
from sportsdata_mcp.http_client import HTTPClient
from sportsdata_mcp.spec import AuthNone, AuthStaticHeader, Provider


def _provider() -> Provider:
    return Provider(
        id="demo",
        display_name="Demo",
        base_urls={"default": "https://api.demo.test"},
        auth={"default": AuthNone(), "private": AuthStaticHeader(
            type="static_header", header="Cookie", env="DEMO_COOKIE", optional=True
        )},
    )


def _client(cfg: Config) -> tuple[HTTPClient, list[str]]:
    """Client whose transport records every URL that actually hits the network."""
    calls: list[str] = []

    def handler(req: httpx.Request) -> httpx.Response:
        calls.append(str(req.url))
        return httpx.Response(
            200,
            json={"n": len(calls)},  # changes per real request, so a hit is detectable
            headers={"content-type": "application/json"},
        )

    http = HTTPClient(_provider(), cfg)
    http._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return http, calls


async def test_identical_gets_hit_the_cache():
    http, calls = _client(Config(cache_ttl_override=60))
    a = await http.request_json(method="GET", base="default", url="/v1/x")
    b = await http.request_json(method="GET", base="default", url="/v1/x")
    assert a == b == {"n": 1}, "second call should be served from cache"
    assert len(calls) == 1
    await http.aclose()


async def test_different_params_are_different_entries():
    http, calls = _client(Config(cache_ttl_override=60))
    await http.request_json(method="GET", base="default", url="/v1/x", params={"a": 1})
    await http.request_json(method="GET", base="default", url="/v1/x", params={"a": 2})
    assert len(calls) == 2
    await http.aclose()


async def test_ttl_zero_disables_caching():
    """The knob has to actually turn it off — someone watching a market move needs every
    call to be a real one."""
    http, calls = _client(Config(cache_ttl_override=0))
    await http.request_json(method="GET", base="default", url="/v1/x")
    await http.request_json(method="GET", base="default", url="/v1/x")
    assert len(calls) == 2
    await http.aclose()


async def test_expired_entry_refetches(monkeypatch):
    http, calls = _client(Config(cache_ttl_override=60))
    await http.request_json(method="GET", base="default", url="/v1/x")
    # Jump past the TTL rather than sleeping.
    import sportsdata_mcp.http_client as mod

    real = mod.time.monotonic
    monkeypatch.setattr(mod.time, "monotonic", lambda: real() + 3600)
    await http.request_json(method="GET", base="default", url="/v1/x")
    assert len(calls) == 2
    await http.aclose()


async def test_non_get_is_never_cached():
    """A POST may have side effects upstream; replaying one from cache would be wrong."""
    http, calls = _client(Config(cache_ttl_override=60))
    await http.request_json(method="POST", base="default", url="/v1/x", json_body={"q": 1})
    await http.request_json(method="POST", base="default", url="/v1/x", json_body={"q": 1})
    assert len(calls) == 2
    await http.aclose()


async def test_auth_tiers_do_not_share_a_cache_entry(monkeypatch):
    """Same URL, different auth key = different document. ESPN Fantasy is the live case:
    a private league 401s anonymously and returns data with the cookie. Sharing one entry
    across tiers would leak one user's tier into another's call."""
    monkeypatch.setenv("DEMO_COOKIE", "espn_s2=abc; SWID={x}")
    http, calls = _client(Config(cache_ttl_override=60))
    await http.request_json(method="GET", base="default", url="/league/1", auth_key="default")
    await http.request_json(method="GET", base="default", url="/league/1", auth_key="private")
    assert len(calls) == 2, "anonymous and authenticated reads must not share a cache entry"
    await http.aclose()


async def test_cache_is_bounded():
    """A long-running server driven over many distinct params must not grow forever."""
    from sportsdata_mcp.http_client import _CACHE_MAX_ENTRIES

    # Lift the token bucket: this test makes ~280 requests and the default 10 rps would
    # make it a 28-second unit test.
    http, _calls = _client(
        Config(cache_ttl_override=600, providers={"demo": {"rate_limit_rps": 10000, "burst": 10000}})
    )
    for i in range(_CACHE_MAX_ENTRIES + 25):
        await http.request_json(method="GET", base="default", url="/v1/x", params={"i": i})
    assert len(http._cache) <= _CACHE_MAX_ENTRIES
    await http.aclose()


@pytest.mark.parametrize("ttl,expected", [(None, 60.0), (5, 5.0), (0, 0.0)])
def test_config_ttl_precedence(ttl, expected):
    cfg = Config(cache_ttl_override=ttl)
    assert cfg.cache_ttl_for("demo") == expected


def test_per_provider_ttl_beats_global():
    cfg = Config(cache_ttl_override=60, providers={"demo": {"cache_ttl_seconds": 0}})
    assert cfg.cache_ttl_for("demo") == 0.0
    assert cfg.cache_ttl_for("other") == 60.0
