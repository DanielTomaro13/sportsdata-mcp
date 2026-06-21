"""OTA spec overlay (design-fix #6): a signed spec bundle the standalone MCP can fetch +
apply into an overlay, so drifting provider specs (e.g. Entain GraphQL hashes) refresh
without a new app build. Trust mirrors the licence gate — Ed25519, kid-aware, fail-closed
when a key is baked."""

import hashlib
import json
import urllib.request

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from sportsdata_mcp import ota
from sportsdata_mcp.errors import SpecValidationError
from sportsdata_mcp.spec_loader import load_all_specs, packaged_specs_dir


def _keypair() -> tuple[str, str]:
    priv = Ed25519PrivateKey.generate()
    priv_b64 = ota._b64url_encode(
        priv.private_bytes(
            serialization.Encoding.Raw, serialization.PrivateFormat.Raw, serialization.NoEncryption()
        )
    )
    pub_b64 = ota._b64url_encode(
        priv.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    )
    return priv_b64, pub_b64


def _template_text() -> str:
    """A real, valid provider spec (the packaged _template) to use as an overlay fixture."""
    return (packaged_specs_dir() / "_template.yaml").read_text(encoding="utf-8")


def _bundle_with(version: str, files: dict[str, str], kid: str | None = None) -> dict:
    out = {
        "schema": ota.SCHEMA,
        "version": version,
        "files": {
            n: {"sha256": hashlib.sha256(c.encode()).hexdigest(), "content": c} for n, c in files.items()
        },
    }
    if kid:
        out["kid"] = kid
    return out


@pytest.fixture
def overlay(monkeypatch, tmp_path):
    """Route the overlay dir to a temp path and ensure no baked key (dev posture)."""
    d = tmp_path / "spec-overlay"
    monkeypatch.setattr(ota, "_overlay_dir", lambda: d)
    monkeypatch.setattr(ota, "BAKED_SPEC_PUBKEYS", {})
    return d


# ── sign / verify ────────────────────────────────────────────────────────────


def test_build_sign_verify_roundtrip():
    priv, pub = _keypair()
    bundle = ota.build_bundle("2026-06-22", packaged_specs_dir(), kid="k1")
    assert bundle["files"] and bundle["kid"] == "k1"
    sig = ota.sign_bundle(bundle, priv)
    assert ota.verify_bundle(bundle, sig, {"k1": pub}) is True
    # wrong key, tampered version, garbage signature all fail
    _, other = _keypair()
    assert ota.verify_bundle(bundle, sig, {"k1": other}) is False
    assert ota.verify_bundle({**bundle, "version": "9999"}, sig, {"k1": pub}) is False
    assert ota.verify_bundle(bundle, "!!!not-b64!!!", {"k1": pub}) is False


def test_verify_is_kid_aware_with_fallback():
    priv1, pub1 = _keypair()
    priv2, pub2 = _keypair()
    trusted = {"k1": pub1, "k2": pub2}
    b1 = ota.build_bundle("1", packaged_specs_dir(), kid="k1")
    b2 = ota.build_bundle("1", packaged_specs_dir(), kid="k2")
    assert ota.verify_bundle(b1, ota.sign_bundle(b1, priv1), trusted)
    assert ota.verify_bundle(b2, ota.sign_bundle(b2, priv2), trusted)
    # kid-less (legacy) still verifies against the set
    b0 = ota.build_bundle("1", packaged_specs_dir())
    assert ota.verify_bundle(b0, ota.sign_bundle(b0, priv1), trusted)
    # a wrong-kid label still verifies via fallback (kid only orders candidates)
    bx = ota.build_bundle("1", packaged_specs_dir(), kid="k2")  # labelled k2…
    assert ota.verify_bundle(bx, ota.sign_bundle(bx, priv1), trusted)  # …but signed by k1


# ── apply + overlay seam ──────────────────────────────────────────────────────


def test_apply_writes_overlay_and_loader_prefers_it(overlay):
    res = ota.apply_bundle(_bundle_with("2026-06-22", {"example.yaml": _template_text()}))
    assert res == {"applied": ["example.yaml"], "version": "2026-06-22"}
    assert (overlay / "example.yaml").is_file()
    assert ota.applied_version() == "2026-06-22"
    assert "example.yaml" in ota.overlay_spec_sources()
    # the default (no-arg) loader merges the overlay → the new provider appears
    providers = {s.provider.id for s in load_all_specs()}
    assert "example" in providers
    # an EXPLICIT dir is overlay-free (lint/tests stay deterministic)
    providers_pkg = {s.provider.id for s in load_all_specs(packaged_specs_dir())}
    assert "example" not in providers_pkg


def test_apply_rejects_corrupt_sha(overlay):
    bad = {"schema": ota.SCHEMA, "version": "1", "files": {"example.yaml": {"sha256": "0" * 64, "content": _template_text()}}}
    with pytest.raises(ota.SpecFeedError, match="sha256 mismatch"):
        ota.apply_bundle(bad)
    assert not (overlay / "example.yaml").exists()


def test_apply_rejects_bad_schema(overlay):
    with pytest.raises(ota.SpecFeedError, match="schema"):
        ota.apply_bundle({"schema": 99, "version": "1", "files": {}})


def test_apply_refuses_rollback(overlay):
    ota.apply_bundle(_bundle_with("2.0.0", {"example.yaml": _template_text()}))
    with pytest.raises(ota.SpecFeedError, match="rollback"):
        ota.apply_bundle(_bundle_with("1.9.0", {"example.yaml": _template_text()}))
    # same version re-applies fine (idempotent)
    ota.apply_bundle(_bundle_with("2.0.0", {"example.yaml": _template_text()}))


