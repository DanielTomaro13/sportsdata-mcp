"""Refresh persisted-query sha256 hashes from a provider's deployed JS bundle.

Entain's gateway keeps APQ registrations in an evictable cache, and an APQ pair
only has to be self-consistent (``sha256Hash == sha256(query)``) — it does not
have to match the hash precomputed in the JS bundle's manifest. So instead of
trusting the manifest (which can point at hashes the gateway has evicted, and
which diverges from the yaml after a reseed), this module extracts each
operation's AST from the bundle, prints it with graphql-core, hashes the printed
text, REGISTERS that pair with the gateway, and writes both the hashes (into the
spec yaml) and the printed documents (into ``{provider}.documents.json``, the
sidecar the runtime dispatcher uses to self-heal future evictions).

Ops whose AST cannot be found in the bundle fall back to the manifest-extracted
hash (no self-heal document available for those).

The flow is provider-agnostic — driven by the spec's ``provider.hash_refresh``
block plus its ``graphql.operations`` list — but Entain is the only provider
that needs it today.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

import httpx

from ..spec import Spec
from .entain_documents import document_hash, extract_document, print_document

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
    # Ops whose printed document was extracted (and written to the sidecar on a
    # non-dry run) — these self-heal at runtime. Manifest-only ops are the rest.
    documents: dict[str, str] = field(default_factory=dict)
    documents_written: int = 0
    # Changed ops whose gateway registration POST did not stick (best-effort:
    # the runtime APQ retry re-registers them on first use anyway).
    register_failed: list[str] = field(default_factory=list)


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


def fetch_bundle(
    host: str,
    pattern: str,
    client: httpx.Client,
    echo: Callable[[str], None] = lambda _s: None,
) -> tuple[str, str]:
    """Fetch the landing page, locate + download the bundle. Returns ``(url, js_text)``."""
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
        echo(f"🔍 Downloading bundle ({len(bundle.content) // 1024} KB) … done")
        return url, bundle.text
    except httpx.HTTPError as e:
        raise RefreshError(f"fetch failed: {e}") from e


def fetch_latest_hashes(
    host: str,
    pattern: str,
    *,
    client: httpx.Client | None = None,
    timeout: float = 30.0,
    echo: Callable[[str], None] = lambda _s: None,
) -> tuple[str, int, dict[str, str]]:
    """Fetch + locate the bundle, extract the manifest ``{name: hash}`` table.

    Returns ``(bundle_url, bundle_bytes, {name: hash})``.
    """
    own = client is None
    client = client or httpx.Client(timeout=timeout, headers=_DEFAULT_HEADERS, follow_redirects=True)
    try:
        url, text = fetch_bundle(host, pattern, client, echo)
        echo("🔍 Extracting [name, sha256] pairs from minified bundle")
        ops = extract_operations(text)
        echo(f"   → {len(ops)} operations")
        return url, len(text.encode()), ops
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


def _gateway_endpoint(spec: Spec) -> tuple[str, dict[str, str]] | None:
    """Resolve the persisted-query gateway URL + headers from the spec's dispatcher."""
    disp = next((d for d in spec.dispatchers if d.kind == "graphql_persisted"), None)
    if disp is None:
        return None
    base = spec.provider.base_urls.get(disp.base or "default")
    if base is None:
        return None
    return base.rstrip("/") + (disp.endpoint or ""), {**spec.provider.default_headers, **disp.default_headers}


def register_with_gateway(client: httpx.Client, gateway: str, headers: dict[str, str], name: str, query: str, sha: str) -> bool:
    """POST the (query, sha) pair so the gateway's APQ cache stores it, then probe.

    Empty variables: ops with required variables fail validation AFTER the APQ
    layer stores the pair, and no session cookie is sent — nothing (including
    mutations) actually executes.
    """
    ext = {"persistedQuery": {"version": 1, "sha256Hash": sha}}
    try:
        client.post(
            gateway,
            headers=headers,
            json={"operationName": name, "query": query, "variables": {}, "extensions": ext},
        )
        probe = client.get(
            gateway,
            headers=headers,
            params={"operationName": name, "variables": "{}", "extensions": json.dumps(ext)},
        )
        return "PersistedQueryNotFound" not in probe.text
    except httpx.HTTPError:
        return False


def write_documents(spec_path: Path, provider_id: str, documents: dict[str, str]) -> Path:
    """Write the printed-documents sidecar next to the spec yaml."""
    path = spec_path.parent / f"{provider_id}.documents.json"
    path.write_text(json.dumps(documents, indent=1, sort_keys=True) + "\n")
    return path


def run_refresh(
    spec: Spec,
    spec_path: Path,
    *,
    write: bool = True,
    client: httpx.Client | None = None,
    echo: Callable[[str], None] = print,
) -> DiffResult:
    """Full refresh: fetch bundle, print + hash each op's document, diff against the
    spec, then (unless dry-run) register changed pairs with the gateway and write
    the yaml hashes + the documents sidecar."""
    hr = spec.provider.hash_refresh
    if hr is None:
        raise RefreshError(f"provider '{spec.provider.id}' has no hash_refresh block configured")

    own = client is None
    client = client or httpx.Client(timeout=30.0, headers=_DEFAULT_HEADERS, follow_redirects=True)
    try:
        url, bundle = fetch_bundle(hr.bundle_host, hr.bundle_url_pattern, client, echo)
        echo("🔍 Extracting operation documents (AST literals) from bundle")
        manifest = extract_operations(bundle)
        documents: dict[str, str] = {}
        latest: dict[str, str] = {}
        for op in spec.graphql.operations if spec.graphql else []:
            doc = extract_document(bundle, op.name)
            if doc is not None:
                query = print_document(doc)
                documents[op.name] = query
                latest[op.name] = document_hash(query)
            elif op.name in manifest:
                # No AST in the bundle — fall back to the manifest hash. Usable,
                # but the runtime cannot self-heal this op if it gets evicted.
                latest[op.name] = manifest[op.name]
        echo(f"   → {len(documents)} documents, {len(latest) - len(documents)} manifest-only")

        changed, unchanged, missing = diff_operations(spec, latest)
        result = DiffResult(
            bundle_url=url,
            bundle_bytes=len(bundle.encode()),
            extracted=len(latest),
            changed=changed,
            unchanged=unchanged,
            missing_from_bundle=missing,
            documents=documents,
        )
        if not write:
            return result

        # New hashes are sha256(printed doc) — self-consistent but not yet in the
        # gateway's APQ cache. Register them now so calls succeed immediately; if
        # one doesn't stick, the runtime dispatcher's APQ retry heals it on first use.
        gateway_info = _gateway_endpoint(spec)
        to_register = [c for c in changed if c.name in documents]
        if to_register and gateway_info is None:
            echo("   ⚠ no graphql_persisted dispatcher/base URL — skipping gateway registration")
        elif to_register:
            gateway, headers = gateway_info
            echo(f"🔍 Registering {len(to_register)} changed pair(s) with {gateway}")
            for c in to_register:
                if not register_with_gateway(client, gateway, headers, c.name, documents[c.name], c.new):
                    result.register_failed.append(c.name)

        if changed:
            apply_changes(spec_path, changed)
        if documents:
            write_documents(spec_path, spec.provider.id, documents)
            result.documents_written = len(documents)
        return result
    finally:
        if own:
            client.close()
