"""A 401/403 from a BYO-key provider must name the env var to set.

With 20+ BYO-key providers, "blocked — likely bot detection or geo-block" is the wrong
diagnosis for the overwhelmingly common case: the user simply hasn't set a key. That
message sends someone hunting for a geo-block that doesn't exist. But a genuine block
(a provider that needs NO key, like the AU bookmakers refusing a cloud IP) must still
read as a block — the two must not be conflated in either direction.
"""

from __future__ import annotations

import httpx
import pytest

from sportsdata_mcp.config import Config
from sportsdata_mcp.errors import ToolError
from sportsdata_mcp.http_client import HTTPClient
from sportsdata_mcp.spec import AuthNone, AuthStaticHeader, Provider


def _client(provider: Provider, status: int, body: str = "{}") -> HTTPClient:
    http = HTTPClient(provider, Config(cache_ttl_override=0))
    http._client = httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda req: httpx.Response(status, text=body, headers={"content-type": "application/json"})
        )
    )
    return http


def _byo_provider() -> Provider:
    return Provider(
        id="byo", display_name="BYO",
        base_urls={"default": "https://api.byo.test"},
        auth={"default": AuthStaticHeader(
            type="static_header", header="Authorization", env="BYO_TOKEN", optional=True)},
    )


def _keyless_provider() -> Provider:
    return Provider(
        id="keyless", display_name="Keyless",
        base_urls={"default": "https://api.keyless.test"},
        auth={"default": AuthNone()},
    )


@pytest.mark.parametrize("status", [401, 403])
async def test_missing_key_names_the_env_var(monkeypatch, status):
    monkeypatch.delenv("BYO_TOKEN", raising=False)
    http = _client(_byo_provider(), status, '{"error":"Token is missing"}')
    with pytest.raises(ToolError) as ei:
        await http.request_json(method="GET", base="default", url="/x")
    assert ei.value.code == "AUTH_REQUIRED"
    assert "BYO_TOKEN" in str(ei.value)
    # The upstream's own words are preserved — they often say more than we can.
    assert "Token is missing" in str(ei.value)
    await http.aclose()


async def test_a_real_block_is_still_reported_as_a_block(monkeypatch):
    """A provider that needs no key and 403s IS blocked — the AU bookmakers refusing a
    cloud IP is the live case, and the drift check depends on that diagnosis."""
    http = _client(_keyless_provider(), 403, "<html>Access Denied</html>")
    with pytest.raises(ToolError) as ei:
        await http.request_json(method="GET", base="default", url="/x")
    assert ei.value.code == "BLOCKED"
    assert "bot detection or geo-block" in str(ei.value)
    await http.aclose()


async def test_a_configured_key_that_still_401s_is_not_told_to_set_it(monkeypatch):
    """If the key IS set and the upstream still refuses, the problem is a revoked key
    or the wrong plan — telling the user to set what they already have is useless."""
    monkeypatch.setenv("BYO_TOKEN", "already-set")
    http = _client(_byo_provider(), 401, '{"error":"plan does not include this endpoint"}')
    with pytest.raises(ToolError) as ei:
        await http.request_json(method="GET", base="default", url="/x")
    assert ei.value.code != "AUTH_REQUIRED"
    assert "set BYO_TOKEN" not in str(ei.value)
    await http.aclose()
