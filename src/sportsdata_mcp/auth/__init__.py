"""Auth providers — one per scheme. Selected by spec `auth.type`."""

from .afl import AFLTokenProvider
from .base import AuthProvider
from .header import StaticHeaderAuthProvider
from .kalshi import KalshiRSASigner
from .none import NullAuthProvider
from .oauth import OAuthRefreshProvider
from .query import StaticQueryAuthProvider

__all__ = [
    "AuthProvider",
    "AFLTokenProvider",
    "StaticHeaderAuthProvider",
    "KalshiRSASigner",
    "StaticQueryAuthProvider",
    "NullAuthProvider",
    "OAuthRefreshProvider",
]
