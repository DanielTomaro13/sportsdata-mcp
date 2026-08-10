"""The files that describe this server to the outside world must not drift.

server.json, manifest.json and pyproject.toml each carry a version, and server.json and
manifest.json each carry a description with counts in it. Nothing recomputes them, so
they rot silently — and the rot is only visible to USERS, in a registry listing or an
install dialog, never to us.

This is not hypothetical. When these tests were written, server.json advertised
"~500 tools, 28 providers" at version 0.22.1 while the package was 0.23.1 with 736 tools
across 60 providers. The publish workflow's only defence was a comment saying "keep the
version in server.json in lockstep with pyproject.toml".
"""

from __future__ import annotations

import json
import pathlib
import re

import pytest

from sportsdata_mcp.spec_loader import expand_wildcard_groups, load_all_specs

ROOT = pathlib.Path(__file__).resolve().parents[2]


def _pyproject_version() -> str:
    m = re.search(r'^version = "(.+)"', (ROOT / "pyproject.toml").read_text(), re.MULTILINE)
    assert m
    return m.group(1)


def _counts() -> tuple[int, int, int]:
    """Providers, TOOLS, keyless providers.

    Tools means `all_tools()` — endpoints plus dispatchers — because that is what the
    server actually registers and therefore what a user gets. Counting endpoints alone
    undercounted by 15 and made every public claim quietly wrong in our own favour's
    opposite direction.
    """
    specs = load_all_specs()
    free = {g.split(".")[0] for g in expand_wildcard_groups(["free"], specs)}
    return len(specs), sum(len(s.all_tools()) for s in specs), len(free)


@pytest.mark.parametrize("path,pointer", [
    ("server.json", ("version",)),
    ("server.json", ("packages", 0, "version")),
    ("manifest.json", ("version",)),
])
def test_versions_are_in_lockstep_with_pyproject(path, pointer):
    """A registry entry pointing at a version that is not on PyPI is a broken install."""
    node = json.loads((ROOT / path).read_text())
    for key in pointer:
        node = node[key]
    assert node == _pyproject_version(), f"{path}{list(pointer)} is stale"


def test_advertised_counts_are_not_wildly_wrong():
    """Exact counts would fail on every provider added, which teaches people to edit the
    test rather than the metadata. A 20% band still catches the real failure mode:
    numbers left untouched across many releases."""
    nprov, ntool, _ = _counts()
    text = (ROOT / "server.json").read_text() + (ROOT / "manifest.json").read_text()
    for claimed in (int(m) for m in re.findall(r"(\d+)\s+tools", text)):
        assert abs(claimed - ntool) <= ntool * 0.2, f"'{claimed} tools' vs {ntool} actual"
    for claimed in (int(m) for m in re.findall(r"(\d+)\s+providers", text)):
        assert abs(claimed - nprov) <= nprov * 0.2, f"'{claimed} providers' vs {nprov} actual"


def test_readme_counts_are_not_wildly_wrong():
    text = (ROOT / "README.md").read_text()
    nprov, ntool, _ = _counts()
    head = text[: text.index("\n## ")]  # the badge/summary block, not every mention
    for claimed in (int(m) for m in re.findall(r"~?(\d+) tools", head)):
        assert abs(claimed - ntool) <= ntool * 0.2, f"README says '{claimed} tools', actual {ntool}"
    for claimed in (int(m) for m in re.findall(r"~?(\d+) providers", head)):
        assert abs(claimed - nprov) <= nprov * 0.2, f"README says '{claimed} providers', actual {nprov}"


def test_every_manifest_key_maps_to_a_real_env_var():
    """A key prompt that writes an env var nothing reads is worse than no prompt: the
    user pastes a credential, sees no error, and gets no data."""
    manifest = json.loads((ROOT / "manifest.json").read_text())
    declared = {
        env
        for spec in load_all_specs()
        for auth in spec.provider.auth.values()
        for attr in ("env", "username_env", "password_env")
        if (env := getattr(auth, attr, None))
    }
    for name in manifest["server"]["mcp_config"]["env"]:
        assert name in declared, f"manifest sets {name}, but no spec reads it"


def test_smithery_and_manifest_offer_the_same_keys():
    """Two install surfaces that disagree about which providers exist is a support
    burden nobody notices until someone asks why the extension has a field the web
    install doesn't."""
    manifest = json.loads((ROOT / "manifest.json").read_text())
    smithery = (ROOT / "smithery.yaml").read_text()
    for env in manifest["server"]["mcp_config"]["env"]:
        assert env in smithery, f"{env} is offered in manifest.json but not smithery.yaml"


def test_free_is_the_advertised_default_everywhere():
    """`free` needing no setup is the headline promise; a default of `all` would greet a
    new user with tools that cannot work."""
    manifest = json.loads((ROOT / "manifest.json").read_text())
    assert manifest["user_config"]["groups"]["default"] == "free"
    assert 'default: "free"' in (ROOT / "smithery.yaml").read_text()