def test_apply_rejects_malformed_spec_before_writing(overlay):
    junk = "spec_version: 1\nthis is not a valid spec\n"
    bundle = {"schema": ota.SCHEMA, "version": "1", "files": {"bad.yaml": {"sha256": hashlib.sha256(junk.encode()).hexdigest(), "content": junk}}}
    with pytest.raises(SpecValidationError):
        ota.apply_bundle(bundle)
    assert not (overlay / "bad.yaml").exists()  # aborted before any write


def test_apply_skips_unexpected_filenames(overlay):
    payload = _template_text()
    bundle = _bundle_with("1", {"example.yaml": payload})
    # smuggle a path-traversal + an underscore file — both must be skipped, not written
    bundle["files"]["../evil.yaml"] = {"sha256": hashlib.sha256(payload.encode()).hexdigest(), "content": payload}
    bundle["files"]["_capabilities.yaml"] = {"sha256": hashlib.sha256(payload.encode()).hexdigest(), "content": payload}
    res = ota.apply_bundle(bundle)
    assert res["applied"] == ["example.yaml"]
    assert not (overlay.parent / "evil.yaml").exists()
    assert not (overlay / "_capabilities.yaml").exists()


# ── fetch + clear ──────────────────────────────────────────────────────────────


def test_fetch_and_apply_verifies_signature(overlay, monkeypatch):
    priv, pub = _keypair()
    bundle = _bundle_with("1", {"example.yaml": _template_text()}, kid="k1")
    doc = {"bundle": bundle, "signature": ota.sign_bundle(bundle, priv)}

    class _Resp:
        def __init__(self, body): self._b = body
        def read(self, n=-1): return self._b
        def __enter__(self): return self
        def __exit__(self, *a): return False

    monkeypatch.setattr(urllib.request, "urlopen", lambda url, timeout=30: _Resp(json.dumps(doc).encode()))
    # right key → applies
    assert ota.fetch_and_apply("https://feed.invalid/b", trusted={"k1": pub})["applied"] == ["example.yaml"]
    # wrong key → refused
    _, other = _keypair()
    with pytest.raises(ota.SpecFeedError, match="verification FAILED"):
        ota.fetch_and_apply("https://feed.invalid/b", trusted={"k1": other})


def test_apply_rejects_blank_or_garbage_version(overlay):
    for bad in ("", "   ", "v2", "latest"):
        with pytest.raises(ota.SpecFeedError, match="version"):
            ota.apply_bundle(_bundle_with(bad, {"example.yaml": _template_text()}))


def test_cross_scheme_versions_order_numerically(overlay):
    # date and semver both order via _version_key (digit-led), so anti-rollback still fires
    # across schemes — no lexicographic fallback. A date (2026…) outranks a semver (1.x).
    ota.apply_bundle(_bundle_with("2026-06-22", {"example.yaml": _template_text()}))
    with pytest.raises(ota.SpecFeedError, match="rollback"):
        ota.apply_bundle(_bundle_with("1.0.0", {"example.yaml": _template_text()}))


def test_apply_is_all_or_nothing(overlay):
    good = _template_text()
    bundle = {
        "schema": ota.SCHEMA,
        "version": "1",
        "files": {
            "aaa.yaml": {"sha256": hashlib.sha256(good.encode()).hexdigest(), "content": good},
            "bbb.yaml": {"sha256": "0" * 64, "content": good},  # bad sha → whole apply aborts
        },
    }
    with pytest.raises(ota.SpecFeedError, match="sha256 mismatch"):
        ota.apply_bundle(bundle)
    # the earlier-validated file must NOT have been written (no torn-bundle state)
    assert not (overlay / "aaa.yaml").exists()
    assert ota.applied_version() is None


def test_overlay_dup_tool_falls_back_to_packaged(overlay):
    # Two overlay specs that both define tool `example_ping` → cross-spec collision in the
    # merged set. load_all_specs must NOT crash; it drops the overlay and serves packaged.
    overlay.mkdir(parents=True, exist_ok=True)
    (overlay / "a.yaml").write_text(_template_text(), encoding="utf-8")
    (overlay / "b.yaml").write_text(_template_text(), encoding="utf-8")
    providers = {s.provider.id for s in load_all_specs()}  # no raise
    assert "example" not in providers  # overlay dropped → packaged-only
    assert providers == {s.provider.id for s in load_all_specs(packaged_specs_dir())}


def test_fetch_rejects_oversized_and_bad_scheme(overlay, monkeypatch):
    with pytest.raises(ota.SpecFeedError, match="scheme"):
        ota.fetch_and_apply("file:///etc/passwd", trusted={})

    class _Big:
        def read(self, n=-1): return b"x" * (ota.MAX_BUNDLE_BYTES + 1)
        def __enter__(self): return self
        def __exit__(self, *a): return False

    monkeypatch.setattr(urllib.request, "urlopen", lambda url, timeout=30: _Big())
    with pytest.raises(ota.SpecFeedError, match="exceeds"):
        ota.fetch_and_apply("https://feed.invalid/b", trusted={})


def test_clear_overlay_reverts_to_packaged(overlay):
    ota.apply_bundle(_bundle_with("1", {"example.yaml": _template_text()}))
    assert "example" in {s.provider.id for s in load_all_specs()}
    ota.clear_overlay()
    assert ota.applied_version() is None
    assert "example" not in {s.provider.id for s in load_all_specs()}
