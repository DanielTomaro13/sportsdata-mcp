"""Licensed proxy mode (commerce): a credentialed provider (DataGolf) is routed through
the entitlement service, which attaches the real upstream key server-side. A customer
who supplies their own key, or an unlicensed install, calls the upstream directly."""

from __future__ import annotations

import httpx

from sportsdata_mcp.config import Config
from sportsdata_mcp.http_client import HTTPClient
from sportsdata_mcp.spec import AuthStaticQuery, Provider


def _datagolf_provider() -> Provider:
    return Provider(
        id="datagolf",
        display_name="Data Golf",
        base_urls={"default": "https://feeds.datagolf.com"},
        auth={"default": AuthStaticQuery(type="static_query", param="key", env="DATAGOLF_KEY")},
        # mirror the real datagolf.yaml: the proxied/byo-key routing is now spec data
        proxied=True,
        byo_key_env="DATAGOLF_KEY",
    )


def _capture(seen: dict):
    def handler(req: httpx.Request) -> httpx.Response:
        seen["url"] = str(req.url)
        seen["params"] = dict(req.url.params)
        seen["headers"] = dict(req.headers)
        return httpx.Response(200, json={"ok": True}, headers={"content-type": "application/json"})

    return handler


async def test_licensed_routes_through_entitlement_proxy(monkeypatch):
    monkeypatch.delenv("DATAGOLF_KEY", raising=False)
    monkeypatch.setenv("SPORTSDATA_LICENSE", "sd_live_abc")
    monkeypatch.setenv("SPORTSDATA_ENTITLEMENT_URL", "https://ent.example")
    seen: dict = {}
    http = HTTPClient(_datagolf_provider(), Config())
    http._client = httpx.AsyncClient(transport=httpx.MockTransport(_capture(seen)))
    out = await http.request_json(
        method="GET", base="default", url="/get-player-list",
        params={"tour": "pga"}, auth_key="default",
    )
    assert out == {"ok": True}
    # routed to the proxy, licence in the header, caller params preserved …
    assert seen["url"].startswith("https://ent.example/proxy/datagolf/get-player-list")
    assert seen["headers"].get("authorization") == "Bearer sd_live_abc"
    assert seen["params"].get("tour") == "pga"
    # … and the upstream key is NOT attached client-side (the proxy adds it)
    assert "key" not in seen["params"]
    await http.aclose()


async def test_own_datagolf_key_bypasses_proxy(monkeypatch):
    """A customer with their own DATAGOLF_KEY calls the upstream directly."""
    monkeypatch.setenv("SPORTSDATA_LICENSE", "sd_live_abc")
    monkeypatch.setenv("DATAGOLF_KEY", "ownkey")
    seen: dict = {}
    http = HTTPClient(_datagolf_provider(), Config())
    http._client = httpx.AsyncClient(transport=httpx.MockTransport(_capture(seen)))
    await http.request_json(method="GET", base="default", url="/get-player-list", auth_key="default")
    assert seen["url"].startswith("https://feeds.datagolf.com/get-player-list")
    assert seen["params"].get("key") == "ownkey"
    assert "authorization" not in seen["headers"]
    await http.aclose()


async def test_unlicensed_calls_upstream_directly(monkeypatch):
    monkeypatch.delenv("SPORTSDATA_LICENSE", raising=False)
    monkeypatch.setenv("DATAGOLF_KEY", "ownkey")
    seen: dict = {}
    http = HTTPClient(_datagolf_provider(), Config())
    http._client = httpx.AsyncClient(transport=httpx.MockTransport(_capture(seen)))
    await http.request_json(method="GET", base="default", url="/get-player-list", auth_key="default")
    assert seen["url"].startswith("https://feeds.datagolf.com/get-player-list")
    await http.aclose()
