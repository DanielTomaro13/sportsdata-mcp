"""AuthProvider protocol."""

from __future__ import annotations

from typing import Protocol


class AuthProvider(Protocol):
    """Returns (header_name, header_value) for the current request."""

    async def get(self) -> tuple[str, str]: ...

    def invalidate(self) -> None: ...
