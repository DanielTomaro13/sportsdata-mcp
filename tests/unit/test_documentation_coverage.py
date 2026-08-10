"""Every provider must have documentation, and its `doc_url` must resolve.

`doc_url` is not decorative — it is rendered into tool descriptions, so a broken one
sends a model (or a person) to a GitHub 404. Four providers shipped that way
(theoddsapi, pandascore, cfbd, footballdataorg): specs written, docs never followed,
nothing to notice it.

A word count is a crude proxy for "documented", but it catches the real failure — a stub
that exists only to satisfy a link — and it cannot be argued with the way "is this good
enough" can be.
"""

from __future__ import annotations

import pathlib
import re

import pytest

from sportsdata_mcp.spec_loader import load_all_specs

ROOT = pathlib.Path(__file__).resolve().parents[2]
DOCS = ROOT / "documentation"
SPECS = sorted(load_all_specs(), key=lambda s: s.provider.id)
IDS = [s.provider.id for s in SPECS]


def _doc_path(spec) -> pathlib.Path | None:
    """The file a provider's doc_url points at."""
    m = re.search(r"documentation/([^)\s]+\.md)", spec.provider.doc_url or "")
    return DOCS / m.group(1) if m else None


@pytest.mark.parametrize("spec", SPECS, ids=IDS)
def test_every_provider_declares_a_doc_url(spec):
    assert spec.provider.doc_url, f"{spec.provider.id} has no doc_url"


@pytest.mark.parametrize("spec", SPECS, ids=IDS)
def test_every_doc_url_points_at_a_file_that_exists(spec):
    """The bug this file was written for."""
    path = _doc_path(spec)
    assert path is not None, f"{spec.provider.id}: doc_url is not a documentation/*.md link"
    assert path.exists(), f"{spec.provider.id}: doc_url points at {path.name}, which does not exist"


@pytest.mark.parametrize("spec", SPECS, ids=IDS)
def test_docs_are_substantive_not_stubs(spec):
    """400 words is roughly: what it is, why it is here, how to authenticate, a tool
    table, and the one thing that will bite you. Below that, something is missing."""
    path = _doc_path(spec)
    words = len(path.read_text().split())
    assert words >= 400, f"{spec.provider.id}: {path.name} is {words} words — likely a stub"


@pytest.mark.parametrize("spec", SPECS, ids=IDS)
def test_docs_mention_every_tool(spec):
    """A tool absent from its provider's page is undiscoverable except by listing tools —
    which is exactly what the documentation exists to save people from."""
    text = _doc_path(spec).read_text()
    missing = [t.name for t in spec.all_tools() if t.name not in text]
    assert not missing, f"{spec.provider.id}: undocumented tools: {missing}"


@pytest.mark.parametrize(
    "spec", [s for s in SPECS if s.provider.requires_user_key], ids=[s.provider.id for s in SPECS if s.provider.requires_user_key]
)
def test_byo_docs_name_the_env_var(spec):
    """"Get a key" is useless without the variable name to put it in."""
    text = _doc_path(spec).read_text()
    envs = [
        env
        for auth in spec.provider.auth.values()
        for attr in ("env", "username_env")
        if (env := getattr(auth, attr, None))
    ]
    assert any(e in text for e in envs), f"{spec.provider.id}: doc names none of {envs}"


@pytest.mark.parametrize(
    "spec",
    [s for s in SPECS if not s.provider.shapes_verified],
    ids=[s.provider.id for s in SPECS if not s.provider.shapes_verified],
)
def test_unverified_providers_say_so_in_their_docs(spec):
    """The caveat is in every tool description; a reader of the page deserves it too,
    because "unverified" changes how much you should trust a documented field name."""
    text = _doc_path(spec).read_text().lower()
    assert "unverified" in text or "not verified" in text or "vendor" in text, spec.provider.id


def test_no_orphaned_documentation_files():
    """A page for a provider that no longer exists is worse than no page — it describes
    tools nobody can call."""
    linked = {p.name for s in SPECS if (p := _doc_path(s))}
    # Pages that intentionally document something other than one provider.
    allowed = {"README.md", "TELEMETRY.md", "ADDING_A_PROVIDER.md"}
    orphans = {p.name for p in DOCS.glob("*.md")} - linked - allowed
    assert not orphans, f"documentation with no provider: {sorted(orphans)}"
