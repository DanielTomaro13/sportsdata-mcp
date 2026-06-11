"""Kalshi RSA signing — the optional authenticated tier.

Inactive (no env vars) must be a clean anonymous fallback, never an error;
active must produce verifiable RSA-PSS signatures over timestamp+method+path.
"""

from __future__ import annotations

import base64

import httpx
import pytest
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa

from sportsdata_mcp.config import Config
from sportsdata_mcp.errors import AuthMissingError
from sportsdata_mcp.http_client import HTTPClient
from sportsdata_mcp.spec import AuthKalshiRSA, Provider

SPEC = AuthKalshiRSA(
    type="kalshi_rsa",
    key_id_env="TEST_KALSHI_KEY_ID",
    private_key_env="TEST_KALSHI_PEM",
    private_key_path_env="TEST_KALSHI_PEM_PATH",
)


def _keypair():
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode()
    return key, pem


def _signer(monkeypatch, *, key_id=None, pem=None, pem_path=None):
    from sportsdata_mcp.auth.kalshi import KalshiRSASigner

    for env in ("TEST_KALSHI_KEY_ID", "TEST_KALSHI_PEM", "TEST_KALSHI_PEM_PATH"):
        monkeypatch.delenv(env, raising=False)
    if key_id:
        monkeypatch.setenv("TEST_KALSHI_KEY_ID", key_id)
    if pem:
        monkeypatch.setenv("TEST_KALSHI_PEM", pem)
    if pem_path:
        monkeypatch.setenv("TEST_KALSHI_PEM_PATH", str(pem_path))
    return KalshiRSASigner(SPEC)


def test_inactive_without_credentials(monkeypatch):
    s = _signer(monkeypatch)
    assert s.active is False
    assert s.sign_request("GET", "/trade-api/v2/markets") == {}


def test_inactive_with_only_key_id(monkeypatch):
    s = _signer(monkeypatch, key_id="kid-123")
    assert s.active is False


async def test_inactive_get_raises_for_doctor(monkeypatch):
    s = _signer(monkeypatch)
    with pytest.raises(AuthMissingError):
        await s.get()


def test_active_signature_verifies(monkeypatch):
    key, pem = _keypair()
    s = _signer(monkeypatch, key_id="kid-123", pem=pem)
    assert s.active is True
    headers = s.sign_request("get", "/trade-api/v2/markets?limit=5")
    assert headers["KALSHI-ACCESS-KEY"] == "kid-123"
    # signature covers timestamp + UPPER method + path WITHOUT the query string
    message = headers["KALSHI-ACCESS-TIMESTAMP"] + "GET" + "/trade-api/v2/markets"
    key.public_key().verify(
        base64.b64decode(headers["KALSHI-ACCESS-SIGNATURE"]),
        message.encode(),
        padding.PSS(mgf=padding.MGF1(hashes.SHA256()), salt_length=padding.PSS.DIGEST_LENGTH),
        hashes.SHA256(),
    )


def test_active_via_key_path(monkeypatch, tmp_path):
    _, pem = _keypair()
    p = tmp_path / "kalshi.pem"
    p.write_text(pem)
    s = _signer(monkeypatch, key_id="kid-456", pem_path=p)
    assert s.active is True
    assert s.sign_request("GET", "/x")["KALSHI-ACCESS-KEY"] == "kid-456"


async def test_http_client_signs_each_attempt(monkeypatch):
    """Active signer: requests carry the three KALSHI-ACCESS-* headers; anonymous
    clients (no env) send none."""
    _, pem = _keypair()
    provider = Provider(
        id="kalshi",
        display_name="Kalshi",
        base_urls={"default": "https://api.demo.test/trade-api/v2"},
        auth={"default": SPEC},
    )
    seen: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append({k: v for k, v in request.headers.items() if k.startswith("kalshi-access")})
        return httpx.Response(200, json={"ok": True}, headers={"content-type": "application/json"})

    monkeypatch.setenv("TEST_KALSHI_KEY_ID", "kid-789")
    monkeypatch.setenv("TEST_KALSHI_PEM", pem)
    c = HTTPClient(provider, Config())
    c._client._transport = httpx.MockTransport(handler)
    await c.request_json(method="GET", base="default", url="/markets")
    await c.aclose()
    assert set(seen[0]) == {"kalshi-access-key", "kalshi-access-signature", "kalshi-access-timestamp"}

    monkeypatch.delenv("TEST_KALSHI_KEY_ID")
    monkeypatch.delenv("TEST_KALSHI_PEM")
    c = HTTPClient(provider, Config())
    c._client._transport = httpx.MockTransport(handler)
    await c.request_json(method="GET", base="default", url="/markets")
    await c.aclose()
    assert seen[1] == {}
