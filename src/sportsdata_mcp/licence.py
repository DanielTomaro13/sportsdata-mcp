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

# The deployed entitlement Worker. Override per-install with SPORTSDATA_ENTITLEMENT_URL.
# If it can't be reached the gate fails closed (serves nothing), never open.
DEFAULT_ENTITLEMENT_URL = "https://sportsdata-entitlement.sportsdata.workers.dev"

# Baked Ed25519 *public* key (raw, base64url) — the matching half of the entitlement
# service's signing key (services/entitlement/gen-keypair.py). This is the CURRENT key,
# tagged kid "k1" (the Worker stamps the same kid on the tokens it signs).
BAKED_PUBKEY_B64 = "Vc1niiTDDyWM7Es7pvGdS1Bne9k9nDIMKFhJYiHT0e8"

# Additional trusted verify keys by `kid`, for rotating the signing key WITHOUT a flag-day.
# To rotate: (1) ship a build that trusts both the current key and the next one by adding
# the next here (e.g. {"k2": "<new pubkey>"}); (2) once customers have that build, switch
# the Worker to sign with the new private key + SIGNING_KID="k2" — its tokens carry kid
# "k2" and verify against this entry, while older "k1"/kid-less tokens keep verifying; (3)
# drop the stale entry once every token signed by it has expired. An unknown/absent kid
# falls back to trying every trusted key, so a legacy kid-less token still verifies.
EXTRA_BAKED_PUBKEYS: dict[str, str] = {}


def _entitlement_pubkeys() -> dict[str, str]:
    """The Ed25519 verify keys the gate trusts, as ``{kid: base64url-pubkey}``.

    Security: when a key is BAKED IN (the shipped product), the env override is IGNORED —
    otherwise a self-hoster could substitute their own keypair, point SPORTSDATA_ENTITLEMENT_URL
    at a Worker they control, and mint an all-access token that verifies (a complete bypass).
    The env override is honoured ONLY in unbaked dev/source builds (empty BAKED_PUBKEY_B64),
    where it's needed to test against a local entitlement service.
    """
    if BAKED_PUBKEY_B64:
        return {"k1": BAKED_PUBKEY_B64, **EXTRA_BAKED_PUBKEYS}
    env = os.environ.get("SPORTSDATA_ENTITLEMENT_PUBKEY", "")
    return {"env": env} if env else {}

# How long a cached entitlement keeps a customer's feeds alive once we can no longer
# reach (or re-verify against) the service — and how far past `expires` we still honour
# a token. Matches the service-side issuance TTL philosophy: tolerant, not permanent.
GRACE_SECONDS = 7 * 24 * 3600  # how long a cached token keeps feeds alive *since fetch*,
#                               capped by the token's own `expires` (no double-counting)
_CLOCK_SKEW = 3600  # tolerance on expiry / period-end checks for clock skew

# How often a long-running server re-checks the entitlement so a cancellation/downgrade
# takes effect mid-session (not only at restart). 15 minutes.
REVALIDATE_SECONDS = 15 * 60

_FETCH_TIMEOUT = 8.0
_LIVE_STATUSES = {"active", "trialing", "past_due"}


def proxy_base_for(
    provider_id: str, *, proxied: bool = False, byo_key_env: str | None = None
) -> str | None:
    """If this provider should be routed through the entitlement proxy, return its
    ``…/proxy/<id>`` base; otherwise ``None``.

    `proxied`/`byo_key_env` are spec fields (``provider.proxied`` / ``provider.byo_key_env``)
    so adding a credentialed provider is DATA, not a hardcoded set here. Active only when a
    licence is configured and we have *no* local upstream credential — a customer who
    supplies their own key (``byo_key_env`` set) still calls the upstream directly.
    """
    if not proxied:
        return None
    if not os.environ.get("SPORTSDATA_LICENSE"):
        return None
    if byo_key_env and os.environ.get(byo_key_env):
        return None  # customer's own key — go direct
    url = os.environ.get("SPORTSDATA_ENTITLEMENT_URL", DEFAULT_ENTITLEMENT_URL)
    return f"{url.rstrip('/')}/proxy/{provider_id}"


