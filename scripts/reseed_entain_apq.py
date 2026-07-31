"""Re-seed evicted Entain persisted-query hashes via the APQ registration flow.

Entain's Apollo gateway keeps persisted queries in an evictable cache (observed
flushed wholesale on 2026-07-07: 113 of 127 ops gone while the deployed bundle
was unchanged, so `refresh-hashes entain` reported "already up to date" yet every
call returned PersistedQueryNotFound). Real browsers self-heal via the standard
APQ retry — POST the full query document alongside its sha256 — which re-registers
the pair for everyone. This script does the same for every operation in
specs/entain.yaml whose hash the gateway no longer recognises.

The registered pair only has to be SELF-consistent (sha256Hash == sha256(query)):
it does not need to match the hash precomputed in the JS bundle. We therefore
extract each operation's AST from the deployed bundle, print it with graphql-core
(printer-identical to graphql-js), hash what we printed, register that pair, and
write the new hash back into specs/entain.yaml.

Requires: graphql-core + httpx (both declared dependencies of the package).

Usage:
    .venv/bin/python scripts/reseed_entain_apq.py            # probe + fix
    .venv/bin/python scripts/reseed_entain_apq.py --dry-run  # probe + report only

After a run that changed hashes, restart any long-lived MCP server processes
(the launchd ingest spawns fresh processes per cycle and needs nothing).

NOTE: this script is now mostly a manual probe/bulk-reseed tool. The runtime
dispatcher self-heals PersistedQueryNotFound automatically via the printed
documents in specs/entain.documents.json (the standard Apollo APQ retry), and
`sportsdata-mcp refresh-hashes entain` regenerates hashes FROM those printed
documents (registering them with the gateway) rather than trusting the bundle
manifest — so neither can re-break re-seeded ops anymore.
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path

import httpx

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

from sportsdata_mcp.refresh.entain_documents import extract_document, print_document

SPEC = REPO / "src" / "sportsdata_mcp" / "specs" / "entain.yaml"
GATEWAY = "https://api.ladbrokes.com.au/gql/router"
BUNDLE_HOST = "https://www.ladbrokes.com.au"
BUNDLE_PATTERN = re.compile(r"assets/vendor-graphql-ops-web-[\w-]+\.js")
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
    ),
    "Content-Type": "application/json",
}
SPEC_OP_LINE = re.compile(r'(- \{ name: (\w+), sha256: ")([a-f0-9]{64})(")')


# ── bundle fetch ──────────────────────────────────────────────────────────────

def fetch_bundle(client: httpx.Client) -> str:
    landing = client.get(BUNDLE_HOST)
    landing.raise_for_status()
    m = BUNDLE_PATTERN.search(landing.text)
    if not m:
        sys.exit(f"no bundle matching {BUNDLE_PATTERN.pattern} at {BUNDLE_HOST}")
    url = f"{BUNDLE_HOST}/{m.group(0)}"
    print(f"bundle: {url}")
    r = client.get(url)
    r.raise_for_status()
    return r.text


# ── gateway probes ────────────────────────────────────────────────────────────

def is_registered(client: httpx.Client, name: str, sha: str) -> bool:
    r = client.get(
        GATEWAY,
        params={
            "operationName": name,
            "variables": "{}",
            "extensions": json.dumps({"persistedQuery": {"version": 1, "sha256Hash": sha}}),
        },
    )
    return "PersistedQueryNotFound" not in r.text


def register(client: httpx.Client, name: str, query: str, sha: str) -> None:
    # Empty variables: ops with required variables fail validation AFTER the
    # APQ layer stores the pair, and we send no session cookie — nothing
    # (including the 14 mutations) actually executes.
    client.post(
        GATEWAY,
        json={
            "operationName": name,
            "query": query,
            "variables": {},
            "extensions": {"persistedQuery": {"version": 1, "sha256Hash": sha}},
        },
    )


def main() -> int:
    dry_run = "--dry-run" in sys.argv
    spec_text = SPEC.read_text()
    ops = {m[2]: m[3] for m in SPEC_OP_LINE.finditer(spec_text)}
    print(f"{len(ops)} operations in {SPEC.relative_to(REPO)}")

    with httpx.Client(timeout=30.0, headers=HEADERS, follow_redirects=True) as client:
        evicted = [name for name, sha in ops.items() if not is_registered(client, name, sha)]
        print(f"evicted: {len(evicted)}" + (f" — {', '.join(evicted)}" if evicted else ""))
        if not evicted:
            return 0
        if dry_run:
            print("dry run — no changes made")
            return 1

        bundle = fetch_bundle(client)
        new_hashes: dict[str, str] = {}
        failed: list[str] = []
        for name in evicted:
            doc = extract_document(bundle, name)
            if doc is None:
                failed.append(f"{name} (not in bundle)")
                continue
            query = print_document(doc)
            sha = hashlib.sha256(query.encode()).hexdigest()
            register(client, name, query, sha)
            if not is_registered(client, name, sha):
                failed.append(f"{name} (registration did not stick)")
                continue
            if sha != ops[name]:
                new_hashes[name] = sha
            print(f"  ✓ {name} → {sha[:16]}…")

    if new_hashes:
        spec_text = SPEC_OP_LINE.sub(
            lambda m: m[1] + new_hashes.get(m[2], m[3]) + m[4], spec_text
        )
        SPEC.write_text(spec_text)
        print(f"updated {len(new_hashes)} hash(es) in {SPEC.relative_to(REPO)} — restart MCP servers")
    if failed:
        print(f"FAILED ({len(failed)}): {', '.join(failed)}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
