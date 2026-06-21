"""Live re-validation (commerce): a long-running licensed server re-checks the
entitlement so a cancellation/downgrade takes effect mid-session — and the dispatch
guard refuses a tool whose group is no longer granted. A transient outage keeps the
current set (never knocks a paying customer offline)."""

import base64
import json

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from sportsdata_mcp import licence
from sportsdata_mcp.errors import ToolError
from sportsdata_mcp.licence import group_is_live, set_live_groups
from sportsdata_mcp.registry import _guard


def _b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


@pytest.fixture
def keypair():
    priv = Ed25519PrivateKey.generate()
    pub_raw = priv.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw
    )
    return priv, _b64url(pub_raw)


def _sign(priv, claims):
    payload = json.dumps(claims).encode()
    return _b64url(payload) + "." + _b64url(priv.sign(payload))


# ── live-state helpers ────────────────────────────────────────────────────


def test_unlicensed_is_inert():
    set_live_groups(None)
    assert group_is_live("anything") is True


def test_configured_set_scopes_liveness():
    set_live_groups(["mlb.reference"])
    assert group_is_live("mlb.reference") is True
    assert group_is_live("openf1.reference") is False


def test_empty_set_is_revoked_not_inert():
    set_live_groups([])
    assert group_is_live("mlb.reference") is False  # configured + revoked, not inert


# ── dispatch guard ────────────────────────────────────────────────────────


async def test_guard_refuses_revoked_group():
    async def handler(**kwargs):
        return {"ok": True}

    guarded = _guard(handler, "mlb_teams", "mlb.reference")

    set_live_groups(["mlb.reference"])
    assert await guarded() == {"ok": True}

    set_live_groups([])  # mid-session revocation
    with pytest.raises(ToolError) as exc:
        await guarded()
    assert "licence" in str(exc.value).lower()

    set_live_groups(None)  # unlicensed → guard inert again
    assert await guarded() == {"ok": True}


# ── _revalidate_groups (the confident/transient decision) ────────────────


@pytest.fixture
def reval_env(monkeypatch, tmp_path, keypair):
    priv, pub_b64 = keypair
    monkeypatch.setenv("SPORTSDATA_LICENSE", "sd_live_testkey0001")
    monkeypatch.setattr(licence, "BAKED_PUBKEY_B64", pub_b64)
    monkeypatch.setattr(licence, "_cache_path", lambda: tmp_path / "entitlement.json")

    def arm(claims=None, *, raise_fetch=False):
        def fake_fetch(url, key):
            if raise_fetch:
                raise RuntimeError("unreachable")
            if claims is None:
                return None
            c = {"key": "sd_live_testkey0001", **claims}
            return _sign(priv, c)

        monkeypatch.setattr(licence, "_fetch_token", fake_fetch)

    return arm


ALL = {"mlb.reference", "openf1.reference"}
PG = {"mlb": ["mlb.reference"], "openf1": ["openf1.reference"]}


def test_active_returns_current_grant(reval_env):
    reval_env({"status": "active", "all_access": False, "groups": ["mlb"]})
    assert licence._revalidate_groups(ALL, PG) == ["mlb.reference"]


def test_downgrade_shrinks_grant(reval_env):
    reval_env({"status": "active", "all_access": False, "groups": ["mlb.reference"]})
    assert licence._revalidate_groups(ALL, PG) == ["mlb.reference"]  # openf1 dropped


def test_cancelled_revokes_everything(reval_env):
    reval_env({"status": "canceled", "all_access": True, "groups": []})
    assert licence._revalidate_groups(ALL, PG) == []  # definitive revoke


def test_transient_outage_keeps_current(reval_env):
    """An unreachable service returns None → caller leaves the live set untouched."""
    reval_env(raise_fetch=True)
    assert licence._revalidate_groups(ALL, PG) is None


def test_key_mismatch_keeps_current(reval_env):
    reval_env({"status": "active", "all_access": True, "key": "sd_live_other"})
    assert licence._revalidate_groups(ALL, PG) is None  # not us → don't revoke


async def test_revalidate_once_applies_confident_result(reval_env):
    set_live_groups(["mlb.reference", "openf1.reference"])
    reval_env({"status": "canceled", "all_access": True})
    await licence.revalidate_once(ALL, PG)
    assert group_is_live("mlb.reference") is False  # revoked applied


async def test_revalidate_once_ignores_transient(reval_env):
    set_live_groups(["mlb.reference"])
    reval_env(raise_fetch=True)
    await licence.revalidate_once(ALL, PG)
    assert group_is_live("mlb.reference") is True  # kept on outage
