"""Cookie handling: `defaults.strip_cookies` discards upstream-set cookies.

Akamai bot-manager (TAB) sets bm_* cookies on the first response and 403s any
client that replays them without the matching JS-sensor telemetry, so a
strip_cookies provider must never echo a stored cookie back.
"""

from __future__ import annotations

import httpx

from sportsdata_mcp.config import Config
from sportsdata_mcp.http_client import HTTPClient
from sportsdata_mcp.spec import AuthNone, Provider, ProviderDefaults


def _client(*, strip: bool, prov_cfg: dict | None = None) -> HTTPClient:
    provider = Provider(
        id="demo",
        display_name="Demo",
        base_urls={"default": "https://api.demo.test"},
        auth={"default": AuthNone()},
        defaults=ProviderDefaults(strip_cookies=strip),
    )
    cfg = Config(providers={"demo": prov_cfg} if prov_cfg else {})
    return HTTPClient(provider, cfg)


def _mock_transport(seen_cookie_headers: list[str | None]) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        seen_cookie_headers.append(request.headers.get("cookie"))
        return httpx.Response(
            200,
            headers={"set-cookie": "bm_s=sensor-flagged; Path=/", "content-type": "application/json"},
            json={"ok": True},
        )

    return httpx.MockTransport(handler)


async def test_strip_cookies_never_replays_upstream_cookie():
    c = _client(strip=True)
    seen: list[str | None] = []
    c._client._transport = _mock_transport(seen)
    await c.request_json(method="GET", base="default", url="/x")
    await c.request_json(method="GET", base="default", url="/x")
    await c.aclose()
    assert seen == [None, None]


async def test_default_keeps_cookies_across_requests():
    c = _client(strip=False)
    seen: list[str | None] = []
    c._client._transport = _mock_transport(seen)
    await c.request_json(method="GET", base="default", url="/x")
    await c.request_json(method="GET", base="default", url="/x")
    await c.aclose()
    assert seen[0] is None
    assert seen[1] == "bm_s=sensor-flagged"


async def test_user_config_overrides_spec_strip_cookies():
    c = _client(strip=False, prov_cfg={"strip_cookies": True})
    seen: list[str | None] = []
    c._client._transport = _mock_transport(seen)
    await c.request_json(method="GET", base="default", url="/x")
    await c.request_json(method="GET", base="default", url="/x")
    await c.aclose()
    assert seen == [None, None]
