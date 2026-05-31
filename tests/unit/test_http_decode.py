"""Defensive response decoding in HTTPClient._decode."""

from __future__ import annotations

import httpx
import pytest

from sportsdata_mcp.config import RATE_LIMIT_RPS_DEFAULT, Config
from sportsdata_mcp.errors import ToolError
from sportsdata_mcp.http_client import HTTPClient
from sportsdata_mcp.spec import AuthNone, Provider, ProviderDefaults

JSON = {"content-type": "application/json"}


def _client(max_bytes: int | None = None) -> HTTPClient:
    providers = {"demo": {"max_response_bytes": max_bytes}} if max_bytes else {}
    cfg = Config(providers=providers)
    provider = Provider(
        id="demo",
        display_name="Demo",
        base_urls={"default": "https://api.demo.test"},
        auth={"default": AuthNone()},
    )
    return HTTPClient(provider, cfg)


def _resp(status: int, body: bytes, headers: dict | None = None) -> httpx.Response:
    return httpx.Response(status_code=status, headers=headers or {}, content=body)


def test_ok_json_decodes():
    c = _client()
    out = c._decode(_resp(200, b'{"ok": true}', JSON))
    assert out == {"ok": True}


def test_text_plain_json_decodes():
    """Some APIs (e.g. NBA's CDN) serve valid JSON labelled text/plain — accept it."""
    c = _client()
    out = c._decode(_resp(200, b'{"ok": true}', {"content-type": "text/plain"}))
    assert out == {"ok": True}


def test_no_content_type_json_decodes():
    c = _client()
    out = c._decode(_resp(200, b'[1, 2, 3]', {}))
    assert out == [1, 2, 3]


def test_oversize_raises_recoverable():
    c = _client(max_bytes=10)
    with pytest.raises(ToolError) as ei:
        c._decode(_resp(200, b'{"data": "way too long"}', JSON))
    assert ei.value.code == "RESPONSE_TOO_LARGE"
    assert ei.value.recoverable is True


def _client_with_cap(cap: int) -> HTTPClient:
    """A client whose provider sets an explicit cap (including 0 = unlimited)."""
    cfg = Config(providers={"demo": {"max_response_bytes": cap}})
    provider = Provider(
        id="demo",
        display_name="Demo",
        base_urls={"default": "https://api.demo.test"},
        auth={"default": AuthNone()},
    )
    return HTTPClient(provider, cfg)


def test_zero_cap_disables_size_guard():
    c = _client_with_cap(0)
    big = b'{"data": "' + b"x" * 5_000_000 + b'"}'
    out = c._decode(_resp(200, big, JSON))  # would raise RESPONSE_TOO_LARGE under any positive cap
    assert out["data"].startswith("x")


def test_global_override_applies_when_provider_unset():
    cfg = Config(max_bytes_override=0)
    assert cfg.max_response_bytes_for("anything") == 0  # 0 → unlimited, for every provider


def test_provider_cap_beats_global_override():
    cfg = Config(providers={"demo": {"max_response_bytes": 1234}}, max_bytes_override=0)
    assert cfg.max_response_bytes_for("demo") == 1234
    assert cfg.max_response_bytes_for("other") == 0


def test_429_rate_limited():
    c = _client()
    with pytest.raises(ToolError) as ei:
        c._decode(_resp(429, b"slow down", JSON))
    assert ei.value.code == "RATE_LIMITED"
    assert ei.value.recoverable is True


def test_403_blocked():
    c = _client()
    with pytest.raises(ToolError) as ei:
        c._decode(_resp(403, b"<html>Access Denied</html>", {"content-type": "text/html"}))
    assert ei.value.code == "BLOCKED"
    assert ei.value.recoverable is False


def test_500_recoverable_status_error():
    c = _client()
    with pytest.raises(ToolError) as ei:
        c._decode(_resp(503, b"oops", JSON))
    assert ei.value.code == "HTTP_503"
    assert ei.value.recoverable is True


def test_404_not_recoverable():
    c = _client()
    with pytest.raises(ToolError) as ei:
        c._decode(_resp(404, b"missing", JSON))
    assert ei.value.code == "HTTP_404"
    assert ei.value.recoverable is False


