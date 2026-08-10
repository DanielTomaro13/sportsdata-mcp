"""HTTP Basic auth.

Only one provider needs this so far (MySportsFeeds), but it is a standard scheme and
the alternative is asking users to base64-encode a credential pair by hand and paste it
into an env var — which is both unpleasant and impossible to validate, since a
mis-encoded string is indistinguishable from a wrong password until the 401 arrives.
"""

from __future__ import annotations

import base64
import os

from ..errors import AuthMissingError
from ..spec import AuthStaticBasic


class StaticBasicAuthProvider:
    def __init__(self, spec: AuthStaticBasic, secrets: dict[str, str] | None = None) -> None:
        secrets = secrets or {}
        username = os.environ.get(spec.username_env) or secrets.get(spec.username_env)
        if not username:
            raise AuthMissingError(
                f"env var {spec.username_env} not set (and no secrets['{spec.username_env}']); "
                f"required for HTTP Basic auth"
            )
        # Some APIs use a CONSTANT for one half of the pair — MySportsFeeds wants the
        # literal string "MYSPORTSFEEDS" as the password — so `password` may be a literal
        # in the spec, with `password_env` overriding it when the user has a real one.
        password = None
        if spec.password_env:
            password = os.environ.get(spec.password_env) or secrets.get(spec.password_env)
        if password is None:
            password = spec.password
        if password is None:
            raise AuthMissingError(
                f"auth.static_basic has neither `password` nor a set `password_env` "
                f"({spec.password_env})"
            )
        token = base64.b64encode(f"{username}:{password}".encode()).decode()
        self._value = f"Basic {token}"

    async def get(self) -> tuple[str, str]:
        return "Authorization", self._value

    def invalidate(self) -> None:
        pass