def _b64url_decode(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def _cache_path() -> Path:
    return Path.home() / ".sportsdata" / "entitlement.json"


def _verify_token(token: str, trusted: dict[str, str]) -> dict:
    """Verify a signed entitlement token against any trusted key and return its claims.

    ``trusted`` is ``{kid: base64url-pubkey}``. The token's ``kid`` claim selects which key
    to try first (the rotation fast path); we then fall back to every other trusted key, so
    a legacy kid-less token — or one minted during a rotation — still verifies. Raises if no
    trusted key verifies the signature, or the payload isn't a JSON object."""
    from cryptography.exceptions import InvalidSignature
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

    payload_b64, sig_b64 = token.split(".", 1)
    payload = _b64url_decode(payload_b64)
    sig = _b64url_decode(sig_b64)
    claims = json.loads(payload)
    if not isinstance(claims, dict):
        # ValueError, not TypeError: this is a malformed *value* decoded from an
        # untrusted token, not a caller passing the wrong argument type.
        raise ValueError("entitlement payload is not an object")  # noqa: TRY004

    kid = str(claims.get("kid", "")) or None
    order = ([trusted[kid]] if kid and kid in trusted else []) + [
        v for k, v in trusted.items() if not (kid and k == kid)
    ]
    last_exc: Exception | None = None
    for pubkey_b64 in order:
        try:
            Ed25519PublicKey.from_public_bytes(_b64url_decode(pubkey_b64)).verify(sig, payload)
            return claims
        except (InvalidSignature, ValueError) as exc:  # try the next trusted key
            last_exc = exc
    raise last_exc or ValueError("no trusted entitlement key verified the token")


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
        # The cache holds a signed bearer token at rest; keep the dir + file owner-only
        # (the cache path is shared, so don't leave it world-readable to other local users).
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        path.write_text(json.dumps({"token": token, "fetched_at": int(time.time())}))
        os.chmod(path, 0o600)
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


def _resolve_entitlement(key: str, url: str, trusted: dict[str, str]) -> dict | None:
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
        claims = _verify_token(token, trusted)
    except Exception as exc:  # noqa: BLE001 — bad signature / malformed token
        log.warning("entitlement verification failed: %s", exc)
        return None

    # Bind the token to *this* licence: a valid signature is necessary but not
    # sufficient — the token's `key` claim must be the configured licence, so a cached
    # token issued for a different licence (the cache file is shared) is never honoured.
    if str(claims.get("key", "")) != key:
        log.warning("entitlement token is for a different licence key — ignoring")
        return None

    # Honour the token's own `expires` strictly (only a small clock-skew tolerance) — the
    # offline window is the cache-age grace (GRACE_SECONDS since fetch) capped by this, so
    # the two don't compound. The service bounds `expires` to the paid period, and we also
    # enforce `current_period_end` directly, so a cached token can't outlive the
    # subscription even against an older service that didn't bound `expires`.
    now = int(time.time())
    expires = int(claims.get("expires", 0))
    if expires and now > expires + _CLOCK_SKEW:
        log.warning("entitlement token has expired")
        return None
    period_end = int(claims.get("current_period_end", 0))
    if period_end and now > period_end + _CLOCK_SKEW:
        log.warning("entitlement is past its billing period")
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
    trusted = _entitlement_pubkeys()
    if not trusted:
        log.warning(
            "SPORTSDATA_LICENSE is set but no entitlement public key is configured "
            "(SPORTSDATA_ENTITLEMENT_PUBKEY / baked key) — serving no feeds"
        )
        return []

    claims = _resolve_entitlement(key, url, trusted)
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
    trusted = _entitlement_pubkeys()
    if not trusted:
        return None
    try:
        token = _fetch_token(url, key)
    except Exception as exc:  # noqa: BLE001 — transient: keep current entitlement
        log.info("revalidation fetch failed (%s) — keeping current entitlement", exc)
        return None
    if not token:
        return None
    try:
        claims = _verify_token(token, trusted)
    except Exception as exc:  # noqa: BLE001 — unverifiable: keep current, don't revoke
        log.warning("revalidation verify failed: %s — keeping current entitlement", exc)
        return None
    if str(claims.get("key", "")) != key:
        return None
    # Mirror the startup path's strict checks: a freshly-fetched token that is expired or
    # past its billing period is a DEFINITIVE lapse (revoke), not a transient outage. Without
    # these a long-lived server kept serving past period-end whenever status stayed "active".
    now = int(time.time())
    expires = int(claims.get("expires", 0))
    if expires and now > expires + _CLOCK_SKEW:
        log.warning("entitlement token has expired — revoking feeds")
        return []
    period_end = int(claims.get("current_period_end", 0))
    if period_end and now > period_end + _CLOCK_SKEW:
        log.warning("entitlement is past its billing period — revoking feeds")
        return []
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