def test_non_json_challenge_page():
    c = _client()
    with pytest.raises(ToolError) as ei:
        c._decode(_resp(200, b"<html>checking your browser</html>", {"content-type": "text/html"}))
    assert ei.value.code == "NON_JSON_RESPONSE"


def test_json_content_type_but_unparseable():
    c = _client()
    with pytest.raises(ToolError) as ei:
        c._decode(_resp(200, b"{not json", JSON))
    assert ei.value.code == "JSON_DECODE_ERROR"


# ─── Spec-level provider defaults flow into the client ──────────────────


def _provider_with_defaults() -> Provider:
    return Provider(
        id="nba",
        display_name="NBA",
        base_urls={"default": "https://stats.nba.com"},
        auth={"default": AuthNone()},
        defaults=ProviderDefaults(
            rate_limit_rps=0.4,
            request_timeout_seconds=45,
            burst=1,
            retry_statuses=[429, 500, 502, 503, 504],
            max_retries=3,
            retry_backoff_seconds=1.0,
        ),
    )


def test_spec_defaults_configure_client():
    c = HTTPClient(_provider_with_defaults(), Config())
    assert c._bucket.rate == 0.4
    assert c._bucket.burst == 1
    assert c._retry_statuses == {429, 500, 502, 503, 504}
    assert c._max_retries == 3
    assert c._retry_backoff == 1.0


def test_user_config_overrides_spec_defaults_in_client():
    cfg = Config(providers={"nba": {"rate_limit_rps": 5, "burst": 8, "max_retries": 0}})
    c = HTTPClient(_provider_with_defaults(), cfg)
    assert c._bucket.rate == 5.0
    assert c._bucket.burst == 8
    assert c._max_retries == 0  # operator opted out of retries
    # untouched keys still come from the spec defaults
    assert c._retry_statuses == {429, 500, 502, 503, 504}


def test_no_spec_defaults_keeps_engine_behaviour():
    """A provider with no defaults block retries nothing and uses the engine rate."""
    p = Provider(id="demo", display_name="Demo", base_urls={"default": "https://x.test"}, auth={"default": AuthNone()})
    c = HTTPClient(p, Config())
    assert c._max_retries == 0
    assert c._retry_statuses == set()
    assert c._bucket.rate == RATE_LIMIT_RPS_DEFAULT


async def test_request_retries_transient_status_then_succeeds():
    """503, 503, 200 → the loop retries (no backoff delay) and returns the 200."""
    p = Provider(
        id="nba",
        display_name="NBA",
        base_urls={"default": "https://stats.nba.com"},
        auth={"default": AuthNone()},
        defaults=ProviderDefaults(retry_statuses=[503], max_retries=3, retry_backoff_seconds=0.0),
    )
    c = HTTPClient(p, Config())
    seq = [_resp(503, b"slow"), _resp(503, b"slow"), _resp(200, b'{"ok": true}', JSON)]
    calls = {"n": 0}

    async def fake_request(*args, **kwargs):
        i = calls["n"]
        calls["n"] += 1
        return seq[i]

    c._client.request = fake_request  # type: ignore[method-assign]
    r = await c.request(method="GET", base="default", url="/stats/x")
    assert r.status_code == 200
    assert calls["n"] == 3  # two retries then success
    await c.aclose()


async def test_request_gives_up_after_max_retries():
    """All attempts 503 → returns the last 503 (then _decode would surface HTTP_503)."""
    p = Provider(
        id="nba",
        display_name="NBA",
        base_urls={"default": "https://stats.nba.com"},
        auth={"default": AuthNone()},
        defaults=ProviderDefaults(retry_statuses=[503], max_retries=2, retry_backoff_seconds=0.0),
    )
    c = HTTPClient(p, Config())
    calls = {"n": 0}

    async def fake_request(*args, **kwargs):
        calls["n"] += 1
        return _resp(503, b"down")

    c._client.request = fake_request  # type: ignore[method-assign]
    r = await c.request(method="GET", base="default", url="/stats/x")
    assert r.status_code == 503
    assert calls["n"] == 3  # 1 initial + 2 retries
    await c.aclose()
