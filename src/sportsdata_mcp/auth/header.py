"""Static-header auth (literal value or env-var-sourced)."""

from __future__ import annotations

import os

from ..errors import AuthMissingError
from ..spec import AuthStaticHeader


class StaticHeaderAuthProvider:
    def __init__(self, spec: AuthStaticHeader) -> None:
        if spec.env:
            value = os.environ.get(spec.env)
            if value is None:
                raise AuthMissingError(f"env var {spec.env} not set; required for header {spec.header}")
            self._value = value
        elif spec.value is not None:
            self._value = spec.value
        else:
            raise AuthMissingError(f"auth.static_header for header '{spec.header}' has neither `value` nor `env`")
        self._header = spec.header

    async def get(self) -> tuple[str, str]:
        return self._header, self._value

    def invalidate(self) -> None:
        pass
