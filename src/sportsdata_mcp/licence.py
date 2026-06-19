"""Licence gate (commerce Phase 2).

When ``SPORTSDATA_LICENSE`` is set, the feed groups this server serves are decided by
the *signed entitlement* — fetched from the entitlement service, verified offline with
a baked Ed25519 public key, and cached for a grace window so a brief outage (or going
offline) does not knock a paying customer off their feeds.

The gate is **opt-in**: with no ``SPORTSDATA_LICENSE`` set, :func:`resolve_licensed_groups`
returns ``None`` and the server keeps whatever ``enabled_groups`` the config asked for —
so local/dev/unlicensed installs are completely unaffected.

When a licence *is* configured the gate **fails closed**: if the entitlement cannot be
fetched or verified and there is no usable cache, the server serves *no* feeds rather
than silently falling back to the configured groups.

Wire format (matches ``services/entitlement/src/sign.ts`` and the agents licensing
module): ``token = base64url(payloadJSON) + "." + base64url(signature)``, Ed25519 over
the exact payload bytes.
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import time
from pathlib import Path

log = logging.getLogger(__name__)

# Placeholder entitlement endpoint. NOTE: `wrangler deploy` publishes the Worker at
# `sportsdata-entitlement.<your-account>.workers.dev` (or a custom route) — NOT this bare
# host — so a licensed build MUST set SPORTSDATA_ENTITLEMENT_URL (or a custom domain).
# If it can't be reached the gate fails closed (serves nothing), never open.
DEFAULT_ENTITLEMENT_URL = "https://sportsdata-entitlement.workers.dev"

# Baked Ed25519 *public* key (raw, base64url) — the matching half of the entitlement
# service's signing key. Replace this with the `public` line printed by
# services/entitlement/gen-keypair.py before shipping a licensed build, or override at
# runtime with SPORTSDATA_ENTITLEMENT_PUBKEY. Empty here so unsigned/dev builds are
# obviously unconfigured rather than silently trusting a stranger's key.
BAKED_PUBKEY_B64 = ""

# How long a cached entitlement keeps a customer's feeds alive once we can no longer
# reach (or re-verify against) the service — and how far past `expires` we still honour
# a token. Matches the service-side issuance TTL philosophy: tolerant, not permanent.
GRACE_SECONDS = 7 * 24 * 3600

# How often a long-running server re-checks the entitlement so a cancellation/downgrade
# takes effect mid-session (not only at restart). 15 minutes.
REVALIDATE_SECONDS = 15 * 60

_FETCH_TIMEOUT = 8.0
_LIVE_STATUSES = {"active", "trialing", "past_due"}


# Providers that run on OUR upstream credential and must be routed through the
# entitlement service's proxy in a licensed build (the credential never ships locally).
# Only DataGolf today: TAB's public endpoints need no auth and run client-side.
PROXIED_PROVIDERS = {"datagolf"}


def proxy_base_for(provider_id: str) -> str | None:
    """If this provider should be routed through the entitlement proxy, return its
    ``…/proxy/<id>`` base; otherwise ``None``.

    Active only when a licence is configured and we have *no* local upstream credential
    for the provider — so a customer who supplies their own key still calls the upstream
    directly.
    """
    if provider_id not in PROXIED_PROVIDERS:
        return None
    if not os.environ.get("SPORTSDATA_LICENSE"):
        return None
    if provider_id == "datagolf" and os.environ.get("DATAGOLF_KEY"):
        return None  # customer's own DataGolf key — go direct
    url = os.environ.get("SPORTSDATA_ENTITLEMENT_URL", DEFAULT_ENTITLEMENT_URL)
    return f"{url.rstrip('/')}/proxy/{provider_id}"


def _b64url_decode(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def _cache_path() -> Path:
    return Path.home() / ".sportsdata" / "entitlement.json"


def _verify_token(token: str, pubkey_b64: str) -> dict:
    """Verify a signed entitlement token and return its claims. Raises on any failure."""
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

    payload_b64, sig_b64 = token.split(".", 1)
    payload = _b64url_decode(payload_b64)
    pub = Ed25519PublicKey.from_public_bytes(_b64url_decode(pubkey_b64))
    pub.verify(_b64url_decode(sig_b64), payload)  # raises InvalidSignature
    claims = json.loads(payload)
    if not isinstance(claims, dict):
        raise ValueError("entitlement payload is not an object")
    return claims


def _fetch_token(url: str, key: str) -> str | None:
    """GET the signed token from the entitlement service. Network/HTTP errors raise."""
    import httpx

    resp = httpx.get(
        f"{url.rstrip('/')}/entitlement",
        headers={"Authorization": f"Bearer {key}"},
        timeout=_FETCH_TIMEOUT,
    )
    resp.raise_for_status()
    token = resp.json().get("licence")
    return str(token) if token else None


def _save_cache(token: str) -> None:
    try:
        path = _cache_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"token": token, "fetched_at": int(time.time())}))
    except OSError as exc:  # cache is best-effort — never fatal
        log.debug("could not write entitlement cache: %s", exc)


def _load_cache() -> str | None:
    try:
        data = json.loads(_cache_path().read_text())
    except (OSError, ValueError):
        return None
    fetched_at = int(data.get("fetched_at", 0))
    if int(time.time()) - fetched_at >= GRACE_SECONDS:
        return None  # too stale to trust offline
    token = data.get("token")
    return str(token) if token else None


def _resolve_entitlement(key: str, url: str, pubkey_b64: str) -> dict | None:
    """Live fetch → verify → cache; on any failure fall back to a cached token within
    the grace window. Returns verified claims, or ``None`` if nothing usable."""
    token: str | None = None
    try:
        token = _fetch_token(url, key)
        if token:
            _save_cache(token)
    except Exception as exc:  # noqa: BLE001 — any fetch problem falls back to cache
        log.warning("entitlement fetch failed (%s) — falling back to cache", exc)

    if not token:
        token = _load_cache()
        if token:
            log.info("using cached entitlement (service unreachable)")
    if not token:
        return None

    try:
        claims = _verify_token(token, pubkey_b64)
    except Exception as exc:  # noqa: BLE001 — bad signature / malformed token
        log.warning("entitlement verification failed: %s", exc)
        return None

    # Bind the token to *this* licence: a valid signature is necessary but not
    # sufficient — the token's `key` claim must be the configured licence, so a cached
    # token issued for a different licence (the cache file is shared) is never honoured.
    if str(claims.get("key", "")) != key:
        log.warning("entitlement token is for a different licence key — ignoring")
        return None

    expires = int(claims.get("expires", 0))
    if expires and int(time.time()) - expires > GRACE_SECONDS:
        log.warning("entitlement expired beyond grace window")
        return None
    if str(claims.get("status", "")) not in _LIVE_STATUSES:
        log.warning("entitlement status %r is not active", claims.get("status"))
        return None
    return claims


def claims_to_groups(
    claims: dict,
    all_groups: set[str],
    provider_groups: dict[str, list[str]],
) -> list[str]:
    """Map verified entitlement claims to the concrete set of served group ids.

    ``all_access`` grants every group. Otherwise each entry in the entitlement's
    ``groups`` is matched as a full group id *or* a provider id (expanded to all of that
    provider's groups), then intersected with what this build actually ships.
    """
    if claims.get("all_access"):
        return sorted(all_groups)
    granted: set[str] = set()
    for entry in claims.get("groups") or []:
        if entry in all_groups:
            granted.add(entry)
        elif entry in provider_groups:
            granted.update(provider_groups[entry])
    return sorted(granted & all_groups)


def resolve_licensed_groups(
    all_groups: set[str],
    provider_groups: dict[str, list[str]],
) -> list[str] | None:
    """Groups the configured licence permits, or ``None`` when no licence is configured.

    ``None``  → no ``SPORTSDATA_LICENSE``; caller keeps its configured groups (opt-out).
    ``[]``    → licence configured but unresolvable / lapsed; caller serves nothing.
    ``[...]`` → the granted group ids (already intersected with this build's groups).
    """
    key = os.environ.get("SPORTSDATA_LICENSE")
    if not key:
        return None

    url = os.environ.get("SPORTSDATA_ENTITLEMENT_URL", DEFAULT_ENTITLEMENT_URL)
    pubkey_b64 = os.environ.get("SPORTSDATA_ENTITLEMENT_PUBKEY", BAKED_PUBKEY_B64)
    if not pubkey_b64:
        log.warning(
            "SPORTSDATA_LICENSE is set but no entitlement public key is configured "
            "(SPORTSDATA_ENTITLEMENT_PUBKEY / baked key) — serving no feeds"
        )
        return []

    claims = _resolve_entitlement(key, url, pubkey_b64)
    if claims is None:
        return []  # fail closed
    groups = claims_to_groups(claims, all_groups, provider_groups)
    log.info(
        "licence %s…: status=%s all_access=%s → %d group(s)",
        key[:12],
        claims.get("status"),
        bool(claims.get("all_access")),
        len(groups),
    )
    return groups


# ── Live re-validation ────────────────────────────────────────────────────
# A licensed build only resolves once at startup, so without this a cancellation or
# downgrade would keep serving until the next restart. build_server seeds the granted
# set; a background task in the lifespan refreshes it on a TTL; the dispatch guard
# consults group_is_live() per call. (Tools can only be *removed* at runtime, never
# added — gaining a feed still needs a restart, which the startup gate already handles.)

_live_state: dict = {"configured": False, "groups": set()}


def set_live_groups(groups: list[str] | None) -> None:
    """Seed/replace the currently-granted group set. ``None`` = no licence configured
    (the gate is inert and every group is live); ``[]`` = configured but revoked."""
    if groups is None:
        _live_state["configured"] = False
        _live_state["groups"] = set()
    else:
        _live_state["configured"] = True
        _live_state["groups"] = set(groups)


def group_is_live(group: str) -> bool:
    """Whether a tool in ``group`` may run right now. True when unlicensed (inert)."""
    if not _live_state["configured"]:
        return True
    return group in _live_state["groups"]


def _revalidate_groups(
    all_groups: set[str], provider_groups: dict[str, list[str]]
) -> list[str] | None:
    """A *live* re-check (no cache fallback) for a running server. Returns the freshly
    granted groups, ``[]`` on a definitive non-live status (revoke everything), or
    ``None`` to mean 'no confident answer — keep the current set' so a transient outage
    never knocks a paying customer offline mid-session."""
    key = os.environ.get("SPORTSDATA_LICENSE")
    if not key:
        return None
    url = os.environ.get("SPORTSDATA_ENTITLEMENT_URL", DEFAULT_ENTITLEMENT_URL)
    pubkey_b64 = os.environ.get("SPORTSDATA_ENTITLEMENT_PUBKEY", BAKED_PUBKEY_B64)
    if not pubkey_b64:
        return None
    try:
        token = _fetch_token(url, key)
    except Exception as exc:  # noqa: BLE001 — transient: keep current entitlement
        log.info("revalidation fetch failed (%s) — keeping current entitlement", exc)
        return None
    if not token:
        return None
    try:
        claims = _verify_token(token, pubkey_b64)
    except Exception as exc:  # noqa: BLE001 — unverifiable: keep current, don't revoke
        log.warning("revalidation verify failed: %s — keeping current entitlement", exc)
        return None
    if str(claims.get("key", "")) != key:
        return None
    if str(claims.get("status", "")) not in _LIVE_STATUSES:
        log.warning("entitlement no longer active (%s) — revoking feeds", claims.get("status"))
        return []
    _save_cache(token)
    return claims_to_groups(claims, all_groups, provider_groups)


async def revalidate_once(
    all_groups: set[str], provider_groups: dict[str, list[str]]
) -> None:
    """Refresh the live granted set once — the blocking fetch runs off the event loop."""
    groups = await asyncio.to_thread(_revalidate_groups, all_groups, provider_groups)
    if groups is not None:
        set_live_groups(groups)


async def revalidation_loop(
    all_groups: set[str], provider_groups: dict[str, list[str]]
) -> None:
    """Re-check the entitlement every ``REVALIDATE_SECONDS`` until cancelled."""
    while True:
        await asyncio.sleep(REVALIDATE_SECONDS)
        try:
            await revalidate_once(all_groups, provider_groups)
        except Exception as exc:  # noqa: BLE001 — never let the loop die
            log.warning("entitlement revalidation error: %s", exc)
