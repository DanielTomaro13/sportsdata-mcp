"""OAuth auth: short-lived access tokens, self-minted and auto-refreshed in memory."""

from __future__ import annotations

import asyncio
import logging
import os
import time

import httpx

from ..errors import AuthMissingError
from ..spec import AuthOAuthRefresh

log = logging.getLogger(__name__)


def _resolve(env_name: str | None, secrets: dict[str, str], *, what: str, required: bool = True) -> str | None:
    if not env_name:
        if required:
            raise AuthMissingError(f"spec is missing the env-name field for {what}")
        return None
    value = os.environ.get(env_name) or secrets.get(env_name)
    if not value and required:
        raise AuthMissingError(f"env var {env_name} not set (and no secrets['{env_name}']); required for {what}")
    return value


class OAuthRefreshProvider:
    """Mints access tokens via the configured grant; caches in memory only.

    - ``client_credentials`` (default): fully self-managing — every mint uses the
      client id/secret; nothing long-lived to harvest or rotate.
    - ``refresh_token``: refresh grant; if it dies and login creds are configured,
      falls back to the password grant (auto-harvest).
    - ``password``: mints directly from account credentials.

    Proactive refresh happens ``expiry_margin_seconds`` before ``expires_in``;
    reactive refresh rides the generic 401→``invalidate()``→retry loop in
    ``HTTPClient.request``. Nothing is persisted.
    """

    def __init__(self, spec: AuthOAuthRefresh, http: httpx.AsyncClient, secrets: dict[str, str] | None = None) -> None:
        secrets = secrets or {}
        self._spec = spec
        self._http = http
        self._client_id = _resolve(spec.client_id_env, secrets, what="the OAuth client id")
        self._client_secret = _resolve(spec.client_secret_env, secrets, what="the OAuth client secret")
        self._refresh_token = _resolve(
            spec.refresh_token_env, secrets, what="the OAuth refresh token",
            required=spec.grant == "refresh_token",
        )
        need_login = spec.grant == "password"
        self._username = _resolve(spec.username_env, secrets, what="the OAuth username", required=need_login)
        self._password = _resolve(spec.password_env, secrets, what="the OAuth password", required=need_login)
        self._access_token: str | None = None
        self._expires_at: float = 0.0
        self._lock = asyncio.Lock()

    async def get(self) -> tuple[str, str]:
        if self._access_token and time.monotonic() < self._expires_at:
            return self._spec.header, self._spec.value_prefix + self._access_token
        async with self._lock:
            if self._access_token and time.monotonic() < self._expires_at:
                return self._spec.header, self._spec.value_prefix + self._access_token
            await self._mint()
            assert self._access_token is not None
            return self._spec.header, self._spec.value_prefix + self._access_token

    def invalidate(self) -> None:
        self._access_token = None
        self._expires_at = 0.0

    async def _mint(self) -> None:
        if self._spec.grant == "client_credentials":
            r = await self._post_grant({"grant_type": "client_credentials"})
            if r.status_code >= 400:
                raise AuthMissingError(
                    f"OAuth client_credentials grant failed (HTTP {r.status_code}): {r.text[:200]} — "
                    f"check {self._spec.client_id_env}/{self._spec.client_secret_env}"
                )
            self._store(r.json())
            return

        if self._spec.grant == "password":
            await self._password_grant()
            return

        # refresh_token grant, with optional password-grant auto-harvest fallback
        r = await self._post_grant({"grant_type": "refresh_token", "refresh_token": self._refresh_token or ""})
        if r.status_code < 400:
            self._store(r.json())
            return
        body = r.text[:200]
        dead_grant = "invalid_grant" in body or "expired" in body.lower()
        if not dead_grant:
            raise AuthMissingError(f"OAuth refresh failed (HTTP {r.status_code}): {body}")
        if not (self._username and self._password):
            raise AuthMissingError(
                f"OAuth refresh rejected by {self._spec.token_url} (HTTP {r.status_code}): {body} — "
                f"the refresh token is expired/revoked; harvest a new one and update "
                f"{self._spec.refresh_token_env}"
            )
        log.warning("refresh token dead; auto-harvesting a new token pair via password grant")
        await self._password_grant()

    async def _password_grant(self) -> None:
        r = await self._post_grant(
            {"grant_type": "password", "username": self._username or "", "password": self._password or ""}
        )
        if r.status_code >= 400:
            raise AuthMissingError(
                f"OAuth password grant failed (HTTP {r.status_code}): {r.text[:200]} — "
                f"check {self._spec.username_env}/{self._spec.password_env}"
            )
        self._store(r.json())

    async def _post_grant(self, grant_fields: dict[str, str]) -> httpx.Response:
        # Form-encoded by contract — TAB's endpoint rejects JSON bodies outright.
        # Deliberately outside the provider's token-bucket rate limiter: a mint
        # happens at most once per token lifetime (~hours), not per data request.
        return await self._http.post(
            self._spec.token_url,
            data={**grant_fields, "client_id": self._client_id, "client_secret": self._client_secret},
        )

    def _store(self, payload: dict) -> None:
        token = payload.get("access_token")
        if not token:
            raise AuthMissingError(f"OAuth token response carried no access_token: keys={list(payload.keys())}")
        self._access_token = token
        expires_in = float(payload.get("expires_in", 3600))
        self._expires_at = time.monotonic() + max(expires_in - self._spec.expiry_margin_seconds, 30.0)
        rotated = payload.get("refresh_token")
        if rotated and rotated != self._refresh_token:
            self._refresh_token = rotated  # keep working this process lifetime
            if self._spec.grant == "refresh_token" and not (self._username and self._password):
                # Without a re-harvest path we cannot recover after restart — operator must act.
                log.warning(
                    "OAuth refresh token ROTATED by %s — update %s with the new value or "
                    "authentication will fail after this process exits",
                    self._spec.token_url,
                    self._spec.refresh_token_env,
                )
