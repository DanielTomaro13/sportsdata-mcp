"""Key rotation for the feed-entitlement gate (design-fix #5).

The gate trusts a *set* of Ed25519 keys keyed by `kid`, so the entitlement service's
signing key can rotate without a flag-day: a build can trust both the current and the next
key, and tokens carry a `kid` naming which one signed them. A kid-less (legacy) or
unknown-kid token still verifies by falling back to every trusted key.
"""

import base64
import json

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from sportsdata_mcp.licence import _verify_token


def _b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _keypair():
    priv = Ed25519PrivateKey.generate()
    pub = priv.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw
    )
    return priv, _b64url(pub)


def _sign(priv: Ed25519PrivateKey, claims: dict) -> str:
    payload = json.dumps(claims).encode()
    return _b64url(payload) + "." + _b64url(priv.sign(payload))


def test_kidless_token_verifies_against_the_single_trusted_key():
    priv, pub = _keypair()
    token = _sign(priv, {"status": "active", "groups": ["x"]})  # no kid (legacy form)
    assert _verify_token(token, {"k1": pub})["status"] == "active"


def test_kid_named_token_verifies_against_its_key_during_rotation():
    priv1, pub1 = _keypair()
    priv2, pub2 = _keypair()
    trusted = {"k1": pub1, "k2": pub2}  # build trusts both during a rotation
    old = _sign(priv1, {"kid": "k1", "status": "active"})
    new = _sign(priv2, {"kid": "k2", "status": "active"})
    assert _verify_token(old, trusted)["kid"] == "k1"
    assert _verify_token(new, trusted)["kid"] == "k2"


def test_kid_is_only_a_hint_wrong_kid_still_verifies_via_fallback():
    # A token labelled k2 but actually signed by k1 still verifies (kid only *orders*
    # candidates; the signature is what's authoritative).
    priv1, pub1 = _keypair()
    _, pub2 = _keypair()
    token = _sign(priv1, {"kid": "k2", "status": "active"})
    assert _verify_token(token, {"k1": pub1, "k2": pub2})["status"] == "active"


def test_untrusted_key_is_rejected():
    rogue, _ = _keypair()
    _, trusted_pub = _keypair()
    token = _sign(rogue, {"kid": "k1", "status": "active", "all_access": True})
    with pytest.raises(Exception):
        _verify_token(token, {"k1": trusted_pub})


def test_non_object_payload_is_rejected():
    priv, pub = _keypair()
    payload = json.dumps([1, 2, 3]).encode()
    token = _b64url(payload) + "." + _b64url(priv.sign(payload))
    with pytest.raises(ValueError):
        _verify_token(token, {"k1": pub})
