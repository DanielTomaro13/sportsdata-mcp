"""Auth providers — one per scheme. Selected by spec `auth.type`."""

from .afl import AFLTokenProvider
from .base import AuthProvider
from .header import StaticHeaderAuthProvider
from .none import NullAuthProvider

__all__ = ["AuthProvider", "AFLTokenProvider", "StaticHeaderAuthProvider", "NullAuthProvider"]
