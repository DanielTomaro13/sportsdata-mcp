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


async def test_value_prefix_prepended(monkeypatch):
    """value_prefix turns a bare env token into header syntax (Bearer <token>)."""
    from sportsdata_mcp.auth.header import StaticHeaderAuthProvider
    from sportsdata_mcp.spec import AuthStaticHeader

    monkeypatch.setenv("TEST_X_BEARER", "tok123")
    spec = AuthStaticHeader(type="static_header", header="Authorization", env="TEST_X_BEARER", value_prefix="Bearer ")
    name, value = await StaticHeaderAuthProvider(spec).get()
    assert (name, value) == ("Authorization", "Bearer tok123")


async def test_env_overrides_literal_value(monkeypatch):
    """With both env and value set, the env var wins (rotate-via-env)."""
    from sportsdata_mcp.auth.header import StaticHeaderAuthProvider
    from sportsdata_mcp.spec import AuthStaticHeader

    monkeypatch.setenv("TEST_APIM_KEY", "rotated-key")
    spec = AuthStaticHeader(type="static_header", header="Ocp-Apim-Subscription-Key",
                            env="TEST_APIM_KEY", value="public-default")
    name, value = await StaticHeaderAuthProvider(spec).get()
    assert (name, value) == ("Ocp-Apim-Subscription-Key", "rotated-key")


async def test_literal_value_used_when_env_unset(monkeypatch):
    """env set but unset in environment → fall back to the literal public default."""
    from sportsdata_mcp.auth.header import StaticHeaderAuthProvider
    from sportsdata_mcp.spec import AuthStaticHeader

    monkeypatch.delenv("TEST_APIM_KEY", raising=False)
    spec = AuthStaticHeader(type="static_header", header="Ocp-Apim-Subscription-Key",
                            env="TEST_APIM_KEY", value="public-default")
    _name, value = await StaticHeaderAuthProvider(spec).get()
    assert value == "public-default"


def test_env_only_still_requires_var(monkeypatch):
    """env-only (no literal) must still raise when unset — no silent anonymous mode."""
    import pytest

    from sportsdata_mcp.auth.header import StaticHeaderAuthProvider
    from sportsdata_mcp.errors import AuthMissingError
    from sportsdata_mcp.spec import AuthStaticHeader

    monkeypatch.delenv("TEST_REQUIRED", raising=False)
    spec = AuthStaticHeader(type="static_header", header="X-Key", env="TEST_REQUIRED")
    with pytest.raises(AuthMissingError):
        StaticHeaderAuthProvider(spec)


# ─── optional tier: unset credential means anonymous, not an error ─────────


def _optional_provider() -> Provider:
    """ESPN Fantasy's shape: public leagues anonymous, private ones cookie-authed."""
    return Provider(
        id="demo",
        display_name="Demo",
        base_urls={"default": "https://api.demo.test"},
        auth={
            "private": AuthStaticHeader(
                type="static_header", header="Cookie", env="DEMO_COOKIE", optional=True
            )
        },
    )


async def _roundtrip(monkeypatch) -> dict[str, str]:
    seen: dict[str, str] = {}

    def handler(req: httpx.Request) -> httpx.Response:
        seen.update(req.headers)
        return httpx.Response(200, json={"ok": True}, headers={"content-type": "application/json"})

    http = HTTPClient(_optional_provider(), Config())
    http._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    await http.request_json(method="GET", base="default", url="/league/1", auth_key="private")
    await http.aclose()
    return seen


async def test_optional_header_unset_goes_out_anonymous(monkeypatch):
    """The public tier must still work: no env var → no Cookie header, no exception."""
    monkeypatch.delenv("DEMO_COOKIE", raising=False)
    seen = await _roundtrip(monkeypatch)
    assert "cookie" not in {k.lower() for k in seen}


async def test_optional_header_is_sent_once_configured(monkeypatch):
    """Setting the env var upgrades the very same tools to the authenticated tier."""
    monkeypatch.setenv("DEMO_COOKIE", "espn_s2=abc; SWID={xyz}")
    seen = await _roundtrip(monkeypatch)
    assert seen.get("cookie") == "espn_s2=abc; SWID={xyz}"


async def test_non_optional_header_still_raises_when_unset(monkeypatch):
    """`optional` must not weaken the default contract for required credentials."""
    monkeypatch.delenv("DEMO_KEY", raising=False)
    http = HTTPClient(_provider(), Config())
    with pytest.raises(AuthMissingError):
        await http.request_json(method="GET", base="default", url="/v2/thing", auth_key="default")
    await http.aclose()
