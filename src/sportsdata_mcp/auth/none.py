"""No-op auth provider for endpoints that need nothing."""

from __future__ import annotations


class NullAuthProvider:
    async def get(self) -> tuple[str, str]:
        raise RuntimeError("NullAuthProvider.get called — caller should check auth type first")

    def invalidate(self) -> None:
        pass
