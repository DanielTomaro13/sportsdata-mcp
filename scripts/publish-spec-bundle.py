#!/usr/bin/env python
"""Build + sign the OTA spec bundle → dist/spec-bundle.json.

    SPORTSDATA_SPEC_PRIVKEY=<b64> python scripts/publish-spec-bundle.py [--version X] [--kid k1]

Packages the current packaged provider specs (src/sportsdata_mcp/specs/*.yaml) and signs
them with the spec-feed private key. Generate a keypair the same way as the entitlement
key (an Ed25519 raw keypair, base64url); keep the PUBLIC half baked into builds via
ota.BAKED_SPEC_PUBKEYS (keyed by --kid). Upload dist/spec-bundle.json as a release asset
and point SPORTSDATA_SPEC_FEED_URL at it; clients run `sportsdata-mcp update-specs`.

Use --kid to tag which signing key signed the bundle (rotation): bake the new pubkey under
that kid first, then publish with it. Omit --kid for an unkeyed/dev bundle.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

# run from a source checkout
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from sportsdata_mcp import __version__
from sportsdata_mcp.ota import build_bundle, sign_bundle
from sportsdata_mcp.spec_loader import packaged_specs_dir


def main() -> int:
    parser = argparse.ArgumentParser(description="Build + sign the OTA spec bundle.")
    parser.add_argument("--version", default=__version__, help="Bundle version label (default: package version).")
    parser.add_argument("--kid", default=None, help="Signing-key id to stamp (rotation); omit for unkeyed.")
    parser.add_argument("--out", default="dist/spec-bundle.json", help="Output path.")
    args = parser.parse_args()

    privkey = os.environ.get("SPORTSDATA_SPEC_PRIVKEY")
    if not privkey:
        print("error: set SPORTSDATA_SPEC_PRIVKEY (b64) — the spec-feed signing key", file=sys.stderr)
        return 1

    bundle = build_bundle(args.version, packaged_specs_dir(), kid=args.kid)
    signature = sign_bundle(bundle, privkey)
    doc = {"bundle": bundle, "signature": signature}

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(doc), encoding="utf-8")
    kid = f", kid={args.kid}" if args.kid else ""
    print(f"wrote {out}  (version {bundle['version']}, {len(bundle['files'])} specs{kid}, signed)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
