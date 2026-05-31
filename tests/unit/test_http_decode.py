"""Defensive response decoding in HTTPClient._decode."""

from __future__ import annotations

import httpx
import pytest

from sportsdata_mcp.config import Config
from sportsdata_mcp.errors import ToolError
from sportsdata_mcp.http_client import HTTPClient
from sportsdata_mcp.spec import AuthNone, Provider

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


def test_oversize_raises_recoverable():
    c = _client(max_bytes=10)
    with pytest.raises(ToolError) as ei:
        c._decode(_resp(200, b'{"data": "way too long"}', JSON))
    assert ei.value.code == "RESPONSE_TOO_LARGE"
    assert ei.value.recoverable is True


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
