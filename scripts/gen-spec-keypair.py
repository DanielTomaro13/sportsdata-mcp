#!/usr/bin/env python
"""Generate an Ed25519 keypair for signing OTA spec bundles.

    python scripts/gen-spec-keypair.py

Prints a PRIVATE key (keep it OFFLINE — it's used only at publish time as the
``SPORTSDATA_SPEC_PRIVKEY`` env var for ``scripts/publish-spec-bundle.py``) and a PUBLIC
key (bake it into ``src/sportsdata_mcp/ota.py`` → ``BAKED_SPEC_PUBKEYS`` under a kid, e.g.
``"k1"``). Run this once. To ROTATE later: generate a fresh pair, add the new public key
under a new kid (``"k2"``) in a release that ships BEFORE you switch, then publish bundles
with ``--kid k2``; drop the old entry once its bundles are gone.

The private key never belongs in git, the binary, or a chat — only in your release shell.
"""

from __future__ import annotations

import sys
from pathlib import Path

# run from a source checkout
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from sportsdata_mcp.ota import _b64url_encode


def main() -> int:
    priv = Ed25519PrivateKey.generate()
    priv_b64 = _b64url_encode(
        priv.private_bytes(
            serialization.Encoding.Raw, serialization.PrivateFormat.Raw, serialization.NoEncryption()
        )
    )
    pub_b64 = _b64url_encode(
        priv.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    )
    print("# OTA spec-signing keypair — KEEP THE PRIVATE KEY OFFLINE.\n")
    print("# 1) Publish side (never commit) — export before running publish-spec-bundle.py:")
    print(f"export SPORTSDATA_SPEC_PRIVKEY={priv_b64}\n")
    print("# 2) Bake the PUBLIC key into src/sportsdata_mcp/ota.py:")
    print(f'#    BAKED_SPEC_PUBKEYS: dict[str, str] = {{"k1": "{pub_b64}"}}')
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
