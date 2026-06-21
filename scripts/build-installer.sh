#!/bin/sh
# Build the standalone MCP installer bundle (commerce Phase 3 — direct download, NOT
# the App Store). Produces a self-contained onedir: the `sportsdata-mcp` binary + its
# bundled Python runtime + the provider specs, so the customer needs no Python.
#
#   pip install -e ".[build]"
#   sh scripts/build-installer.sh
#   sh scripts/make-macos-app.sh        # wrap as sportsdata-mcp.app
#   sh scripts/sign-and-notarize.sh     # Gatekeeper-clean DMG (needs an Apple Developer ID)
#
# The entitlement public key + service URL are baked into licence.py (do that after you
# deploy the Worker — see services/entitlement/README.md step 7), so the bundle verifies
# licences offline with no extra config.
set -eu

REPO="$(cd "$(dirname "$0")/.." && pwd)"
APP_NAME="sportsdata-mcp"
VERSION="$("$REPO/.venv/bin/python" -c 'import sportsdata_mcp; print(sportsdata_mcp.__version__)' 2>/dev/null \
           || python -c 'import sportsdata_mcp; print(sportsdata_mcp.__version__)')"

echo "building $APP_NAME $VERSION (onedir, direct-download)"
cd "$REPO"

PY="$REPO/.venv/bin/pyinstaller"
[ -x "$PY" ] || PY="pyinstaller"

"$PY" \
  --name "$APP_NAME" \
  --onedir \
  --console \
  --collect-all sportsdata_mcp \
  --collect-all fastmcp \
  --collect-submodules cryptography \
  --copy-metadata sportsdata-mcp \
  --noconfirm \
  --clean \
  "$REPO/src/sportsdata_mcp/__main__.py" || {
    echo "pyinstaller failed — did you run: pip install -e '.[build]' ?" >&2; exit 1; }

# NOTE: the distributable is the .app produced by make-macos-app.sh + packaged with
# `ditto` (see release.yml) — NOT a `zip` of this onedir. Plain `zip` drops the framework
# symlinks and breaks the nested ad-hoc signatures, which makes the app read as "damaged".
echo "done → dist/$APP_NAME/  (onedir)"
echo "next: sh scripts/make-macos-app.sh   then   sh scripts/sign-and-notarize.sh"
