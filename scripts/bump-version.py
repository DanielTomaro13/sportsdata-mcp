#!/usr/bin/env python3
"""Move the version in every file that carries it, in one command.

The version is written down in four places — pyproject.toml, `__version__`, and both
server.json and manifest.json — and nothing derived them from each other, so a bump was
four hand-edits and a miss was silent. Two suites already assert the four agree
(`test_distribution_metadata.py`, `test_packaging.py`), but they only run in the slow
`test` job: v0.27.1 shipped with three of the four left at 0.27.0 and main stayed red
until someone read an 8-minute log. This script is the write half of that contract, and
`--check` is a sub-second read half CI can run up front.

    python scripts/bump-version.py 0.28.0   # rewrite all four
    python scripts/bump-version.py --check  # verify they agree, exit 1 if not

pyproject.toml is the source of truth for `--check`; the others must match it.

Stdlib only and no imports from the package itself, so it runs before an install and
cannot be broken by the code it is versioning.
"""

from __future__ import annotations

import argparse
import copy
import json
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]

# Keep in step with the parametrised pointers in tests/unit/test_distribution_metadata.py.
# The tests are deliberately an independent statement of the same contract, so a site
# added there and not here fails CI rather than passing quietly.
JSON_SITES: dict[str, list[tuple[str | int, ...]]] = {
    "server.json": [("version",), ("packages", 0, "version")],
    "manifest.json": [("version",)],
}
TEXT_SITES: dict[str, str] = {
    "pyproject.toml": r'^version = "([^"]+)"',
    "src/sportsdata_mcp/__init__.py": r'^__version__ = "([^"]+)"',
}
SOURCE_OF_TRUTH = "pyproject.toml"

SEMVER = re.compile(r"^\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?$")


def _at(node, pointer):
    for key in pointer:
        node = node[key]
    return node


def _set_at(node, pointer, value):
    for key in pointer[:-1]:
        node = node[key]
    node[pointer[-1]] = value


def read_versions() -> dict[str, str]:
    """Every version site, keyed by a human-readable name, in a stable order."""
    found: dict[str, str] = {}
    for path, pattern in TEXT_SITES.items():
        text = (ROOT / path).read_text()
        m = re.search(pattern, text, re.MULTILINE)
        if not m:
            sys.exit(f"{path}: no version line matching {pattern!r}")
        found[path] = m.group(1)
    for path, pointers in JSON_SITES.items():
        data = json.loads((ROOT / path).read_text())
        for pointer in pointers:
            try:
                found[f"{path}{list(pointer)}"] = _at(data, pointer)
            except (KeyError, IndexError):
                sys.exit(f"{path}: no value at {list(pointer)}")
    return found


def rewrite_text(path: str, pattern: str, new: str) -> str | None:
    """Rewrite the one version line. Returns the new text, or None if already current."""
    raw = (ROOT / path).read_text()
    m = re.search(pattern, raw, re.MULTILINE)
    assert m  # read_versions() has already proved the line exists
    if m.group(1) == new:
        return None
    line = m.group(0)
    out, n = re.subn(
        re.escape(line), line.replace(m.group(1), new), raw, count=1, flags=re.MULTILINE
    )
    if n != 1:
        sys.exit(f"{path}: expected to rewrite 1 version line, rewrote {n}")
    return out


def rewrite_json(path: str, pointers: list[tuple], new: str) -> str | None:
    """Rewrite the version at each pointer by editing the raw text, so the file keeps
    its formatting — reserialising would reflow files that humans maintain.

    The textual substitution is verified structurally afterwards: the parsed result must
    equal the original with exactly these pointers changed. A `"version"` key elsewhere
    in the file that happened to hold the same string would be caught here as an
    over-replacement, and nothing is written."""
    raw = (ROOT / path).read_text()
    before = json.loads(raw)
    stale = {_at(before, p) for p in pointers} - {new}
    if not stale:
        return None

    out = raw
    for value in stale:
        for pointer in pointers:
            key = pointer[-1]
            out = out.replace(f'"{key}": "{value}"', f'"{key}": "{new}"')

    expected = copy.deepcopy(before)
    for pointer in pointers:
        _set_at(expected, pointer, new)
    if json.loads(out) != expected:
        sys.exit(
            f"{path}: rewriting the version changed something else too — refusing to "
            f"write. Edit it by hand and check {[list(p) for p in pointers]}."
        )
    return out


def check() -> int:
    found = read_versions()
    truth = found[SOURCE_OF_TRUTH]
    stale = {name: v for name, v in found.items() if v != truth}
    width = max(len(n) for n in found)
    for name, version in found.items():
        mark = "✗" if name in stale else "✓"
        print(f"  {mark} {name:<{width}}  {version}")
    if stale:
        print(
            f"\n{len(stale)} file(s) disagree with {SOURCE_OF_TRUTH} ({truth}).\n"
            f"Fix with:  python scripts/bump-version.py {truth}",
            file=sys.stderr,
        )
        return 1
    print(f"\nall {len(found)} version sites agree: {truth}")
    return 0


def bump(new: str) -> int:
    if not SEMVER.match(new):
        sys.exit(f"{new!r} is not a semantic version (expected N.N.N)")

    read_versions()  # fail before writing anything if a site has gone missing
    pending: dict[pathlib.Path, str] = {}
    for path, pattern in TEXT_SITES.items():
        if (text := rewrite_text(path, pattern, new)) is not None:
            pending[ROOT / path] = text
    for path, pointers in JSON_SITES.items():
        if (text := rewrite_json(path, pointers, new)) is not None:
            pending[ROOT / path] = text

    if not pending:
        print(f"already at {new} — nothing to do")
        return 0
    for file, text in pending.items():  # every rewrite verified: now commit them to disk
        file.write_text(text)
        print(f"  {file.relative_to(ROOT)} → {new}")

    if f"## {new}" not in (ROOT / "CHANGELOG.md").read_text():
        print(f"\nnote: CHANGELOG.md has no '## {new}' section yet.")
    return check()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("version", nargs="?", help="the new version, e.g. 0.28.0")
    parser.add_argument(
        "--check", action="store_true", help="verify every site agrees; do not write"
    )
    args = parser.parse_args()
    if args.check == bool(args.version):
        parser.error("give a version to bump to, or --check — not both, not neither")
    return check() if args.check else bump(args.version)


if __name__ == "__main__":
    sys.exit(main())
