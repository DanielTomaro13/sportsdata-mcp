"""Refresh persisted-query sha256 hashes from a provider's deployed JS bundle.

Entain's GraphQL gateway only accepts the hash currently registered by the live
front-end bundle; that hash rotates on every deploy (see the "hash drift" note in
documentation/Entain.md). This module re-extracts the operation→hash table from
the current bundle and writes the fresh hashes back into the provider spec.

The extraction is provider-agnostic — it is driven entirely by the spec's
``provider.hash_refresh`` block plus its ``graphql.operations`` list — but Entain
is the only provider that needs it today.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import httpx

from ..spec import Spec

_DEFAULT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; sportsdata-mcp/0.1)",
    "Accept": "*/*",
}

_HEX64 = r"[a-f0-9]{64}"
_OP_NAME = r"[A-Za-z][A-Za-z0-9_]*"
_Q = r"[\"'`]"  # string quote: double, single, or template-literal backtick

# The deployed Entain bundle stores the manifest as JS tuples with backtick
# strings: [`HomeSportsScreen`,`<64-hex>`]. This is the primary form.
_TUPLE_FORM = re.compile(rf"""\[\s*{_Q}(?P<name>{_OP_NAME}){_Q}\s*,\s*{_Q}(?P<hash>{_HEX64}){_Q}\s*\]""")
# Object-literal fallbacks (other Apollo manifest shapes); key order varies, so
# match both orderings within one object (no braces between the keys).
_NAME_THEN_HASH = re.compile(
    rf"""name\s*:\s*{_Q}(?P<name>{_OP_NAME}){_Q}[^{{}}]{{0,240}}?hash\s*:\s*{_Q}(?P<hash>{_HEX64}){_Q}"""
)
_HASH_THEN_NAME = re.compile(
    rf"""hash\s*:\s*{_Q}(?P<hash>{_HEX64}){_Q}[^{{}}]{{0,240}}?name\s*:\s*{_Q}(?P<name>{_OP_NAME}){_Q}"""
)
# Flat manifest map form: "OperationName":"<64-hex>".
_MAP_FORM = re.compile(rf"""{_Q}(?P<name>{_OP_NAME}){_Q}\s*:\s*{_Q}(?P<hash>{_HEX64}){_Q}""")

# A spec operation line: ``- { name: X, sha256: "<64-hex>", ... }``.
_SPEC_OP_LINE = re.compile(r'(?P<head>- \{ name: (?P<name>\w+), sha256: ")(?P<hash>[a-f0-9]{64})(?P<tail>")')


class RefreshError(Exception):
    """Raised when the bundle cannot be located, fetched, or parsed."""


@dataclass
class HashChange:
    name: str
    old: str
    new: str


@dataclass
class DiffResult:
    bundle_url: str
    bundle_bytes: int
    extracted: int
    changed: list[HashChange]
    unchanged: list[str]
    missing_from_bundle: list[str]


def _glob_to_regex(pattern: str) -> re.Pattern[str]:
    """Turn a ``*``-glob bundle pattern into a regex (``*`` → non-greedy any)."""
    return re.compile(".*?".join(re.escape(p) for p in pattern.split("*")))


def discover_bundle_url(landing_html: str, pattern: str, host: str) -> str | None:
    """Find the first bundle path matching ``pattern`` in the landing HTML."""
    m = _glob_to_regex(pattern).search(landing_html)
    if not m:
        return None
    path = m.group(0)
    if path.startswith("http"):
        return path
    return host.rstrip("/") + "/" + path.lstrip("/")


def extract_operations(bundle_js: str) -> dict[str, str]:
    """Extract every ``operationName → sha256`` pair found in a JS bundle."""
    out: dict[str, str] = {}
    for rx in (_TUPLE_FORM, _NAME_THEN_HASH, _HASH_THEN_NAME, _MAP_FORM):
        for m in rx.finditer(bundle_js):
            out.setdefault(m.group("name"), m.group("hash"))
    return out


def fetch_latest_hashes(
    host: str,
    pattern: str,
    *,
    client: httpx.Client | None = None,
    timeout: float = 30.0,
    echo: Callable[[str], None] = lambda _s: None,
) -> tuple[str, int, dict[str, str]]:
    """Fetch the landing page, locate + download the bundle, extract hashes.

    Returns ``(bundle_url, bundle_bytes, {name: hash})``.
    """
    own = client is None
    client = client or httpx.Client(timeout=timeout, headers=_DEFAULT_HEADERS, follow_redirects=True)
    try:
        echo(f"🔍 Fetching {host}")
        landing = client.get(host)
        landing.raise_for_status()
        echo(f"🔍 Locating {pattern}")
        url = discover_bundle_url(landing.text, pattern, host)
        if not url:
            raise RefreshError(f"no bundle matching {pattern!r} found at {host}")
        echo(f"   → {url}")
        bundle = client.get(url)
        bundle.raise_for_status()
        size = len(bundle.content)
        echo(f"🔍 Downloading bundle ({size // 1024} KB) … done")
        echo("🔍 Extracting [name, sha256] pairs from minified bundle")
        ops = extract_operations(bundle.text)
        echo(f"   → {len(ops)} operations")
        return url, size, ops
    except httpx.HTTPError as e:
        raise RefreshError(f"fetch failed: {e}") from e
    finally:
        if own:
            client.close()


def diff_operations(spec: Spec, latest: dict[str, str]) -> tuple[list[HashChange], list[str], list[str]]:
    """Compare spec hashes against freshly-extracted ones.

    Returns ``(changed, unchanged_names, missing_from_bundle_names)``.
    """
    changed: list[HashChange] = []
    unchanged: list[str] = []
    missing: list[str] = []
    for op in spec.graphql.operations if spec.graphql else []:
        new = latest.get(op.name)
        if new is None:
            missing.append(op.name)
        elif new != op.sha256:
            changed.append(HashChange(op.name, op.sha256, new))
        else:
            unchanged.append(op.name)
    return changed, unchanged, missing


def apply_changes(spec_path: Path, changes: list[HashChange]) -> int:
    """Rewrite only the changed sha256 values in place, preserving formatting."""
    if not changes:
        return 0
    new_by_name = {c.name: c.new for c in changes}
    applied: set[str] = set()

    def _repl(m: re.Match[str]) -> str:
        name = m.group("name")
        want = new_by_name.get(name)
        if want is not None and m.group("hash") != want:
            applied.add(name)
            return m.group("head") + want + m.group("tail")
        return m.group(0)

    new_text = _SPEC_OP_LINE.sub(_repl, spec_path.read_text())
    spec_path.write_text(new_text)
    return len(applied)


def run_refresh(
    spec: Spec,
    spec_path: Path,
    *,
    write: bool = True,
    client: httpx.Client | None = None,
    echo: Callable[[str], None] = print,
) -> DiffResult:
    """Full refresh: fetch bundle, diff against spec, optionally write back."""
    hr = spec.provider.hash_refresh
    if hr is None:
        raise RefreshError(f"provider '{spec.provider.id}' has no hash_refresh block configured")
    url, size, latest = fetch_latest_hashes(hr.bundle_host, hr.bundle_url_pattern, client=client, echo=echo)
    changed, unchanged, missing = diff_operations(spec, latest)
    if write and changed:
        apply_changes(spec_path, changed)
    return DiffResult(
        bundle_url=url,
        bundle_bytes=size,
        extracted=len(latest),
        changed=changed,
        unchanged=unchanged,
        missing_from_bundle=missing,
    )
