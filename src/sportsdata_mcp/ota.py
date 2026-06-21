"""OTA spec updates — refresh provider SPECS between releases.

Provider specs are DATA that drifts: books rotate GraphQL persisted-query hashes (Entain
especially), move endpoints, add params. The standalone (Base-SKU) MCP otherwise needs a
whole new build to track a hash change — the slow path the downloadable-app model imposes.
This packages the packaged specs as a SIGNED bundle a running install fetches and applies
into an OVERLAY under ``~/.sportsdata/spec-overlay`` — which the spec loader prefers over
the packaged copy.

Trust model mirrors the licence gate: an Ed25519 detached signature over the canonical
bundle, verified offline against a baked SPEC pubkey SET (kid-aware, so the signing key can
rotate without a flag-day — see ``licence.py``). No baked key (source/dev build) → an
unverified apply is allowed with a loud warning; a product build with a key REFUSES an
unsigned/forged bundle. The only network call is the fetch the user explicitly runs
(``sportsdata-mcp update-specs``).

Publish with ``scripts/publish-spec-bundle.py`` (signs with the matching private key),
upload the result as a release asset, point ``--url`` / ``SPORTSDATA_SPEC_FEED_URL`` at it.
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
import re
from pathlib import Path
from typing import Any

log = logging.getLogger("sportsdata_mcp.ota")

SCHEMA = 1
SPEC_FEED_URL_ENV = "SPORTSDATA_SPEC_FEED_URL"
SPEC_PUBKEY_ENV = "SPORTSDATA_SPEC_PUBKEY"

# A bundle file name must be exactly a provider spec — same shape as a provider id + .yaml.
# Whitelisting (not blacklisting) blocks dotfiles, ``_``-prefixed, path separators, and odd
# unicode in one rule, so nothing but a real ``{provider}.yaml`` is ever written.
_VALID_SPEC_NAME = re.compile(r"[a-z][a-z0-9_]*\.yaml")
# A version must start with a digit so date ('2026-06-22') and semver ('1.10.0') both order
# numerically via _version_key — and a blank/garbage version can't slip past anti-rollback.
_VALID_VERSION = re.compile(r"[0-9][0-9A-Za-z._\-]*")
# Specs are small text; cap the fetched bundle well above any real size, BEFORE verifying,
# so a hostile/compromised feed host can't exhaust memory with a giant or unbounded body.
MAX_BUNDLE_BYTES = 8 * 1024 * 1024

# Baked Ed25519 verify keys for spec bundles, by kid. Empty until a key is baked at release;
# until then a product build can't OTA-update (no trust anchor) and a dev/source build
# applies UNVERIFIED with a warning. Kid-aware so the signing key rotates the same way the
# entitlement key does (licence.py: ship trust for the next key, switch the issuer, retire).
# Generate a keypair with `python scripts/gen-spec-keypair.py` and paste the PUBLIC half
# here, e.g. {"k1": "<base64url-pubkey>"}; keep the private half offline (publish only).
BAKED_SPEC_PUBKEYS: dict[str, str] = {}


class SpecFeedError(RuntimeError):
    """A spec bundle could not be verified or applied (bad signature/sha/schema/rollback)."""


def _b64url_decode(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def _b64url_encode(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


# ── overlay seam the spec loader consults ────────────────────────────────────


def _overlay_dir() -> Path:
    # Shares the ~/.sportsdata home with the licence cache; owner-only (created 0700 on apply).
    return Path.home() / ".sportsdata" / "spec-overlay"


def applied_version() -> str | None:
    """Version of the currently-applied spec overlay, or None (running packaged specs)."""
    marker = _overlay_dir() / "VERSION"
    return marker.read_text(encoding="utf-8").strip() if marker.is_file() else None


def overlay_spec_sources() -> dict[str, str]:
    """``{filename: yaml-text}`` for each applied overlay provider spec. THIS is the seam
    ``spec_loader.load_all_specs`` merges over the packaged specs. A corrupt/unreadable
    overlay file is skipped (the packaged copy wins) — an overlay must never break startup."""
    out: dict[str, str] = {}
    overlay = _overlay_dir()
    if not overlay.is_dir():
        return out
    for path in sorted(overlay.glob("*.yaml")):
        if path.name.startswith("_"):
            continue
        try:
            out[path.name] = path.read_text(encoding="utf-8")
        except OSError as e:
            log.warning("spec overlay %s unreadable, using packaged: %s", path.name, e)
    return out


def _trusted_pubkeys() -> dict[str, str]:
    """Trusted spec-bundle verify keys ``{kid: pubkey}``. Baked set wins (product); else the
    env override (dev). Empty = no trust anchor (dev applies unverified; product can't update)."""
    if BAKED_SPEC_PUBKEYS:
        return dict(BAKED_SPEC_PUBKEYS)
    env = os.environ.get(SPEC_PUBKEY_ENV, "")
    return {"env": env} if env else {}


# ── bundle build / sign / verify (Ed25519) ───────────────────────────────────


def _canonical_bytes(bundle: dict[str, Any]) -> bytes:
    return json.dumps(bundle, sort_keys=True, separators=(",", ":")).encode("utf-8")


def build_bundle(version: str, specs_dir: Path, *, kid: str | None = None) -> dict[str, Any]:
    """Package every provider spec (``{provider}.yaml``) under ``specs_dir`` into a bundle
    dict (publish side). ``_``-prefixed files (e.g. ``_capabilities.yaml``) are excluded."""
    files: dict[str, Any] = {}
    for path in sorted(specs_dir.glob("*.yaml")):
        if path.name.startswith("_"):
            continue
        content = path.read_text(encoding="utf-8")
        files[path.name] = {
            "sha256": hashlib.sha256(content.encode("utf-8")).hexdigest(),
            "content": content,
        }
    bundle: dict[str, Any] = {"schema": SCHEMA, "version": str(version), "files": files}
    if kid:  # tag the signing key for rotation; omit for the legacy/dev single-key case
        bundle["kid"] = kid
    return bundle


def sign_bundle(bundle: dict[str, Any], private_key_b64: str) -> str:
    """Detached Ed25519 signature (b64url) over the canonical bundle bytes."""
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    key = Ed25519PrivateKey.from_private_bytes(_b64url_decode(private_key_b64))
    return _b64url_encode(key.sign(_canonical_bytes(bundle)))


def verify_bundle(bundle: dict[str, Any], signature_b64: str, trusted: dict[str, str]) -> bool:
    """True iff ``signature_b64`` verifies over the canonical bundle under any trusted key.
    The bundle's ``kid`` orders which key to try first; falls back to the rest (rotation)."""
    from cryptography.exceptions import InvalidSignature
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

    msg = _canonical_bytes(bundle)
    try:
        sig = _b64url_decode(signature_b64)
    except Exception:  # noqa: BLE001 — malformed signature is just "doesn't verify"
        return False
    kid = str(bundle.get("kid", "")) or None
    order = ([trusted[kid]] if kid and kid in trusted else []) + [
        v for k, v in trusted.items() if not (kid and k == kid)
    ]
    for pub_b64 in order:
        try:
            Ed25519PublicKey.from_public_bytes(_b64url_decode(pub_b64)).verify(sig, msg)
            return True
        except (InvalidSignature, ValueError):
            continue
    return False


# ── apply (client side) ──────────────────────────────────────────────────────


def _version_key(v: str) -> tuple:
    """Natural-sort key so dates ('2026-06-15') and semver ('1.10.0' > '1.9.0') both order."""
    import re

    return tuple(int(t) if t.isdigit() else t for t in re.findall(r"\d+|\D+", v or ""))


def _validate_spec_text(text: str, name: str) -> None:
    """Parse ``text`` as a Spec — raises before we commit a malformed overlay that would
    otherwise break the next server start."""
    from .spec_loader import load_spec_text

    load_spec_text(text, name)


def apply_bundle(bundle: dict[str, Any]) -> dict[str, Any]:
    """Write the specs in a verified bundle to the overlay dir. Entries must be
    ``{provider}.yaml``; anything else is skipped (forward-compatible). The whole bundle is
    sha256- and Spec-validated FIRST, then written — so a single bad file leaves the overlay
    untouched (no torn-bundle state). Anti-rollback refuses a missing/blank/older version (a
    signed-but-stale replay can't revert specs)."""
    if bundle.get("schema") != SCHEMA:
        raise SpecFeedError(f"unsupported bundle schema {bundle.get('schema')!r} (expected {SCHEMA})")

    # A version is mandatory and must be digit-led, so it always orders numerically (an empty
    # or garbage version would otherwise slip past — and blanking the stored VERSION would
    # disable anti-rollback for good).
    new_v = str(bundle.get("version", "")).strip()
    if not _VALID_VERSION.fullmatch(new_v):
        raise SpecFeedError(f"bundle version {new_v!r} is missing or not a valid version")
    cur_v = applied_version()
    if cur_v:
        try:
            older = _version_key(new_v) < _version_key(cur_v)
        except TypeError:
            # Unorderable across version schemes — REFUSE rather than fall back to a
            # lexicographic compare (which isn't a valid ordering and could pass a rollback).
            raise SpecFeedError(
                f"cannot compare version {new_v!r} with applied {cur_v!r} — use one version scheme"
            ) from None
        if older:
            raise SpecFeedError(
                f"bundle version {new_v!r} is older than the applied {cur_v!r} — refusing rollback"
            )

    # Phase 1: validate EVERY file (sha256 + parses as a Spec) before touching the overlay.
    validated: dict[str, str] = {}
    for name, rec in (bundle.get("files") or {}).items():
        if not _VALID_SPEC_NAME.fullmatch(name):
            log.warning("bundle carries unexpected file %r — skipping", name)
            continue
        content = str(rec.get("content", ""))
        if hashlib.sha256(content.encode("utf-8")).hexdigest() != rec.get("sha256"):
            raise SpecFeedError(f"sha256 mismatch for {name} — refusing to apply a corrupt bundle")
        _validate_spec_text(content, name)  # malformed spec aborts the WHOLE apply, before any write
        validated[name] = content

    # Phase 2: everything checked — write atomically (tmp + replace), VERSION last.
    overlay = _overlay_dir()
    overlay.mkdir(parents=True, exist_ok=True, mode=0o700)
    for name, content in validated.items():
        tmp = overlay / f".{name}.tmp"
        tmp.write_text(content, encoding="utf-8")
        tmp.replace(overlay / name)  # atomic swap — no torn file on crash
    (overlay / "VERSION").write_text(new_v, encoding="utf-8")
    return {"applied": sorted(validated), "version": new_v}


def fetch_and_apply(url: str, *, trusted: dict[str, str] | None = None) -> dict[str, Any]:
    """Fetch ``{bundle, signature}`` from ``url``, verify, and apply. With a trust anchor a
    bad signature is fatal; with none, applies UNVERIFIED with a warning (dev/source only —
    a product build always bakes the key)."""
    import urllib.request

    trust = _trusted_pubkeys() if trusted is None else trusted
    # Only http(s) — block file://, ftp://, etc. so a feed URL can't read a local file.
    scheme = url.split(":", 1)[0].lower()
    if scheme not in ("https", "http"):
        raise SpecFeedError(f"unsupported spec feed URL scheme {scheme!r} — use https")
    if scheme == "http":
        # A product build (baked key) must never pull the feed over plaintext: the signature
        # protects integrity, but http leaks WHICH specs the install fetches and eases a
        # downgrade/MITM. Hard-reject when a key is baked; warn only on dev/source.
        if BAKED_SPEC_PUBKEYS:
            raise SpecFeedError("refusing to fetch the spec feed over plain http — use https")
        log.warning("spec feed over plain http (%s) — use https (dev only)", url.split("?")[0])

    with urllib.request.urlopen(url, timeout=30) as resp:  # noqa: S310 — explicit user action
        # Cap the read BEFORE verifying/parsing so a hostile feed can't exhaust memory.
        raw = resp.read(MAX_BUNDLE_BYTES + 1)
    if len(raw) > MAX_BUNDLE_BYTES:
        raise SpecFeedError(f"spec feed response exceeds {MAX_BUNDLE_BYTES} bytes — refusing")
    doc = json.loads(raw.decode("utf-8"))
    bundle, signature = doc.get("bundle"), doc.get("signature", "")
    if not isinstance(bundle, dict):
        raise SpecFeedError("feed response missing a 'bundle' object")
    if trust:
        if not verify_bundle(bundle, signature, trust):
            raise SpecFeedError("bundle signature verification FAILED — refusing to apply")
    else:
        log.warning("no spec pubkey baked/configured — applying the bundle UNVERIFIED (dev only)")
    return apply_bundle(bundle)


def clear_overlay() -> None:
    """Remove any applied overlay (revert to the packaged specs). Best-effort."""
    import shutil

    shutil.rmtree(_overlay_dir(), ignore_errors=True)
