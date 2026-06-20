"""Licence gate (commerce Phase 2): when SPORTSDATA_LICENSE is set, the signed
entitlement decides which feed groups the server serves. Opt-in + fail-closed."""

import base64
import json
import time

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from sportsdata_mcp import licence
from sportsdata_mcp.config import Config
from sportsdata_mcp.licence import claims_to_groups, resolve_licensed_groups
from sportsdata_mcp.server import build_server


def _b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


@pytest.fixture
def keypair():
    """A throwaway Ed25519 keypair: signs tokens like the entitlement service, and the
    raw-base64url public key the gate verifies against."""
    priv = Ed25519PrivateKey.generate()
    pub_raw = priv.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw
    )
    return priv, _b64url(pub_raw)


def _sign(priv: Ed25519PrivateKey, claims: dict) -> str:
    payload = json.dumps(claims).encode()
    return _b64url(payload) + "." + _b64url(priv.sign(payload))


@pytest.fixture
def gate_env(monkeypatch, tmp_path, keypair):
    """Configure a licence + verify key, route the cache to a temp file, and return a
    helper that arms the (monkeypatched) entitlement fetch with given claims."""
    priv, pub_b64 = keypair
    monkeypatch.setenv("SPORTSDATA_LICENSE", "sd_live_testkey0001")
    monkeypatch.setenv("SPORTSDATA_ENTITLEMENT_PUBKEY", pub_b64)
    monkeypatch.setenv("SPORTSDATA_ENTITLEMENT_URL", "https://example.invalid")
    monkeypatch.setattr(licence, "_cache_path", lambda: tmp_path / "entitlement.json")

    def arm(claims: dict | None, *, raise_fetch: bool = False):
        def fake_fetch(url: str, key: str):
            if raise_fetch:
                raise RuntimeError("service unreachable")
            if claims is None:
                return None
            # The gate binds the token to the configured licence; default the `key`
            # claim to match so tests exercise group/status logic (a test can still
            # pass an explicit mismatching `key` to check the binding).
            c = {"key": "sd_live_testkey0001", **claims}
            return _sign(priv, c)

        monkeypatch.setattr(licence, "_fetch_token", fake_fetch)

    return arm


# ── resolve_licensed_groups ──────────────────────────────────────────────


def test_no_licence_returns_none(monkeypatch):
    """No SPORTSDATA_LICENSE → gate is inert; caller keeps configured groups."""
    monkeypatch.delenv("SPORTSDATA_LICENSE", raising=False)
    assert resolve_licensed_groups({"mlb.reference"}, {"mlb": ["mlb.reference"]}) is None


def test_explicit_groups_scope_server(gate_env):
    gate_env({"status": "active", "all_access": False, "groups": ["mlb.reference"]})
    _, reg = build_server(Config(enabled_groups=[]))
    assert "mlb_teams" in reg.tools
    assert "openf1_sessions" not in reg.tools


def test_provider_id_expands_to_its_groups(gate_env):
    """A bare provider id in the entitlement grants every group of that provider."""
    gate_env({"status": "active", "all_access": False, "groups": ["mlb"]})
    _, reg = build_server(Config(enabled_groups=[]))
    assert "mlb_teams" in reg.tools
    assert "openf1_sessions" not in reg.tools


def test_all_access_grants_everything(gate_env):
    gate_env({"status": "active", "all_access": True, "groups": []})
    _, reg = build_server(Config(enabled_groups=[]))
    assert "mlb_teams" in reg.tools
    assert "openf1_sessions" in reg.tools
    assert len(reg.tools) > 300


def test_licence_is_a_ceiling_config_can_narrow(gate_env):
    """A configured group list narrows *within* the licence but cannot exceed it."""
    gate_env({"status": "active", "all_access": True, "groups": []})
    _, reg = build_server(Config(enabled_groups=["mlb.reference"]))
    assert "mlb_teams" in reg.tools
    assert "openf1_sessions" not in reg.tools


def test_config_cannot_exceed_licence(gate_env):
    """Configuring a group the licence does not grant yields nothing for it."""
    gate_env({"status": "active", "all_access": False, "groups": ["mlb.reference"]})
    _, reg = build_server(Config(enabled_groups=["openf1.reference"]))
    assert "openf1_sessions" not in reg.tools
    assert "mlb_teams" not in reg.tools  # not in the configured narrow set either


