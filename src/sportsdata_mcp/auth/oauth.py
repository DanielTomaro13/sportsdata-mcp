"""OAuth refresh-token auth: short-lived access tokens, auto-refreshed in memory."""

from __future__ import annotations

import asyncio
import logging
import os
import time

import httpx

from ..errors import AuthMissingError
from ..spec import AuthOAuthRefresh

log = logging.getLogger(__name__)


def _resolve(env_name: str, secrets: dict[str, str], *, what: str) -> str:
    value = os.environ.get(env_name) or secrets.get(env_name)
    if not value:
        raise AuthMissingError(f"env var {env_name} not set (and no secrets['{env_name}']); required for {what}")
    return value


class OAuthRefreshProvider:
    """Mints access tokens from a refresh token; caches in memory only.

    - Proactive refresh: a token is treated as expired ``expiry_margin_seconds``
      before its ``expires_in`` elapses.
    - Reactive refresh: the request loop calls :meth:`invalidate` on a 401 and
      retries once (generic 401 handling in ``HTTPClient.request``).
    - Nothing is persisted. If the upstream ROTATES the refresh token, we keep
      working with the in-memory one but warn the operator to update the env var —
      the old one may stop working after this process exits.
    """

    def __init__(self, spec: AuthOAuthRefresh, http: httpx.AsyncClient, secrets: dict[str, str] | None = None) -> None:
        secrets = secrets or {}
        self._spec = spec
        self._http = http
        self._refresh_token = _resolve(spec.refresh_token_env, secrets, what="the OAuth refresh token")
        self._client_id = _resolve(spec.client_id_env, secrets, what="the OAuth client id")
        self._client_secret = _resolve(spec.client_secret_env, secrets, what="the OAuth client secret")
        self._access_token: str | None = None
        self._expires_at: float = 0.0
        self._lock = asyncio.Lock()

    async def get(self) -> tuple[str, str]:
        if self._access_token and time.monotonic() < self._expires_at:
            return self._spec.header, self._spec.value_prefix + self._access_token
        async with self._lock:
            if self._access_token and time.monotonic() < self._expires_at:
                return self._spec.header, self._spec.value_prefix + self._access_token
            await self._refresh()
            assert self._access_token is not None
            return self._spec.header, self._spec.value_prefix + self._access_token

    def invalidate(self) -> None:
        self._access_token = None
        self._expires_at = 0.0

    async def _refresh(self) -> None:
        # Form-encoded by contract — TAB's endpoint rejects JSON bodies outright.
        r = await self._http.post(
            self._spec.token_url,
            data={
                "grant_type": "refresh_token",
                "refresh_token": self._refresh_token,
                "client_id": self._client_id,
                "client_secret": self._client_secret,
            },
        )
        if r.status_code >= 400:
            body = r.text[:200]
            if "invalid_grant" in body or "expired" in body.lower():
                raise AuthMissingError(
                    f"OAuth refresh rejected by {self._spec.token_url} (HTTP {r.status_code}): {body} — "
                    f"the refresh token is expired/revoked; harvest a new one and update "
                    f"{self._spec.refresh_token_env}"
                )
            raise AuthMissingError(f"OAuth refresh failed (HTTP {r.status_code}): {body}")
        payload = r.json()
        token = payload.get("access_token")
        if not token:
            raise AuthMissingError(f"OAuth token response carried no access_token: keys={list(payload.keys())}")
        self._access_token = token
        expires_in = float(payload.get("expires_in", 3600))
        self._expires_at = time.monotonic() + max(expires_in - self._spec.expiry_margin_seconds, 30.0)
        rotated = payload.get("refresh_token")
        if rotated and rotated != self._refresh_token:
            self._refresh_token = rotated  # keep working this process lifetime
            log.warning(
                "OAuth refresh token ROTATED by %s — update %s with the new value or "
                "authentication will fail after this process exits",
                self._spec.token_url,
                self._spec.refresh_token_env,
            )
