"""Kalshi RSA request signing — the OPTIONAL authenticated tier.

Kalshi market data is public; an API key (key id + RSA private key) only raises
rate limits. So unlike every other scheme, missing credentials are NOT an error:
the signer constructs in *inactive* mode and signs nothing, leaving requests
anonymous. When both env vars are present, every request carries the
KALSHI-ACCESS-KEY / KALSHI-ACCESS-SIGNATURE / KALSHI-ACCESS-TIMESTAMP headers
(RSA-PSS-SHA256 over ``timestamp_ms + METHOD + path``, path without the query
string — per Kalshi's reference implementation).
"""

from __future__ import annotations

import base64
import os
import time
from pathlib import Path

from ..errors import AuthMissingError
from ..spec import AuthKalshiRSA


def _resolve(env_name: str | None, secrets: dict[str, str]) -> str | None:
    if not env_name:
        return None
    return os.environ.get(env_name) or secrets.get(env_name)


class KalshiRSASigner:
    """Per-request signer. ``active`` is False when no credentials are configured."""

    def __init__(self, spec: AuthKalshiRSA, secrets: dict[str, str] | None = None) -> None:
        secrets = secrets or {}
        self._spec = spec
        self._key_id = _resolve(spec.key_id_env, secrets)
        pem = _resolve(spec.private_key_env, secrets)
        key_path = _resolve(spec.private_key_path_env, secrets)
        if pem is None and key_path:
            pem = Path(key_path).expanduser().read_text()
        # Written as one branch rather than `bool(...)` then a separate conditional so
        # the "active implies both are present" invariant is CHECKED rather than merely
        # true: inside this branch the key id and PEM are known non-None, and a future
        # edit that breaks the pairing fails to type-check instead of failing at signing
        # time on someone's first authenticated call.
        if self._key_id and pem:
            self._private_key = self._load_key(pem)
            self.active = True
        else:
            self._private_key = None
            self.active = False

    @staticmethod
    def _load_key(pem: str):
        try:
            from cryptography.hazmat.primitives import serialization
        except ImportError as e:  # pragma: no cover — dev/test envs ship cryptography
            raise AuthMissingError(
                "Kalshi request signing needs the 'cryptography' package: pip install cryptography"
            ) from e
        return serialization.load_pem_private_key(pem.encode(), password=None)

    def sign_request(self, method: str, path: str) -> dict[str, str]:
        """Headers for one request; empty dict in anonymous mode."""
        key_id, private_key = self._key_id, self._private_key
        if not self.active or key_id is None or private_key is None:
            return {}
        from cryptography.hazmat.primitives import hashes
        from cryptography.hazmat.primitives.asymmetric import padding

        timestamp_ms = str(int(time.time() * 1000))
        message = timestamp_ms + method.upper() + path.split("?")[0]
        signature = private_key.sign(
            message.encode(),
            padding.PSS(mgf=padding.MGF1(hashes.SHA256()), salt_length=padding.PSS.DIGEST_LENGTH),
            hashes.SHA256(),
        )
        return {
            "KALSHI-ACCESS-KEY": key_id,
            "KALSHI-ACCESS-SIGNATURE": base64.b64encode(signature).decode(),
            "KALSHI-ACCESS-TIMESTAMP": timestamp_ms,
        }

    # AuthProvider protocol — used by doctor's mint check. In active mode this
    # proves the key id resolved and the PEM parsed; inactive mode is handled
    # by doctor via `active` before it ever calls get().
    async def get(self) -> tuple[str, str]:
        if not self.active:
            raise AuthMissingError(
                f"Kalshi auth not configured (optional): set {self._spec.key_id_env} and "
                f"{self._spec.private_key_env or self._spec.private_key_path_env} to sign requests"
            )
        return "KALSHI-ACCESS-KEY", self._key_id  # type: ignore[return-value]

    def invalidate(self) -> None:
        pass  # signatures are per-request; nothing cached to drop
