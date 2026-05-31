"""Parse the 127-operation GraphQL catalogue table out of documentation/Entain.md
and emit a YAML `graphql.operations` block. One-off generator used to seed
specs/entain.yaml; the live `refresh-hashes entain` CLI supersedes it thereafter.

Usage: python scripts/gen_entain_ops.py > /tmp/entain_ops.yaml
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

DOC = Path(__file__).resolve().parent.parent / "documentation" / "Entain.md"

# | `Name` | `query` | `hash` | `Variables...` | ✅ |
ROW = re.compile(
    r"^\|\s*`(?P<name>[A-Za-z0-9_]+)`\s*"
    r"\|\s*`(?P<type>query|mutation)`\s*"
    r"\|\s*`(?P<hash>[a-f0-9]{64})`\s*"
    r"\|\s*(?P<vars>.*?)\s*"
    r"\|\s*(?P<verified>.*?)\s*\|\s*$"
)


def _clean_vars(raw: str) -> str:
    raw = raw.strip()
    if raw in ("_(none)_", "", "_none_"):
        return ""
    # Strip surrounding backticks if the whole cell is code-fenced.
    return raw.strip("`").strip()


def main() -> int:
    rows = []
    for line in DOC.read_text().splitlines():
        m = ROW.match(line)
        if not m:
            continue
        rows.append(
            (
                m["name"],
                m["hash"],
                _clean_vars(m["vars"]),
                "✅" in m["verified"],
            )
        )

    # De-dupe by name (the doc lists each op once, but guard anyway), keep order.
    seen = set()
    uniq = []
    for name, h, v, verified in rows:
        if name in seen:
            continue
        seen.add(name)
        uniq.append((name, h, v, verified))

    out = ["graphql:", "  operations:"]
    for name, h, v, verified in uniq:
        # Double-quote the variables string and escape embedded quotes/backslashes.
        vq = v.replace("\\", "\\\\").replace('"', '\\"')
        parts = [f"name: {name}", f'sha256: "{h}"', f'variables: "{vq}"']
        if verified:
            parts.append("verified: true")
        out.append("    - { " + ", ".join(parts) + " }")

    print("\n".join(out))
    print(f"\n# {len(uniq)} operations", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
