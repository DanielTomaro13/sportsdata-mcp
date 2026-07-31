"""Extract printed GraphQL documents from Entain's deployed ops bundle.

The bundle (``vendor-graphql-ops-web-*.js``) stores each persisted operation as a
plain graphql-js AST literal — unquoted identifier keys, backtick strings, no
computed values (verified across all 127 ops). We parse that literal, rebuild it
as graphql-core AST nodes, and print it (graphql-core's printer is
printer-identical to graphql-js). An APQ registration pair only has to be
SELF-consistent — ``sha256Hash == sha256(query)`` — so the hash of what we print
is registrable regardless of what the bundle's own manifest precomputed.

Shared by ``refresh-hashes`` (refresh.entain_hashes) and the manual bulk-reseed
script (scripts/reseed_entain_apq.py).
"""

from __future__ import annotations

import hashlib
import re

from graphql.language import ast as gql_ast
from graphql.language.printer import print_ast

# ── JS object-literal → Python data ──────────────────────────────────────────


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


def extract_document(bundle_js: str, name: str) -> dict | None:
    """Find operation ``name``'s AST literal in the bundle and parse it, or None."""
    for op_kind in ("query", "mutation", "subscription"):
        marker = (
            "{kind:`Document`,definitions:[{kind:`OperationDefinition`,"
            f"operation:`{op_kind}`,name:{{kind:`Name`,value:`{name}`"
        )
        idx = bundle_js.find(marker)
        if idx >= 0:
            return JSLiteralParser(bundle_js[idx:]).parse_value()
    return None


def print_document(doc: dict) -> str:
    """Print a dict-shaped AST as GraphQL text (identical to graphql-js printing)."""
    return print_ast(dict_to_ast(doc))


def document_hash(query: str) -> str:
    return hashlib.sha256(query.encode()).hexdigest()
