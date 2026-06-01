"""Static-header auth: literal value, env var, and the config `secrets` fallback."""

from __future__ import annotations

import httpx
import pytest

from sportsdata_mcp.auth.header import StaticHeaderAuthProvider
from sportsdata_mcp.config import Config
from sportsdata_mcp.errors import AuthMissingError
from sportsdata_mcp.http_client import HTTPClient
from sportsdata_mcp.spec import AuthNone, AuthStaticHeader, Provider


def _hdr(*, value: str | None = None, env: str | None = None) -> AuthStaticHeader:
    return AuthStaticHeader(type="static_header", header="x-api-key", value=value, env=env)


async def test_literal_value():
    ap = StaticHeaderAuthProvider(_hdr(value="literal-123"))
    assert await ap.get() == ("x-api-key", "literal-123")


async def test_env_var_wins_over_secrets(monkeypatch):
    """A real env var takes precedence over a same-named `secrets` entry."""
    monkeypatch.setenv("DEMO_KEY", "from-env")
    ap = StaticHeaderAuthProvider(_hdr(env="DEMO_KEY"), {"DEMO_KEY": "from-secrets"})
    assert await ap.get() == ("x-api-key", "from-env")


async def test_secrets_fallback_when_env_unset(monkeypatch):
    """With no env var, the value comes from the config `secrets` block (local-dev path)."""
    monkeypatch.delenv("DEMO_KEY", raising=False)
    ap = StaticHeaderAuthProvider(_hdr(env="DEMO_KEY"), {"DEMO_KEY": "from-secrets"})
    assert await ap.get() == ("x-api-key", "from-secrets")


async def test_missing_env_and_secrets_raises(monkeypatch):
    monkeypatch.delenv("DEMO_KEY", raising=False)
    with pytest.raises(AuthMissingError, match="DEMO_KEY"):
        StaticHeaderAuthProvider(_hdr(env="DEMO_KEY"), {})


async def test_neither_value_nor_env_raises():
    with pytest.raises(AuthMissingError, match="neither"):
        StaticHeaderAuthProvider(_hdr())


# ─── HTTPClient end-to-end: secret pulled from Config and injected ─────────


def _provider() -> Provider:
    return Provider(
        id="demo",
        display_name="Demo",
        base_urls={"default": "https://api.demo.test"},
        auth={"default": _hdr(env="DEMO_KEY"), "public": AuthNone()},
    )


async def test_httpclient_injects_secret_from_config(monkeypatch):
    """A `static_header` `env:` auth resolves through Config(secrets=...) onto the wire."""
    monkeypatch.delenv("DEMO_KEY", raising=False)
    seen: dict[str, str] = {}

    def handler(req: httpx.Request) -> httpx.Response:
        seen.update(req.headers)
        return httpx.Response(200, json={"ok": True}, headers={"content-type": "application/json"})

    http = HTTPClient(_provider(), Config(secrets={"DEMO_KEY": "secret-xyz"}))
    http._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    out = await http.request_json(method="GET", base="default", url="/v2/thing", auth_key="default")
    assert out == {"ok": True}
    assert seen.get("x-api-key") == "secret-xyz"
    await http.aclose()