def test_fail_closed_when_unresolvable(gate_env):
    """Licence set but the service is down and there is no cache → serve no feeds."""
    gate_env(None, raise_fetch=True)
    groups = resolve_licensed_groups({"mlb.reference"}, {"mlb": ["mlb.reference"]})
    assert groups == []


def test_inactive_status_serves_nothing(gate_env):
    gate_env({"status": "canceled", "all_access": True, "groups": []})
    groups = resolve_licensed_groups({"mlb.reference"}, {"mlb": ["mlb.reference"]})
    assert groups == []


def test_expired_token_serves_nothing(gate_env):
    """A token past its own `expires` is rejected (no 7-day extra grace on top)."""
    gate_env({"status": "active", "all_access": True, "expires": int(time.time()) - 10 * 24 * 3600})
    assert resolve_licensed_groups({"mlb.reference"}, {"mlb": ["mlb.reference"]}) == []


def test_past_billing_period_serves_nothing(gate_env):
    """Even with a far-future `expires`, a token past `current_period_end` is rejected —
    so a cached token can't outlive the paid subscription."""
    now = int(time.time())
    gate_env({
        "status": "active", "all_access": True,
        "expires": now + 999_999, "current_period_end": now - 10_000,
    })
    assert resolve_licensed_groups({"mlb.reference"}, {"mlb": ["mlb.reference"]}) == []


def test_token_for_a_different_licence_rejected(gate_env):
    """A correctly-signed token whose `key` claim is a different licence is ignored —
    guards the shared offline cache against cross-licence reuse."""
    gate_env({"status": "active", "all_access": True, "key": "sd_live_someoneelse"})
    assert resolve_licensed_groups({"mlb.reference"}, {"mlb": ["mlb.reference"]}) == []


def test_bad_signature_rejected(monkeypatch, tmp_path, keypair):
    """A token signed by a different key must not verify."""
    _, pub_b64 = keypair
    other = Ed25519PrivateKey.generate()
    monkeypatch.setenv("SPORTSDATA_LICENSE", "sd_live_testkey0001")
    monkeypatch.setenv("SPORTSDATA_ENTITLEMENT_PUBKEY", pub_b64)
    monkeypatch.setattr(licence, "_cache_path", lambda: tmp_path / "entitlement.json")
    token = _sign(other, {"status": "active", "all_access": True})
    monkeypatch.setattr(licence, "_fetch_token", lambda url, key: token)
    assert resolve_licensed_groups({"mlb.reference"}, {"mlb": ["mlb.reference"]}) == []


def test_missing_pubkey_serves_nothing(monkeypatch):
    monkeypatch.setenv("SPORTSDATA_LICENSE", "sd_live_testkey0001")
    monkeypatch.setenv("SPORTSDATA_ENTITLEMENT_PUBKEY", "")
    monkeypatch.setattr(licence, "BAKED_PUBKEY_B64", "")
    assert resolve_licensed_groups({"mlb.reference"}, {}) == []


# ── claims_to_groups (pure mapping) ──────────────────────────────────────


def test_claims_to_groups_intersects_with_build():
    all_groups = {"mlb.reference", "openf1.reference"}
    pg = {"mlb": ["mlb.reference"], "openf1": ["openf1.reference"]}
    # provider id + a group the build does not ship are both handled
    claims = {"groups": ["mlb", "nonexistent.group"]}
    assert claims_to_groups(claims, all_groups, pg) == ["mlb.reference"]


def test_caching_survives_outage(gate_env, monkeypatch):
    """A good fetch is cached; a later outage falls back to the cached entitlement."""
    gate_env({"status": "active", "all_access": False, "groups": ["mlb.reference"]})
    assert resolve_licensed_groups({"mlb.reference"}, {"mlb": ["mlb.reference"]}) == [
        "mlb.reference"
    ]
    # service now down, but the cached token is still within grace
    monkeypatch.setattr(
        licence, "_fetch_token", lambda url, key: (_ for _ in ()).throw(RuntimeError("down"))
    )
    assert resolve_licensed_groups({"mlb.reference"}, {"mlb": ["mlb.reference"]}) == [
        "mlb.reference"
    ]
