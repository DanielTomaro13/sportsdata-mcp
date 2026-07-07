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

Requires: graphql-core (pip install graphql-core) + httpx (already a dependency).

Usage:
    .venv/bin/python scripts/reseed_entain_apq.py            # probe + fix
    .venv/bin/python scripts/reseed_entain_apq.py --dry-run  # probe + report only

After a run that changed hashes, restart any long-lived MCP server processes
(the launchd ingest spawns fresh processes per cycle and needs nothing).

NOTE for `refresh-hashes entain`: after this script runs, yaml hashes for
re-seeded ops intentionally DIVERGE from the bundle manifest. Running
refresh-hashes would "restore" the bundle's (dead, evicted) hashes and re-break
those ops — prefer this script whenever the failure is PersistedQueryNotFound
on hashes that refresh-hashes claims are already up to date.
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path

import httpx
from graphql.language import ast as gql_ast
from graphql.language.printer import print_ast

REPO = Path(__file__).resolve().parent.parent
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


# ── JS object-literal → Python data ──────────────────────────────────────────
# The bundle stores each operation as a plain AST literal: unquoted identifier
# keys, backtick strings, numbers, booleans, nested arrays/objects. No computed
# values or variable references (verified across all 127 ops).

class JSLiteralParser:
    def __init__(self, src: str) -> None:
        self.src = src
        self.i = 0

    def error(self, msg: str) -> Exception:
        return ValueError(f"{msg} at offset {self.i}: {self.src[self.i:self.i + 40]!r}")

    def ws(self) -> None:
        while self.i < len(self.src) and self.src[self.i] in " \t\r\n":
            self.i += 1

    def parse_value(self):
        self.ws()
        c = self.src[self.i]
        if c == "{":
            return self.parse_object()
        if c == "[":
            return self.parse_array()
        if c in "`'\"":
            return self.parse_string(c)
        if self.src.startswith(("!0", "!1"), self.i):  # minifier booleans
            self.i += 2
            return self.src[self.i - 1] == "0"
        m = re.match(r"true|false|null|void 0|-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?", self.src[self.i:])
        if m:
            tok = m.group(0)
            self.i += len(tok)
            if tok == "true":
                return True
            if tok == "false":
                return False
            if tok in ("null", "void 0"):
                return None
            return float(tok) if any(ch in tok for ch in ".eE") else int(tok)
        raise self.error("unexpected value")

    def parse_string(self, quote: str) -> str:
        assert self.src[self.i] == quote
        self.i += 1
        out: list[str] = []
        while True:
            c = self.src[self.i]
            if c == "\\":
                nxt = self.src[self.i + 1]
                mapped = {"n": "\n", "t": "\t", "r": "\r", "b": "\b", "f": "\f", "0": "\0"}.get(nxt)
                if nxt == "u":
                    out.append(chr(int(self.src[self.i + 2 : self.i + 6], 16)))
                    self.i += 6
                    continue
                out.append(mapped if mapped is not None else nxt)
                self.i += 2
                continue
            if c == quote:
                self.i += 1
                return "".join(out)
            out.append(c)
            self.i += 1

    def parse_object(self) -> dict:
        assert self.src[self.i] == "{"
        self.i += 1
        obj: dict = {}
        self.ws()
        if self.src[self.i] == "}":
            self.i += 1
            return obj
        while True:
            self.ws()
            m = re.match(r"[A-Za-z_$][\w$]*", self.src[self.i:])
            if m:
                key = m.group(0)
                self.i += len(key)
            elif self.src[self.i] in "`'\"":
                key = self.parse_string(self.src[self.i])
            else:
                raise self.error("expected object key")
            self.ws()
            if self.src[self.i] != ":":
                raise self.error("expected ':'")
            self.i += 1
            obj[key] = self.parse_value()
            self.ws()
            if self.src[self.i] == ",":
                self.i += 1
                continue
            if self.src[self.i] == "}":
                self.i += 1
                return obj
            raise self.error("expected ',' or '}'")

    def parse_array(self) -> list:
        assert self.src[self.i] == "["
        self.i += 1
        arr: list = []
        self.ws()
        if self.src[self.i] == "]":
            self.i += 1
            return arr
        while True:
            arr.append(self.parse_value())
            self.ws()
            if self.src[self.i] == ",":
                self.i += 1
                continue
            if self.src[self.i] == "]":
                self.i += 1
                return arr
            raise self.error("expected ',' or ']'")


def _snake(name: str) -> str:
    return re.sub(r"(?<!^)(?=[A-Z])", "_", name).lower()


def dict_to_ast(node):
    """Recursively convert a dict-shaped GraphQL AST into graphql-core nodes."""
    if isinstance(node, list):
        return tuple(dict_to_ast(n) for n in node)
    if not isinstance(node, dict):
        return node
    kind = node["kind"]
    cls = getattr(gql_ast, f"{kind[0].upper()}{kind[1:]}Node")
    kwargs = {}
    for key, value in node.items():
        if key == "kind":
            continue
        if key == "operation":
            kwargs[key] = gql_ast.OperationType(value)
            continue
        kwargs[_snake(key)] = dict_to_ast(value)
    return cls(**kwargs)


# ── bundle fetch + extraction ─────────────────────────────────────────────────

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


def extract_document(bundle: str, name: str) -> dict | None:
    for op_kind in ("query", "mutation", "subscription"):
        marker = (
            "{kind:`Document`,definitions:[{kind:`OperationDefinition`,"
            f"operation:`{op_kind}`,name:{{kind:`Name`,value:`{name}`"
        )
        idx = bundle.find(marker)
        if idx >= 0:
            return JSLiteralParser(bundle[idx:]).parse_value()
    return None


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
            query = print_ast(dict_to_ast(doc))
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
