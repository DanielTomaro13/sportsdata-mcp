"""oauth_refresh auth: token mint/cache/refresh against a fake endpoint (no live creds)."""

from __future__ import annotations


import httpx
import pytest

from sportsdata_mcp.auth.oauth import OAuthRefreshProvider
from sportsdata_mcp.errors import AuthMissingError
from sportsdata_mcp.spec import AuthOAuthRefresh

SPEC = AuthOAuthRefresh(
    type="oauth_refresh",
    token_url="https://fake.tab/oauth/token",
    refresh_token_env="T_REFRESH",
    client_id_env="T_ID",
    client_secret_env="T_SECRET",
    expiry_margin_seconds=60,
)


def _env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("T_REFRESH", "refresh-1")
    monkeypatch.setenv("T_ID", "client-1")
    monkeypatch.setenv("T_SECRET", "secret-1")


class FakeTokenEndpoint:
    def __init__(self, *, expires_in: int = 3600, rotate_to: str | None = None, fail: str | None = None) -> None:
        self.calls: list[httpx.Request] = []
        self.expires_in = expires_in
        self.rotate_to = rotate_to
        self.fail = fail
        self.minted = 0

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.calls.append(request)
        if self.fail == "invalid_grant":
            return httpx.Response(400, json={"error": "invalid_grant", "error_description": "Refresh token has expired"})
        if self.fail == "server":
            return httpx.Response(503, text="upstream sad")
        self.minted += 1
        body: dict = {"access_token": f"at-{self.minted}", "expires_in": self.expires_in}
        if self.rotate_to:
            body["refresh_token"] = self.rotate_to
        return httpx.Response(200, json=body)

    def client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=httpx.MockTransport(self.handler))


async def test_mints_form_encoded_and_returns_bearer(monkeypatch: pytest.MonkeyPatch) -> None:
    _env(monkeypatch)
    fake = FakeTokenEndpoint()
    provider = OAuthRefreshProvider(SPEC, fake.client())
    name, value = await provider.get()
    assert (name, value) == ("Authorization", "Bearer at-1")
    req = fake.calls[0]
    assert req.headers["content-type"] == "application/x-www-form-urlencoded"  # TAB rejects JSON
    body = dict(pair.split("=") for pair in req.content.decode().split("&"))
    assert body == {
        "grant_type": "refresh_token",
        "refresh_token": "refresh-1",
        "client_id": "client-1",
        "client_secret": "secret-1",
    }


async def test_token_cached_until_expiry(monkeypatch: pytest.MonkeyPatch) -> None:
    _env(monkeypatch)
    fake = FakeTokenEndpoint()
    provider = OAuthRefreshProvider(SPEC, fake.client())
    await provider.get()
    await provider.get()
    await provider.get()
    assert fake.minted == 1  # cached


async def test_short_expiry_triggers_proactive_refresh(monkeypatch: pytest.MonkeyPatch) -> None:
    """expires_in below the margin floors the cache window (~30s) — but a token at the
    margin boundary refreshes on the next call once monotonic passes expiry. Simulate
    by forcing the clock."""
    _env(monkeypatch)
    fake = FakeTokenEndpoint(expires_in=3600)
    provider = OAuthRefreshProvider(SPEC, fake.client())
    await provider.get()
    provider._expires_at = 0.0  # token aged out
    name, value = await provider.get()
    assert value == "Bearer at-2"
    assert fake.minted == 2


async def test_invalidate_forces_refresh(monkeypatch: pytest.MonkeyPatch) -> None:
    """The request loop calls invalidate() on 401 — next get() must re-mint."""
    _env(monkeypatch)
    fake = FakeTokenEndpoint()
    provider = OAuthRefreshProvider(SPEC, fake.client())
    await provider.get()
    provider.invalidate()
    _, value = await provider.get()
    assert value == "Bearer at-2" and fake.minted == 2


async def test_rotated_refresh_token_warns_and_keeps_working(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    _env(monkeypatch)
    fake = FakeTokenEndpoint(rotate_to="refresh-2")
    provider = OAuthRefreshProvider(SPEC, fake.client())
    with caplog.at_level("WARNING", logger="sportsdata_mcp.auth.oauth"):
        await provider.get()
    assert any("ROTATED" in r.getMessage() and "TAB" not in r.getMessage() for r in caplog.records) or any(
        "T_REFRESH" in r.getMessage() for r in caplog.records
    )
    # next refresh uses the rotated token
    provider.invalidate()
    await provider.get()
    body = dict(pair.split("=") for pair in fake.calls[-1].content.decode().split("&"))
    assert body["refresh_token"] == "refresh-2"


async def test_expired_refresh_token_is_actionable(monkeypatch: pytest.MonkeyPatch) -> None:
    _env(monkeypatch)
    fake = FakeTokenEndpoint(fail="invalid_grant")
    provider = OAuthRefreshProvider(SPEC, fake.client())
    with pytest.raises(AuthMissingError, match="harvest a new one"):
        await provider.get()


def test_missing_env_fails_loudly(monkeypatch: pytest.MonkeyPatch) -> None:
    for var in ("T_REFRESH", "T_ID", "T_SECRET"):
        monkeypatch.delenv(var, raising=False)
    with pytest.raises(AuthMissingError, match="T_REFRESH"):
        OAuthRefreshProvider(SPEC, httpx.AsyncClient())


def test_tab_spec_carries_optional_oauth_scheme() -> None:
    """tab.yaml: `oauth` available, `default` still none (public data needs no auth)."""
    from sportsdata_mcp.spec import AuthNone, AuthOAuthRefresh as AOR
    from sportsdata_mcp.spec_loader import load_all_specs

    tab = next(s for s in load_all_specs() if s.provider.id == "tab")
    assert isinstance(tab.provider.auth["default"], AuthNone)
    oauth = tab.provider.auth["oauth"]
    assert isinstance(oauth, AOR)
    assert oauth.token_url.endswith("/oauth/token")
    assert oauth.refresh_token_env == "TAB_REFRESH_TOKEN"
