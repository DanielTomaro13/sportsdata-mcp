"""Static query-param auth: env/secrets resolution + HTTPClient injects into the query."""

from __future__ import annotations

import httpx
import pytest

from sportsdata_mcp.auth.query import StaticQueryAuthProvider
from sportsdata_mcp.config import Config
from sportsdata_mcp.errors import AuthMissingError
from sportsdata_mcp.http_client import HTTPClient
from sportsdata_mcp.spec import AuthNone, AuthStaticQuery, Provider


def _q(*, value: str | None = None, env: str | None = None) -> AuthStaticQuery:
    return AuthStaticQuery(type="static_query", param="key", value=value, env=env)


async def test_literal_value():
    ap = StaticQueryAuthProvider(_q(value="literal-123"))
    assert await ap.get() == ("key", "literal-123")


async def test_env_var_wins_over_secrets(monkeypatch):
    monkeypatch.setenv("DG_KEY", "from-env")
    ap = StaticQueryAuthProvider(_q(env="DG_KEY"), {"DG_KEY": "from-secrets"})
    assert await ap.get() == ("key", "from-env")


async def test_secrets_fallback_when_env_unset(monkeypatch):
    monkeypatch.delenv("DG_KEY", raising=False)
    ap = StaticQueryAuthProvider(_q(env="DG_KEY"), {"DG_KEY": "from-secrets"})
    assert await ap.get() == ("key", "from-secrets")


async def test_missing_env_and_secrets_raises(monkeypatch):
    monkeypatch.delenv("DG_KEY", raising=False)
    with pytest.raises(AuthMissingError, match="DG_KEY"):
        StaticQueryAuthProvider(_q(env="DG_KEY"), {})


# ─── HTTPClient end-to-end: secret rides in the QUERY STRING, not headers ──


def _provider() -> Provider:
    return Provider(
        id="dg",
        display_name="DG",
        base_urls={"default": "https://feeds.demo.test"},
        auth={"default": _q(env="DG_KEY"), "public": AuthNone()},
    )


async def test_httpclient_injects_key_into_query_not_headers(monkeypatch):
    monkeypatch.delenv("DG_KEY", raising=False)
    seen = {}

    def handler(req: httpx.Request) -> httpx.Response:
        seen["params"] = dict(req.url.params)
        seen["headers"] = dict(req.headers)
        return httpx.Response(200, json={"ok": True}, headers={"content-type": "application/json"})

    http = HTTPClient(_provider(), Config(secrets={"DG_KEY": "secret-xyz"}))
    http._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    out = await http.request_json(
        method="GET", base="default", url="/get-player-list",
        params={"file_format": "json"}, auth_key="default",
    )
    assert out == {"ok": True}
    # the key is in the query string alongside the caller's params …
    assert seen["params"] == {"file_format": "json", "key": "secret-xyz"}
    # … and NOT leaked into a header
    assert "key" not in seen["headers"]
    await http.aclose()
